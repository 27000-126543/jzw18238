import numpy as np
import threading
import time
import os
import tempfile
import wave
from typing import Optional, List, Dict, Any
from PyQt5.QtCore import QObject, pyqtSignal

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    pyaudio = None

try:
    import soundfile as sf
    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False
    sf = None


class AudioRecorder(QObject):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)
    level_changed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self._running = False
        self._record_thread: Optional[threading.Thread] = None
        self._sample_rate = 44100
        self._channels = 2
        self._record_system_audio = True
        self._record_microphone = True
        self._mic_device_index: Optional[int] = None
        self._system_device_index: Optional[int] = None
        self._temp_file: Optional[str] = None
        self._lock = threading.Lock()

        self._mic_frames: List[bytes] = []
        self._system_frames: List[bytes] = []

        self._mic_channels = 1
        self._mic_rate = 44100
        self._sys_channels = 2
        self._sys_rate = 44100

        self._audio = pyaudio.PyAudio() if HAS_PYAUDIO else None

    def set_sample_rate(self, rate: int):
        self._sample_rate = rate

    def set_channels(self, channels: int):
        self._channels = channels

    def set_record_system_audio(self, enabled: bool):
        self._record_system_audio = enabled

    def set_record_microphone(self, enabled: bool):
        self._record_microphone = enabled

    def set_microphone_device(self, device_id: int):
        self._mic_device_index = device_id

    def set_system_audio_device(self, device_id: int):
        self._system_device_index = device_id

    @staticmethod
    def get_input_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_PYAUDIO:
            return devices
        p = None
        try:
            p = pyaudio.PyAudio()
            wasapi_idx = -1
            try:
                wasapi_idx = p.get_host_api_info_by_type(pyaudio.paWASAPI)['index']
            except Exception:
                pass

            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info['maxInputChannels'] <= 0:
                        continue
                    name = info['name']
                    nl = name.lower()
                    if any(kw in nl for kw in ['loopback', 'stereo mix', 'what u hear', 'wave out mix', '立体声混音', '您听到的声音']):
                        continue
                    host_api = int(info.get('hostApi', 0))
                    if host_api == wasapi_idx:
                        continue
                    devices.append({
                        'id': i,
                        'name': name,
                        'channels': info['maxInputChannels'],
                        'sample_rate': int(info['defaultSampleRate'])
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"Error listing mic devices: {e}")
        finally:
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass
        return devices

    @staticmethod
    def get_system_audio_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_PYAUDIO:
            return devices
        p = None
        try:
            p = pyaudio.PyAudio()
            wasapi_idx = -1
            wasapi_default_output_idx = -1
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                wasapi_idx = wasapi_info['index']
                wasapi_default_output_idx = wasapi_info['defaultOutputDevice']
                output_info = p.get_device_info_by_index(wasapi_default_output_idx)
                devices.insert(0, {
                    'id': output_info['index'],
                    'name': f"WASAPI 系统声音 ({output_info['name']}) [推荐]",
                    'channels': min(2, int(output_info['maxOutputChannels'])),
                    'sample_rate': int(output_info['defaultSampleRate']),
                    'wasapi_loopback': True
                })
            except Exception as e:
                print(f"WASAPI loopback device not found: {e}")

            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info['index'] == wasapi_default_output_idx:
                        continue
                    name = info['name'].lower()
                    is_loopback = any(kw in name for kw in ['loopback', 'stereo mix', 'what u hear', 'wave out mix', '立体声混音', '您听到的声音'])
                    if info['maxInputChannels'] > 0 and is_loopback:
                        devices.append({
                            'id': i,
                            'name': info['name'],
                            'channels': info['maxInputChannels'],
                            'sample_rate': int(info['defaultSampleRate'])
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"Error listing system audio devices: {e}")
        finally:
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass
        return devices

    @staticmethod
    def get_output_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_PYAUDIO:
            return devices
        p = None
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info['maxOutputChannels'] > 0:
                        devices.append({
                            'id': i,
                            'name': info['name'],
                            'channels': info['maxOutputChannels'],
                            'sample_rate': int(info['defaultSampleRate'])
                        })
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass
        return devices

    def start_recording(self):
        if self._running or not HAS_PYAUDIO:
            return

        self._running = True
        self._mic_frames = []
        self._system_frames = []
        self._mic_channels = 1
        self._mic_rate = self._sample_rate
        self._sys_channels = 2
        self._sys_rate = self._sample_rate

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        self.recording_started.emit()

    def _open_mic_stream(self):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            dev_idx = self._mic_device_index
            if dev_idx is None:
                try:
                    dev_idx = self._audio.get_default_input_device_info()['index']
                except Exception:
                    return None

            info = self._audio.get_device_info_by_index(dev_idx)
            ch = int(info['maxInputChannels'])
            if ch <= 0:
                return None
            sr = int(info['defaultSampleRate'])

            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=sr,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=1024
            )
            self._mic_channels = ch
            self._mic_rate = sr
            return stream
        except Exception as e:
            print(f"Failed to open microphone: {e}")
            return None

    def _open_system_stream(self):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            wasapi_info = self._audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            output_dev_idx = wasapi_info['defaultOutputDevice']
            output_info = self._audio.get_device_info_by_index(output_dev_idx)

            ch = min(2, int(output_info['maxOutputChannels']))
            if ch <= 0:
                ch = 2
            sr = int(output_info['defaultSampleRate'])

            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=sr,
                input=True,
                input_device_index=output_dev_idx,
                frames_per_buffer=1024
            )
            self._sys_channels = ch
            self._sys_rate = sr
            return stream
        except Exception as e:
            print(f"WASAPI loopback open failed: {e}")

        if self._system_device_index is not None:
            return self._open_normal_input(self._system_device_index)

        return None

    def _open_normal_input(self, device_idx: int):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            info = self._audio.get_device_info_by_index(device_idx)
            ch = min(2, int(info['maxInputChannels']))
            if ch <= 0:
                return None
            sr = int(info['defaultSampleRate'])
            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=sr,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=1024
            )
            self._sys_channels = ch
            self._sys_rate = sr
            return stream
        except Exception as e:
            print(f"Normal input open failed: {e}")
            return None

    def _record_loop(self):
        mic_stream = None
        sys_stream = None

        try:
            if self._record_microphone:
                mic_stream = self._open_mic_stream()

            if self._record_system_audio:
                sys_stream = self._open_system_stream()

            if mic_stream is None and sys_stream is None:
                print("Warning: No audio input available, recording video only.")
                while self._running:
                    time.sleep(0.1)
                return

            mic_level_window = []

            while self._running:
                if mic_stream and mic_stream.is_active():
                    try:
                        data = mic_stream.read(1024, exception_on_overflow=False)
                        self._mic_frames.append(data)
                        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        if len(arr) > 0:
                            rms = float(np.sqrt(np.mean(arr ** 2)))
                            mic_level_window.append(rms)
                            if len(mic_level_window) > 10:
                                mic_level_window.pop(0)
                            avg_rms = sum(mic_level_window) / len(mic_level_window)
                            self.level_changed.emit(min(1.0, avg_rms * 8))
                    except Exception:
                        pass

                if sys_stream and sys_stream.is_active():
                    try:
                        data = sys_stream.read(1024, exception_on_overflow=False)
                        self._system_frames.append(data)
                    except Exception:
                        pass

                time.sleep(0.001)

        except Exception as e:
            print(f"Recording thread error: {e}")

        finally:
            for s in (mic_stream, sys_stream):
                if s:
                    try:
                        s.stop_stream()
                        s.close()
                    except Exception:
                        pass

            self._running = False
            self._save_to_wav()

    def _frames_to_array(self, frames: List[bytes], actual_ch: int, actual_rate: int, target_rate: int) -> Optional[np.ndarray]:
        if len(frames) == 0:
            return None
        try:
            raw = b''.join(frames)
            data_int16 = np.frombuffer(raw, dtype=np.int16)

            if actual_ch <= 0:
                actual_ch = 1

            total_samples = len(data_int16)
            frames_count = total_samples // actual_ch
            if frames_count <= 0:
                return None

            data_int16 = data_int16[:frames_count * actual_ch]
            data_int16 = data_int16.reshape(-1, actual_ch)
            data_float = data_int16.astype(np.float32) / 32768.0

            if data_float.shape[1] == 1:
                data_float = np.column_stack([data_float[:, 0], data_float[:, 0]])
            elif data_float.shape[1] > 2:
                data_float = data_float[:, :2]

            if actual_rate != target_rate:
                try:
                    from scipy.signal import resample_poly
                    from math import gcd
                    g = gcd(target_rate, actual_rate)
                    up = target_rate // g
                    down = actual_rate // g
                    new_len = int(len(data_float) * up / down)
                    if new_len > 0:
                        data_float = resample_poly(data_float, up, down, axis=0).astype(np.float32)
                except ImportError:
                    try:
                        ratio = target_rate / actual_rate
                        new_len = int(len(data_float) * ratio)
                        if new_len > 0 and len(data_float.shape) == 2:
                            import cv2
                            data_float = cv2.resize(data_float, (data_float.shape[1], new_len), interpolation=cv2.INTER_LINEAR).astype(np.float32)
                    except Exception:
                        pass
                except Exception:
                    pass

            return data_float

        except Exception as e:
            print(f"Frame conversion error: {e}")
            return None

    def _save_to_wav(self):
        try:
            if len(self._mic_frames) == 0 and len(self._system_frames) == 0:
                return

            target_rate = self._sample_rate
            target_ch = 2

            mic_data = self._frames_to_array(self._mic_frames, self._mic_channels, self._mic_rate, target_rate)
            sys_data = self._frames_to_array(self._system_frames, self._sys_channels, self._sys_rate, target_rate)

            mixed = None

            if mic_data is not None and sys_data is not None:
                min_len = min(len(mic_data), len(sys_data))
                mic_data = mic_data[:min_len]
                sys_data = sys_data[:min_len]
                mixed = (mic_data * 0.6 + sys_data * 0.6).astype(np.float32)
                mixed = np.clip(mixed, -1.0, 1.0)
            elif mic_data is not None:
                mixed = mic_data
            elif sys_data is not None:
                mixed = sys_data

            if mixed is None or len(mixed) == 0:
                return

            temp_dir = tempfile.gettempdir()
            wav_path = os.path.join(temp_dir, f"audio_rec_{int(time.time())}.wav")

            if HAS_SOUNDFILE:
                sf.write(wav_path, mixed, target_rate)
            else:
                self._write_wav(wav_path, mixed, target_rate, target_ch)

            with self._lock:
                self._temp_file = wav_path

        except Exception as e:
            print(f"Audio save error: {e}")

    def _write_wav(self, path: str, data: np.ndarray, rate: int, channels: int):
        try:
            with wave.open(path, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                int_data = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
                wf.writeframes(int_data.tobytes())
        except Exception as e:
            print(f"WAV write error: {e}")

    def stop_recording(self) -> Optional[str]:
        if not self._running:
            return self._temp_file

        self._running = False

        if self._record_thread:
            self._record_thread.join(timeout=10)

        result = None
        with self._lock:
            if self._temp_file and os.path.exists(self._temp_file):
                result = self._temp_file

        self.recording_stopped.emit(result or "")
        return result

    def is_running(self) -> bool:
        return self._running

    def __del__(self):
        try:
            if self._audio:
                self._audio.terminate()
        except Exception:
            pass
