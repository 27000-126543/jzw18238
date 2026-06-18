import cv2
import numpy as np
import imageio
import os
import threading
from typing import Optional, List
from PyQt5.QtCore import QObject, pyqtSignal


class GIFExporter(QObject):
    export_started = pyqtSignal()
    export_progress = pyqtSignal(int)
    export_finished = pyqtSignal(str)
    export_error = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._running = False
    
    def export_from_video(self, video_path: str, output_path: str, fps: int = 15, max_width: int = 800, start_time: float = 0.0, end_time: float = -1.0, scale: float = 1.0) -> bool:
        if self._running:
            return False
        
        self._running = True
        self.export_started.emit()
        
        thread = threading.Thread(
            target=self._export_thread,
            args=(video_path, output_path, fps, max_width, start_time, end_time, scale),
            daemon=True
        )
        thread.start()
        return True
    
    def _export_thread(self, video_path: str, output_path: str, fps: int, max_width: int, start_time: float, end_time: float, scale: float):
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise Exception("无法打开视频文件")
            
            video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / video_fps if video_fps > 0 else 0
            
            if end_time <= 0 or end_time > duration:
                end_time = duration
            
            start_frame = int(start_time * video_fps)
            end_frame = int(end_time * video_fps)
            
            frame_interval = max(1, int(video_fps / fps))
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            target_width = min(max_width, int(original_width * scale))
            target_height = int(original_height * (target_width / original_width))
            
            frames: List[np.ndarray] = []
            frame_idx = start_frame
            processed = 0
            total_to_process = (end_frame - start_frame) // frame_interval + 1
            
            while frame_idx < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if (frame_idx - start_frame) % frame_interval == 0:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    if target_width != original_width or target_height != original_height:
                        frame_rgb = cv2.resize(frame_rgb, (target_width, target_height))
                    frames.append(frame_rgb)
                    processed += 1
                    progress = int((processed / total_to_process) * 100)
                    self.export_progress.emit(min(100, progress))
                
                frame_idx += 1
            
            cap.release()
            
            if len(frames) == 0:
                raise Exception("没有有效的帧")
            
            duration_per_frame = 1.0 / fps
            
            imageio.mimsave(output_path, frames, duration=duration_per_frame, loop=0)
            
            self._running = False
            self.export_finished.emit(output_path)
            
        except Exception as e:
            self._running = False
            self.export_error.emit(str(e))
    
    def export_from_frames(self, frames: List[np.ndarray], output_path: str, fps: int = 15) -> bool:
        if self._running or len(frames) == 0:
            return False
        
        self._running = True
        self.export_started.emit()
        
        thread = threading.Thread(
            target=self._export_frames_thread,
            args=(frames, output_path, fps),
            daemon=True
        )
        thread.start()
        return True
    
    def _export_frames_thread(self, frames: List[np.ndarray], output_path: str, fps: int):
        try:
            processed_frames = []
            for i, frame in enumerate(frames):
                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                else:
                    frame_rgb = frame
                processed_frames.append(frame_rgb)
                progress = int((i + 1) / len(frames) * 100)
                self.export_progress.emit(min(100, progress))
            
            duration_per_frame = 1.0 / fps
            imageio.mimsave(output_path, processed_frames, duration=duration_per_frame, loop=0)
            
            self._running = False
            self.export_finished.emit(output_path)
            
        except Exception as e:
            self._running = False
            self.export_error.emit(str(e))
    
    def is_running(self) -> bool:
        return self._running
    
    def cancel(self):
        self._running = False
