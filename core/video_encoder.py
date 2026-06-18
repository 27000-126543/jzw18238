import cv2
import numpy as np
import threading
import queue
import time
import os
import tempfile
import subprocess
import sys
from typing import Optional, Tuple
from PyQt5.QtCore import QObject, pyqtSignal
import imageio


class VideoEncoder(QObject):
    encoding_started = pyqtSignal()
    encoding_progress = pyqtSignal(int)
    encoding_finished = pyqtSignal(str)
    encoding_error = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._frame_queue: Optional[queue.Queue] = None
        self._writer: Optional[cv2.VideoWriter] = None
        self._encoding = False
        self._encode_thread: Optional[threading.Thread] = None
        self._fps = 30
        self._resolution: Tuple[int, int] = (1920, 1080)
        self._output_path: Optional[str] = None
        self._temp_path: Optional[str] = None
        self._frame_count = 0
        self._codec = 'mp4v'
    
    def set_fps(self, fps: int):
        self._fps = max(1, min(fps, 120))
    
    def set_resolution(self, width: int, height: int):
        self._resolution = (max(1, width), max(1, height))
    
    def set_codec(self, codec: str):
        self._codec = codec
    
    def start_recording(self, output_path: Optional[str] = None) -> bool:
        if self._encoding:
            return False
        
        try:
            if output_path:
                self._output_path = output_path
            else:
                temp_dir = tempfile.gettempdir()
                self._output_path = os.path.join(temp_dir, f"video_{int(time.time())}.mp4")
            
            self._temp_path = self._output_path + ".temp.mp4"
            self._frame_queue = queue.Queue(maxsize=1000)
            self._frame_count = 0
            
            fourcc = cv2.VideoWriter_fourcc(*self._codec)
            self._writer = cv2.VideoWriter(self._temp_path, fourcc, self._fps, self._resolution)
            
            if not self._writer.isOpened():
                raise Exception("Failed to open video writer")
            
            self._encoding = True
            self._encode_thread = threading.Thread(target=self._encode_loop, daemon=True)
            self._encode_thread.start()
            self.encoding_started.emit()
            
            return True
        except Exception as e:
            self.encoding_error.emit(str(e))
            return False
    
    def _encode_loop(self):
        try:
            while self._encoding or not self._frame_queue.empty():
                try:
                    frame = self._frame_queue.get(timeout=1.0)
                    if frame is None:
                        break
                    
                    if frame.shape[1] != self._resolution[0] or frame.shape[0] != self._resolution[1]:
                        frame = cv2.resize(frame, self._resolution)
                    
                    if len(frame.shape) == 2:
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    
                    self._writer.write(frame)
                    self._frame_count += 1
                    
                    if self._frame_count % 30 == 0:
                        self.encoding_progress.emit(self._frame_count)
                        
                except queue.Empty:
                    continue
                    
        except Exception as e:
            self.encoding_error.emit(str(e))
        finally:
            if self._writer:
                self._writer.release()
            
            try:
                if os.path.exists(self._temp_path) and self._frame_count > 0:
                    if os.path.exists(self._output_path):
                        os.remove(self._output_path)
                    os.rename(self._temp_path, self._output_path)
            except Exception as e:
                print(f"File move error: {e}")
                if os.path.exists(self._temp_path):
                    self._output_path = self._temp_path
    
    def add_frame(self, frame: np.ndarray):
        if not self._encoding or self._frame_queue is None:
            return False
        try:
            self._frame_queue.put(frame.copy(), timeout=0.5)
            return True
        except queue.Full:
            return False
    
    def stop_recording(self, mux_audio_path: Optional[str] = None) -> Optional[str]:
        if not self._encoding:
            return self._output_path
        
        self._encoding = False
        
        if self._frame_queue is not None:
            self._frame_queue.put(None)
        
        if self._encode_thread:
            self._encode_thread.join(timeout=10)
        
        if mux_audio_path and os.path.exists(mux_audio_path) and self._output_path and os.path.exists(self._output_path):
            return self._mux_audio_video(mux_audio_path)
        
        self.encoding_finished.emit(self._output_path or "")
        return self._output_path
    
    def _mux_audio_video(self, audio_path: str) -> Optional[str]:
        try:
            final_path = self._output_path.replace('.mp4', '_with_audio.mp4')
            if os.path.exists(final_path):
                os.remove(final_path)
            
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except:
                ffmpeg_path = 'ffmpeg'
            
            cmd = [
                ffmpeg_path,
                '-y',
                '-i', self._output_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-shortest',
                final_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and os.path.exists(final_path):
                try:
                    os.remove(self._output_path)
                except:
                    pass
                self._output_path = final_path
            else:
                print(f"FFmpeg error: {result.stderr}")
        except Exception as e:
            print(f"Audio mux error: {e}")
        
        self.encoding_finished.emit(self._output_path or "")
        return self._output_path
    
    def is_encoding(self) -> bool:
        return self._encoding
    
    def get_frame_count(self) -> int:
        return self._frame_count
    
    def get_output_path(self) -> Optional[str]:
        return self._output_path


class VideoEditor:
    @staticmethod
    def trim_video(input_path: str, output_path: str, start_time: float, end_time: float) -> bool:
        try:
            try:
                import imageio_ffmpeg
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except:
                ffmpeg_path = 'ffmpeg'
            
            duration = end_time - start_time
            if duration <= 0:
                return False
            
            cmd = [
                ffmpeg_path,
                '-y',
                '-ss', str(start_time),
                '-i', input_path,
                '-t', str(duration),
                '-c', 'copy',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0 and os.path.exists(output_path)
        except Exception as e:
            print(f"Trim error: {e}")
            return False
    
    @staticmethod
    def get_video_duration(video_path: str) -> float:
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return 0.0
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            cap.release()
            return frame_count / fps if fps > 0 else 0.0
        except Exception as e:
            print(f"Duration error: {e}")
            return 0.0
    
    @staticmethod
    def get_video_frame(video_path: str, timestamp: float) -> Optional[np.ndarray]:
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            frame_num = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            cap.release()
            return frame if ret else None
        except Exception as e:
            print(f"Frame read error: {e}")
            return None
    
    @staticmethod
    def get_video_frames(video_path: str) -> int:
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return 0
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            return count
        except:
            return 0
    
    @staticmethod
    def get_video_fps(video_path: str) -> float:
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return 30.0
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            return fps or 30.0
        except:
            return 30.0
