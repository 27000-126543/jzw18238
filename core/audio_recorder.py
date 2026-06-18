import numpy as np
import threading
import queue
import time
import os
import tempfile
import wave
import struct
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

        self._mic_stream = None
        self._system_stream = None
        self._audio = pyaudio.PyAudio() if HAS_PYAUDIO else None

        self._mic_frames: List[bytes] = []
        self._system_frames: List[bytes] = []

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
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0 and int(info.get('hostApi', 0)) == 0:
                    name = info['name']
                    if 'loopback' not in name.lower() and 'stereo mix' not in name.lower() and 'what u hear' not in name.lower():
                        devices.append({
                            'id': i,
                            'name': name,
                            'channels': info['maxInputChannels'],
                            'sample_rate': int(info['defaultSampleRate'])
                        })
            p.terminate()
        except Exception as e:
            print(f"Error listing mic devices: {e}")
        return devices

    @staticmethod
    def get_system_audio_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_PYAUDIO:
            return devices
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                name = info['name'].lower()
                is_loopback = ('loopback' in name or 'stereo mix' in name
                               or 'what u hear' in name or 'wave out mix' in name
                               or '立体声混音' in name or '您听到的声音' in name)

                if info['maxInputChannels'] > 0 and is_loopback:
                    devices.append({
                        'id': i,
                        'name': info['name'],
                        'channels': info['maxInputChannels'],
                        'sample_rate': int(info['defaultSampleRate'])
                    })

            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_output = p.get_device_info_by_index(wasapi_info['defaultOutputDevice'])
                loopback_idx = default_output['index']
                devices.insert(0, {
                    'id': loopback_idx,
                    'name': f"WASAPI 系统声音 ({default_output['name']}) [推荐]",
                    'channels': 2,
                    'sample_rate': int(default_output['defaultSampleRate']),
                    'wasapi_loopback': True
                })
            except Exception as e:
                print(f"WASAPI detection: {e}")

            p.terminate()
        except Exception as e:
            print(f"Error listing system audio devices: {e}")
        return devices

    @staticmethod
    def get_output_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_PYAUDIO:
            return devices
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxOutputChannels'] > 0:
                    devices.append({
                        'id': i,
                        'name': info['name'],
                        'channels': info['maxOutputChannels'],
                        'sample_rate': int(info['defaultSampleRate'])
                    })
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

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        self.recording_started.emit()

    def _open_mic_stream(self):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            dev_idx = self._mic_device_index
            if dev_idx is None:
                dev_idx = self._audio.get_default_input_device_info()['index']

            info = self._audio.get_device_info_by_index(dev_idx)
            ch = min(2, int(info['maxInputChannels']))
            sr = min(self._sample_rate, int(info['defaultSampleRate']))

            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=sr,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=1024
            )
            stream._actual_channels = ch
            stream._actual_rate = sr
            return stream
        except Exception as e:
            print(f"Failed to open microphone: {e}")
            return None

    def _open_system_stream(self):
        if not HAS_PYAUDIO or not self._audio:
            return None

        if self._system_device_index is not None:
            try:
                info = self._audio.get_device_info_by_index(self._system_device_index)
                name = info['name'].lower()
                if 'loopback' in name or 'wasapi' in name:
                    return self._open_wasapi_loopback()
                else:
                    return self._open_normal_input(self._system_device_index)
            except Exception as e:
                print(f"System device open failed: {e}")

        return self._open_wasapi_loopback()

    def _open_wasapi_loopback(self):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            wasapi_idx = self._audio.get_host_api_info_by_type(pyaudio.paWASAPI)['index']
            output_info = self._audio.get_device_info_by_index(
                self._audio.get_host_api_info_by_index(wasapi_idx)['defaultOutputDevice']
            )

            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=min(2, int(output_info['maxOutputChannels'])),
                rate=int(output_info['defaultSampleRate']),
                input=True,
                input_device_index=output_info['index'],
                frames_per_buffer=1024,
                stream_flags=pyaudio.paLoopback
            )
            stream._actual_channels = min(2, int(output_info['maxOutputChannels']))
            stream._actual_rate = int(output_info['defaultSampleRate'])
            stream._is_loopback = True
            return stream
        except Exception as e:
            print(f"WASAPI loopback unavailable: {e}, trying fallback...")

            try:
                p = self._audio
                for i in range(p.get_device_count()):
                    info = p.get_device_info_by_index(i)
                    name = info['name'].lower()
                    if ('stereo mix' in name or 'what u hear' in name
                            or 'wave out mix' in name or '立体声混音' in name):
                        return self._open_normal_input(i)
            except Exception as e2:
                print(f"Fallback also failed: {e2}")

            return None

    def _open_normal_input(self, device_idx: int):
        if not HAS_PYAUDIO or not self._audio:
            return None
        try:
            info = self._audio.get_device_info_by_index(device_idx)
            ch = min(2, int(info['maxInputChannels']))
            sr = min(self._sample_rate, int(info['defaultSampleRate']))
            stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=sr,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=1024
            )
            stream._actual_channels = ch
            stream._actual_rate = sr
            stream._is_loopback = False
            return stream
        except Exception as e:
            print(f"Normal input open failed: {e}")
            return None

    def _record_loop(self):
        try:
            self._mic_stream = None
            self._system_stream = None

            if self._record_microphone:
                self._mic_stream = self._open_mic_stream()
                if self._mic_stream:
                    self._mic_stream.start_stream()

            if self._record_system_audio:
                self._system_stream = self._open_system_stream()
                if self._system_stream:
                    self._system_stream.start_stream()

            if self._mic_stream is None and self._system_stream is None:
                print("Warning: No audio input available, recording video only.")
                while self._running:
                    time.sleep(0.1)
                self._finalize_recording()
                return

            mic_level_window = []

            while self._running:
                try:
                    if self._mic_stream and self._mic_stream.is_active():
                        try:
                            data = self._mic_stream.read(1024, exception_on_overflow=False)
                            self._mic_frames.append(data)
                            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                            if len(arr) > 0:
                                rms = float(np.sqrt(np.mean(arr ** 2)))
                                mic_level_window.append(rms)
                                if len(mic_level_window) > 10:
                                    mic_level_window.pop(0)
                                avg_rms = sum(mic_level_window) / len(mic_level_window)
                                self.level_changed.emit(min(1.0, avg_rms * 8))
                        except Exception as e:
                            pass

                    if self._system_stream and self._system_stream.is_active():
                        try:
                            data = self._system_stream.read(1024, exception_on_overflow=False)
                            self._system_frames.append(data)
                        except Exception as e:
                            pass

                    time.sleep(0.001)
                except Exception as e:
                    print(f"Capture read error: {e}")

            self._finalize_recording()

        except Exception as e:
            print(f"Recording thread error: {e}")
            self._finalize_recording()

    def _finalize_recording(self):
        try:
            if self._mic_stream:
                try:
                    self._mic_stream.stop_stream()
                    self._mic_stream.close()
                except:
                    pass
                self._mic_stream = None

            if self._system_stream:
                try:
                    self._system_stream.stop_stream()
                    self._system_stream.close()
                except:
                    pass
                self._system_stream = None
        except Exception:
            pass

        self._running = False
        self._save_to_wav()

    def _save_to_wav(self):
        try:
            if len(self._mic_frames) == 0 and len(self._system_frames) == 0:
                return

            target_rate = self._sample_rate
            target_ch = 2

            mic_data = self._frames_to_array(self._mic_frames, target_rate, target_ch)
            sys_data = self._frames_to_array(self._system_frames, target_rate, target_ch)

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

    def _frames_to_array(self, frames: List[bytes], target_rate: int, target_ch: int) -> Optional[np.ndarray]:
        if len(frames) == 0:
            return None
        try:
            raw = b''.join(frames)
            data_int16 = np.frombuffer(raw, dtype=np.int16)

            actual_ch = 2
            actual_rate = target_rate
            if self._mic_stream and frames is self._mic_frames and hasattr(self._mic_stream, '_actual_channels'):
                actual_ch = self._mic_stream._actual_channels
                actual_rate = self._mic_stream._actual_rate
            elif self._system_stream and frames is self._system_frames and hasattr(self._system_stream, '_actual_channels'):
                actual_ch = self._system_stream._actual_channels
                actual_rate = self._system_stream._actual_rate

            if actual_ch > 1:
                data_int16 = data_int16.reshape(-1, actual_ch)
            else:
                data_int16 = data_int16.reshape(-1, 1)

            data_float = data_int16.astype(np.float32) / 32768.0

            if data_float.shape[1] == 1 and target_ch == 2:
                data_float = np.repeat(data_float, 2, axis=1)
            elif data_float.shape[1] >= 2 and target_ch == 2:
                data_float = data_float[:, :2]

            if actual_rate != target_rate:
                try:
                    import cv2
                    ratio = target_rate / actual_rate
                    new_len = int(len(data_float) * ratio)
                    if new_len > 0 and len(data_float.shape) == 2:
                        resized = cv2.resize(data_float, (data_float.shape[1], new_len), interpolation=cv2.INTER_LINEAR)
                        data_float = resized.astype(np.float32)
                except Exception:
                    pass

            return data_float

        except Exception as e:
            print(f"Frame conversion error: {e}")
            return None

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
