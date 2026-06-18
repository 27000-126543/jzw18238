import numpy as np
import threading
import time
import os
import tempfile
import wave
from typing import Optional, List, Dict, Any, Tuple
from PyQt5.QtCore import QObject, pyqtSignal

try:
    import soundcard as sc
    import soundfile as sf
    HAS_SOUNDCARD = True
except ImportError:
    HAS_SOUNDCARD = False
    sc = None
    sf = None


class AudioRecorder(QObject):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)
    level_changed = pyqtSignal(float)

    mic_ready = pyqtSignal(bool, str)
    system_ready = pyqtSignal(bool, str)
    mic_captured_samples = pyqtSignal(int)
    system_captured_samples = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._running = False
        self._record_thread: Optional[threading.Thread] = None
        self._sample_rate = 48000
        self._channels = 2
        self._record_system_audio = True
        self._record_microphone = True
        self._mic_device_id: Optional[str] = None
        self._system_device_id: Optional[str] = None
        self._temp_file: Optional[str] = None
        self._lock = threading.Lock()

        self._mic_data: List[np.ndarray] = []
        self._sys_data: List[np.ndarray] = []

        self._mic_samplerate = 48000
        self._sys_samplerate = 48000
        self._mic_channels = 1
        self._sys_channels = 2

        self._mic_error = ""
        self._sys_error = ""
        self._mic_ok = False
        self._sys_ok = False

    def set_sample_rate(self, rate: int):
        self._sample_rate = rate

    def set_channels(self, channels: int):
        self._channels = channels

    def set_record_system_audio(self, enabled: bool):
        self._record_system_audio = enabled

    def set_record_microphone(self, enabled: bool):
        self._record_microphone = enabled

    def set_microphone_device(self, device_id):
        self._mic_device_id = str(device_id) if device_id is not None else None

    def set_system_audio_device(self, device_id):
        self._system_device_id = str(device_id) if device_id is not None else None

    @staticmethod
    def get_input_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_SOUNDCARD:
            return devices
        try:
            for d in sc.all_microphones(include_loopback=False):
                try:
                    devices.append({
                        'id': d.id,
                        'name': d.name,
                        'channels': min(2, d.channels),
                        'sample_rate': int(d.default_samplerate)
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"get_input_devices error: {e}")
        return devices

    @staticmethod
    def get_system_audio_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_SOUNDCARD:
            return devices
        try:
            default_out = sc.default_speaker()
            if default_out is not None:
                try:
                    lb = sc.get_microphone(id=default_out.id, include_loopback=True)
                    devices.insert(0, {
                        'id': lb.id,
                        'name': f"系统声音 - {lb.name} (推荐/WASAPI)",
                        'channels': min(2, lb.channels),
                        'sample_rate': int(lb.default_samplerate),
                        'is_loopback': True
                    })
                except Exception:
                    pass

            seen = set(d['id'] for d in devices)
            for d in sc.all_microphones(include_loopback=True):
                try:
                    name_lower = d.name.lower()
                    is_lb = ('loopback' in name_lower or d.isloopback if hasattr(d, 'isloopback') else False)
                    if is_lb and d.id not in seen:
                        devices.append({
                            'id': d.id,
                            'name': d.name,
                            'channels': min(2, d.channels),
                            'sample_rate': int(d.default_samplerate),
                            'is_loopback': True
                        })
                        seen.add(d.id)
                except Exception:
                    continue
        except Exception as e:
            print(f"get_system_audio_devices error: {e}")
        return devices

    @staticmethod
    def get_output_devices() -> List[Dict[str, Any]]:
        devices = []
        if not HAS_SOUNDCARD:
            return devices
        try:
            for d in sc.all_speakers():
                try:
                    devices.append({
                        'id': d.id,
                        'name': d.name,
                        'channels': d.channels,
                        'sample_rate': int(d.default_samplerate)
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return devices

    def start_recording(self):
        if self._running or not HAS_SOUNDCARD:
            if not HAS_SOUNDCARD:
                self.mic_ready.emit(False, "缺少 soundcard 库")
                self.system_ready.emit(False, "缺少 soundcard 库")
            return

        self._running = True
        self._mic_data = []
        self._sys_data = []
        self._mic_error = ""
        self._sys_error = ""
        self._mic_ok = False
        self._sys_ok = False

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        self.recording_started.emit()

    def _record_loop(self):
        mic_recorder = None
        sys_recorder = None
        mic_thread = None
        sys_thread = None
        stop_flag = threading.Event()

        try:
            if self._record_microphone:
                try:
                    dev = None
                    if self._mic_device_id:
                        try:
                            dev = sc.get_microphone(id=self._mic_device_id, include_loopback=False)
                        except Exception:
                            pass
                    if dev is None:
                        dev = sc.default_microphone()

                    if dev is None:
                        raise RuntimeError("未找到可用的麦克风设备")

                    sr = int(dev.default_samplerate)
                    ch = min(2, dev.channels)
                    self._mic_samplerate = sr
                    self._mic_channels = ch

                    mic_recorder = dev.recorder(samplerate=sr, channels=ch)
                    mic_recorder.__enter__()

                    def _mic_read_loop():
                        level_window = []
                        while not stop_flag.is_set():
                            try:
                                data = mic_recorder.record(numframes=512)
                                if data is not None and len(data) > 0:
                                    self._mic_data.append(data.copy())
                                    arr = data.astype(np.float32).ravel()
                                    if len(arr) > 0:
                                        rms = float(np.sqrt(np.mean(arr ** 2)))
                                        level_window.append(rms)
                                        if len(level_window) > 10:
                                            level_window.pop(0)
                                        avg_rms = sum(level_window) / len(level_window)
                                        self.level_changed.emit(min(1.0, avg_rms * 10))
                            except Exception:
                                break

                    self._mic_ok = True
                    self.mic_ready.emit(True, f"麦克风就绪: {dev.name}")
                    mic_thread = threading.Thread(target=_mic_read_loop, daemon=True)
                    mic_thread.start()

                except Exception as e:
                    self._mic_ok = False
                    self._mic_error = str(e)
                    self.mic_ready.emit(False, f"麦克风启动失败: {e}")
                    mic_recorder = None

            if self._record_system_audio:
                try:
                    dev = None
                    if self._system_device_id:
                        try:
                            dev = sc.get_microphone(id=self._system_device_id, include_loopback=True)
                        except Exception:
                            pass

                    if dev is None:
                        try:
                            speaker = sc.default_speaker()
                            if speaker is not None:
                                dev = sc.get_microphone(id=speaker.id, include_loopback=True)
                        except Exception:
                            pass

                    if dev is None:
                        raise RuntimeError("未找到可用的系统声音采集设备 (需要WASAPI loopback支持)")

                    sr = int(dev.default_samplerate)
                    ch = min(2, dev.channels)
                    self._sys_samplerate = sr
                    self._sys_channels = ch

                    sys_recorder = dev.recorder(samplerate=sr, channels=ch)
                    sys_recorder.__enter__()

                    def _sys_read_loop():
                        while not stop_flag.is_set():
                            try:
                                data = sys_recorder.record(numframes=512)
                                if data is not None and len(data) > 0:
                                    self._sys_data.append(data.copy())
                            except Exception:
                                break

                    self._sys_ok = True
                    self.system_ready.emit(True, f"系统声音就绪: {dev.name}")
                    sys_thread = threading.Thread(target=_sys_read_loop, daemon=True)
                    sys_thread.start()

                except Exception as e:
                    self._sys_ok = False
                    self._sys_error = str(e)
                    self.system_ready.emit(False, f"系统声音启动失败: {e}")
                    sys_recorder = None

            if not self._mic_ok and not self._sys_ok:
                print("Warning: 没有任何音频输入可用，将录制纯视频")
                while self._running:
                    time.sleep(0.1)
            else:
                while self._running:
                    time.sleep(0.05)

        except Exception as e:
            print(f"Record loop fatal error: {e}")
        finally:
            stop_flag.set()

            if mic_thread:
                mic_thread.join(timeout=3)
            if sys_thread:
                sys_thread.join(timeout=3)

            for rec in (mic_recorder, sys_recorder):
                if rec:
                    try:
                        rec.__exit__(None, None, None)
                    except Exception:
                        pass

            self._running = False
            self._save_to_wav()

    def _resample_audio(self, data: np.ndarray, old_sr: int, new_sr: int) -> np.ndarray:
        if old_sr == new_sr or len(data) == 0:
            return data
        try:
            try:
                from scipy.signal import resample_poly
                import math
                from math import gcd
                g = gcd(new_sr, old_sr)
                up = new_sr // g
                down = old_sr // g
                return resample_poly(data, up, down, axis=0).astype(np.float32)
            except ImportError:
                ratio = new_sr / old_sr
                new_len = int(len(data) * ratio)
                if new_len == 0:
                    return data
                if data.ndim == 1:
                    import cv2
                    res = cv2.resize(data.reshape(-1, 1), (1, new_len), interpolation=cv2.INTER_LINEAR)
                    return res.astype(np.float32).ravel()
                else:
                    import cv2
                    res = cv2.resize(data, (data.shape[1], new_len), interpolation=cv2.INTER_LINEAR)
                    return res.astype(np.float32)
        except Exception as e:
            print(f"Resample error: {e}")
            return data

    def _to_stereo(self, data: np.ndarray) -> np.ndarray:
        if data.ndim == 1:
            return np.column_stack([data, data]).astype(np.float32)
        elif data.shape[1] == 1:
            return np.column_stack([data[:, 0], data[:, 0]]).astype(np.float32)
        elif data.shape[1] >= 2:
            return data[:, :2].astype(np.float32)
        return data.astype(np.float32)

    def _concat_buffers(self, chunks: List[np.ndarray]) -> Optional[np.ndarray]:
        if len(chunks) == 0:
            return None
        try:
            return np.concatenate(chunks, axis=0).astype(np.float32)
        except Exception as e:
            print(f"Concat error: {e}")
            valid = [c for c in chunks if c is not None and len(c) > 0]
            if len(valid) > 0:
                return np.concatenate(valid, axis=0).astype(np.float32)
            return None

    def _save_to_wav(self):
        try:
            mic_raw = self._concat_buffers(self._mic_data)
            sys_raw = self._concat_buffers(self._sys_data)

            if mic_raw is None and sys_raw is None:
                return

            target_sr = self._sample_rate

            mic_data = None
            if mic_raw is not None:
                mic_data = self._to_stereo(self._resample_audio(mic_raw, self._mic_samplerate, target_sr))

            sys_data = None
            if sys_raw is not None:
                sys_data = self._to_stereo(self._resample_audio(sys_raw, self._sys_samplerate, target_sr))

            mixed = None
            if mic_data is not None and sys_data is not None:
                min_len = min(len(mic_data), len(sys_data))
                mic_data = mic_data[:min_len]
                sys_data = sys_data[:min_len]
                mixed = (mic_data * 0.55 + sys_data * 0.55).astype(np.float32)
                mixed = np.clip(mixed, -0.99, 0.99)
            elif mic_data is not None:
                mixed = np.clip(mic_data, -0.99, 0.99)
            elif sys_data is not None:
                mixed = np.clip(sys_data, -0.99, 0.99)

            if mixed is None or len(mixed) == 0:
                return

            temp_dir = tempfile.gettempdir()
            wav_path = os.path.join(temp_dir, f"audio_rec_{int(time.time())}.wav")

            if sf is not None:
                sf.write(wav_path, mixed, target_sr)
            else:
                self._write_wav(wav_path, mixed, target_sr, 2)

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
                int_data = (np.clip(data, -0.99, 0.99) * 32767.0).astype(np.int16)
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

    def get_mic_status(self) -> Tuple[bool, str]:
        return self._mic_ok, self._mic_error

    def get_system_status(self) -> Tuple[bool, str]:
        return self._sys_ok, self._sys_error

    def has_mic_samples(self) -> bool:
        return len(self._mic_data) > 0 and sum(len(c) for c in self._mic_data) > 100

    def has_system_samples(self) -> bool:
        return len(self._sys_data) > 0 and sum(len(c) for c in self._sys_data) > 100

    def get_mic_audio(self) -> Tuple[Optional[np.ndarray], int]:
        if len(self._mic_data) == 0:
            return None, 0
        with self._lock:
            data = np.concatenate(self._mic_data, axis=0)
        return data.copy(), self._mic_samplerate

    def get_system_audio(self) -> Tuple[Optional[np.ndarray], int]:
        if len(self._sys_data) == 0:
            return None, 0
        with self._lock:
            data = np.concatenate(self._sys_data, axis=0)
        return data.copy(), self._sys_samplerate

    def get_mixed_audio(self) -> Tuple[Optional[np.ndarray], int]:
        mic_data, mic_sr = self.get_mic_audio()
        sys_data, sys_sr = self.get_system_audio()

        if mic_data is None and sys_data is None:
            return None, 0

        target_sr = self._sample_rate
        target_channels = self._channels

        def prepare(data, sr):
            if data is None:
                return None
            if data.ndim == 1:
                data = np.column_stack([data, data])
            if sr != target_sr:
                data = self._resample_audio(data, sr, target_sr)
            return data

        mic_ready = prepare(mic_data, mic_sr)
        sys_ready = prepare(sys_data, sys_sr)

        mixed = None
        if mic_ready is not None and sys_ready is not None:
            mixed = 0.55 * mic_ready + 0.55 * sys_ready
        elif mic_ready is not None:
            mixed = mic_ready
        elif sys_ready is not None:
            mixed = sys_ready

        if mixed is not None:
            mixed = np.clip(mixed, -0.99, 0.99)
        return mixed, target_sr
