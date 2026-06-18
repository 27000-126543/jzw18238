import numpy as np
import threading
import queue
import time
from typing import Optional, List
from PyQt5.QtCore import QObject, pyqtSignal
import os
import tempfile

try:
    import sounddevice as sd
    import soundfile as sf
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False


class AudioRecorder(QObject):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)
    level_changed = pyqtSignal(float)
    
    def __init__(self):
        super().__init__()
        self._running = False
        self._record_thread: Optional[threading.Thread] = None
        self._audio_queue: Optional[queue.Queue] = None
        self._sample_rate = 44100
        self._channels = 2
        self._record_system_audio = True
        self._record_microphone = True
        self._mic_device_id: Optional[int] = None
        self._system_device_id: Optional[int] = None
        self._temp_file: Optional[str] = None
        self._frames: List[np.ndarray] = []
        self._lock = threading.Lock()
    
    def set_sample_rate(self, rate: int):
        self._sample_rate = rate
    
    def set_channels(self, channels: int):
        self._channels = channels
    
    def set_record_system_audio(self, enabled: bool):
        self._record_system_audio = enabled
    
    def set_record_microphone(self, enabled: bool):
        self._record_microphone = enabled
    
    def set_microphone_device(self, device_id: int):
        self._mic_device_id = device_id
    
    def set_system_audio_device(self, device_id: int):
        self._system_device_id = device_id
    
    @staticmethod
    def get_input_devices() -> List[dict]:
        devices = []
        if not HAS_SOUNDDEVICE:
            return devices
        try:
            all_devices = sd.query_devices()
            for i, dev in enumerate(all_devices):
                if dev['max_input_channels'] > 0:
                    devices.append({
                        'id': i,
                        'name': dev['name'],
                        'channels': dev['max_input_channels'],
                        'sample_rate': dev['default_samplerate']
                    })
        except Exception as e:
            print(f"Error listing devices: {e}")
        return devices
    
    @staticmethod
    def get_output_devices() -> List[dict]:
        devices = []
        if not HAS_SOUNDDEVICE:
            return devices
        try:
            all_devices = sd.query_devices()
            for i, dev in enumerate(all_devices):
                if dev['max_output_channels'] > 0:
                    devices.append({
                        'id': i,
                        'name': dev['name'],
                        'channels': dev['max_output_channels'],
                        'sample_rate': dev['default_samplerate']
                    })
        except Exception as e:
            print(f"Error listing devices: {e}")
        return devices
    
    def start_recording(self):
        if self._running:
            return
        
        self._running = True
        self._frames = []
        self._audio_queue = queue.Queue()
        
        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        self.recording_started.emit()
    
    def _record_loop(self):
        try:
            mic_buffer = []
            system_buffer = []

            if not HAS_SOUNDDEVICE:
                while self._running:
                    time.sleep(0.1)
                self._combine_and_save(mic_buffer, system_buffer)
                return

            mic_stream = None
            system_stream = None

            def mic_callback(indata, frames, time_info, status):
                if status:
                    pass
                self._audio_queue.put(('mic', indata.copy()))
                rms = np.sqrt(np.mean(indata ** 2))
                self.level_changed.emit(min(1.0, rms * 10))

            def system_callback(indata, frames, time_info, status):
                if status:
                    pass
                self._audio_queue.put(('system', indata.copy()))

            try:
                if self._record_microphone:
                    try:
                        mic_stream = sd.InputStream(
                            channels=min(self._channels, 1),
                            samplerate=self._sample_rate,
                            callback=mic_callback,
                            device=self._mic_device_id,
                            blocksize=int(self._sample_rate * 0.1)
                        )
                        mic_stream.start()
                    except Exception as e:
                        print(f"Microphone capture not available: {e}")

                if self._record_system_audio:
                    try:
                        system_stream = sd.InputStream(
                            channels=self._channels,
                            samplerate=self._sample_rate,
                            callback=system_callback,
                            device=self._system_device_id,
                            blocksize=int(self._sample_rate * 0.1)
                        )
                        system_stream.start()
                    except Exception as e:
                        print(f"System audio capture not available: {e}")

                while self._running:
                    try:
                        source, data = self._audio_queue.get(timeout=0.5)
                        if source == 'mic':
                            mic_buffer.append(data)
                        elif source == 'system':
                            system_buffer.append(data)
                    except queue.Empty:
                        continue

            finally:
                if mic_stream:
                    try:
                        mic_stream.stop()
                        mic_stream.close()
                    except:
                        pass
                if system_stream:
                    try:
                        system_stream.stop()
                        system_stream.close()
                    except:
                        pass

            self._combine_and_save(mic_buffer, system_buffer)

        except Exception as e:
            print(f"Recording error: {e}")
            self._running = False
    
    def _combine_and_save(self, mic_buffer: List[np.ndarray], system_buffer: List[np.ndarray]):
        try:
            if len(mic_buffer) == 0 and len(system_buffer) == 0:
                return
            
            def concat_buffers(buffer_list):
                if len(buffer_list) == 0:
                    return None
                max_len = max(b.shape[0] for b in buffer_list)
                padded = []
                for b in buffer_list:
                    if b.shape[0] < max_len:
                        pad = np.zeros((max_len - b.shape[0], b.shape[1] if len(b.shape) > 1 else 1))
                        b = np.vstack([b, pad]) if len(b.shape) > 1 else np.hstack([b, pad.flatten()])
                    padded.append(b)
                return np.vstack(padded) if len(padded[0].shape) > 1 else np.hstack(padded)
            
            mic_data = concat_buffers(mic_buffer)
            system_data = concat_buffers(system_buffer)
            
            final_data = None
            
            if mic_data is not None and system_data is not None:
                min_len = min(mic_data.shape[0], system_data.shape[0])
                mic_data = mic_data[:min_len]
                system_data = system_data[:min_len]
                if len(mic_data.shape) == 1:
                    mic_data = mic_data.reshape(-1, 1)
                if len(system_data.shape) == 1:
                    system_data = system_data.reshape(-1, 1)
                if mic_data.shape[1] == 1:
                    mic_data = np.repeat(mic_data, 2, axis=1)
                if system_data.shape[1] == 1:
                    system_data = np.repeat(system_data, 2, axis=1)
                final_data = (mic_data * 0.5 + system_data * 0.5).astype(np.float32)
            elif mic_data is not None:
                final_data = mic_data
                if len(final_data.shape) == 1:
                    final_data = final_data.reshape(-1, 1)
                if final_data.shape[1] == 1:
                    final_data = np.repeat(final_data, 2, axis=1)
            elif system_data is not None:
                final_data = system_data
                if len(final_data.shape) == 1:
                    final_data = final_data.reshape(-1, 1)
                if final_data.shape[1] == 1:
                    final_data = np.repeat(final_data, 2, axis=1)
            
            if final_data is not None and len(final_data) > 0 and HAS_SOUNDDEVICE:
                temp_dir = tempfile.gettempdir()
                self._temp_file = os.path.join(temp_dir, f"audio_rec_{int(time.time())}.wav")
                sf.write(self._temp_file, final_data, self._sample_rate)
                
                with self._lock:
                    self._temp_file_saved = self._temp_file
                    
        except Exception as e:
            print(f"Audio save error: {e}")
    
    def stop_recording(self) -> Optional[str]:
        if not self._running:
            return None
        
        self._running = False
        if self._record_thread:
            self._record_thread.join(timeout=5)
        
        result = None
        with self._lock:
            if hasattr(self, '_temp_file_saved'):
                result = self._temp_file_saved
            elif self._temp_file and os.path.exists(self._temp_file):
                result = self._temp_file
        
        self.recording_stopped.emit(result or "")
        return result
    
    def is_running(self) -> bool:
        return self._running
