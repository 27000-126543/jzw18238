import mss
import mss.tools
import numpy as np
from enum import Enum
from typing import Optional, Tuple
from PyQt5.QtCore import QObject, pyqtSignal
import time

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import pygetwindow as gw
    HAS_PYWIN = True
except ImportError:
    HAS_PYWIN = False


class CaptureMode(Enum):
    FULLSCREEN = "fullscreen"
    WINDOW = "window"
    REGION = "region"


class ScreenCapture(QObject):
    frame_captured = pyqtSignal(np.ndarray)
    
    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        self.mode = CaptureMode.FULLSCREEN
        self.target_window: Optional[str] = None
        self.region: Optional[Tuple[int, int, int, int]] = None
        self._running = False
        self.fps = 30
        self.monitor_index = 0
    
    def set_mode(self, mode: CaptureMode):
        self.mode = mode
    
    def set_target_window(self, window_title: str):
        self.target_window = window_title
    
    def set_region(self, region: Tuple[int, int, int, int]):
        self.region = region
    
    def set_fps(self, fps: int):
        self.fps = max(1, min(fps, 120))
    
    def set_monitor(self, monitor_index: int):
        self.monitor_index = max(0, monitor_index)
    
    def get_available_windows(self) -> list:
        windows = []
        if not HAS_WIN32:
            return windows
        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and len(title.strip()) > 0:
                    windows.append((hwnd, title))
            return True
        win32gui.EnumWindows(enum_callback, None)
        return windows
    
    def get_window_rect(self, hwnd) -> Optional[Tuple[int, int, int, int]]:
        if not HAS_WIN32:
            return None
        try:
            rect = win32gui.GetWindowRect(hwnd)
            return rect
        except:
            return None
    
    def _get_capture_region(self) -> dict:
        if self.mode == CaptureMode.FULLSCREEN:
            return self.sct.monitors[self.monitor_index]
        elif self.mode == CaptureMode.WINDOW:
            if self.target_window and HAS_WIN32:
                try:
                    hwnd = win32gui.FindWindow(None, self.target_window)
                    if hwnd:
                        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                        width = right - left
                        height = bottom - top
                        return {"top": top, "left": left, "width": width, "height": height}
                except:
                    pass
            return self.sct.monitors[self.monitor_index]
        elif self.mode == CaptureMode.REGION and self.region:
            x, y, w, h = self.region
            return {"top": y, "left": x, "width": w, "height": h}
        return self.sct.monitors[self.monitor_index]
    
    def capture_frame(self) -> Optional[np.ndarray]:
        try:
            region = self._get_capture_region()
            raw = self.sct.grab(region)
            frame = np.array(raw)
            frame = frame[:, :, :3].copy()
            return frame
        except Exception as e:
            print(f"Capture error: {e}")
            return None
    
    def get_monitors_info(self) -> list:
        return self.sct.monitors
    
    def get_current_resolution(self) -> Tuple[int, int]:
        region = self._get_capture_region()
        return (region["width"], region["height"])
    
    def stop(self):
        self._running = False
        self.sct.close()
