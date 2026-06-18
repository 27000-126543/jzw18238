import json
import os
import time
from typing import List, Dict, Any, Optional
from PyQt5.QtCore import QObject, pyqtSignal


class HistoryItemType:
    VIDEO = "video"
    GIF = "gif"
    SCREENSHOT = "screenshot"


class HistoryManager(QObject):
    history_updated = pyqtSignal()

    def __init__(self, data_dir: Optional[str] = None):
        super().__init__()
        if data_dir is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".screen_recorder_history")
        self._data_dir = data_dir
        self._history_file = os.path.join(data_dir, "history.json")
        self._items: List[Dict[str, Any]] = []
        self._max_items = 50
        self._load()

    def _load(self):
        if not os.path.exists(self._history_file):
            self._items = []
            return
        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._items = data.get("items", [])
        except Exception:
            self._items = []

    def _save(self):
        try:
            os.makedirs(self._data_dir, exist_ok=True)
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump({"items": self._items}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Save history error: {e}")

    def add_item(self, item_type: str, path: str, title: str = "", duration: float = 0.0,
                 resolution: str = "", size_bytes: int = 0):
        item = {
            "type": item_type,
            "path": path,
            "title": title or os.path.basename(path),
            "timestamp": time.time(),
            "duration": duration,
            "resolution": resolution,
            "size_bytes": size_bytes,
        }
        self._items.insert(0, item)
        if len(self._items) > self._max_items:
            self._items = self._items[:self._max_items]
        self._save()
        self.history_updated.emit()

    def remove_item(self, path: str):
        self._items = [it for it in self._items if it["path"] != path]
        self._save()
        self.history_updated.emit()

    def get_items(self, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if item_type is None:
            return list(self._items)
        return [it for it in self._items if it["type"] == item_type]

    def clear(self):
        self._items = []
        self._save()
        self.history_updated.emit()

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def format_timestamp(ts: float) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
