from PyQt5.QtWidgets import (QWidget, QPushButton, QLabel, QSlider, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QProgressBar, QDoubleSpinBox, QMessageBox, QStyle)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QFont
import cv2
import os
from core.video_encoder import VideoEditor
from core.gif_exporter import GIFExporter
import numpy as np


class VideoEditorWindow(QWidget):
    export_requested = pyqtSignal(str)
    
    def __init__(self, video_path: str):
        super().__init__()
        self._video_path = video_path
        self._editor = VideoEditor()
        self._gif_exporter = GIFExporter()
        self._duration = self._editor.get_video_duration(video_path)
        self._current_time = 0.0
        self._start_time = 0.0
        self._end_time = self._duration
        self._is_playing = False
        self._frame_cache = {}
        
        self._gif_exporter.export_progress.connect(self._on_gif_progress)
        self._gif_exporter.export_finished.connect(self._on_gif_finished)
        self._gif_exporter.export_error.connect(self._on_gif_error)
        
        self._init_ui()
        self._init_player()
    
    def _init_ui(self):
        self.setWindowTitle("视频剪辑 - 裁剪与导出")
        self.setMinimumSize(900, 650)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        self._preview_label = QLabel()
        self._preview_label.setMinimumSize(800, 450)
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet("""
            background-color: #1a1a1a;
            border: 2px solid #333;
            border-radius: 8px;
        """)
        main_layout.addWidget(self._preview_label)
        
        self._time_label = QLabel("0.0s / 0.0s")
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setStyleSheet("color: #888; font-size: 13px;")
        main_layout.addWidget(self._time_label)
        
        timeline_container = QWidget()
        timeline_layout = QVBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(6)
        
        self._timeline_slider = QSlider(Qt.Horizontal)
        self._timeline_slider.setRange(0, int(self._duration * 100))
        self._timeline_slider.setValue(0)
        self._timeline_slider.valueChanged.connect(self._on_timeline_changed)
        timeline_layout.addWidget(self._timeline_slider)
        
        range_widget = QWidget()
        range_layout = QHBoxLayout(range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        
        range_layout.addWidget(QLabel("起始:"))
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, self._duration)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.1)
        self._start_spin.setValue(0.0)
        self._start_spin.valueChanged.connect(self._on_start_changed)
        range_layout.addWidget(self._start_spin)
        
        range_layout.addSpacing(20)
        
        range_layout.addWidget(QLabel("结束:"))
        self._end_spin = QDoubleSpinBox()
        self._end_spin.setRange(0.0, self._duration)
        self._end_spin.setDecimals(2)
        self._end_spin.setSingleStep(0.1)
        self._end_spin.setValue(self._duration)
        self._end_spin.valueChanged.connect(self._on_end_changed)
        range_layout.addWidget(self._end_spin)
        
        range_layout.addStretch()
        
        duration_label = QLabel(f"导出时长: {(self._end_time - self._start_time):.2f}s")
        duration_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        self._duration_label = duration_label
        range_layout.addWidget(duration_label)
        
        timeline_layout.addWidget(range_widget)
        main_layout.addWidget(timeline_container)
        
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self._btn_play = QPushButton()
        self._btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._btn_play.setIconSize(QSize(24, 24))
        self._btn_play.setFixedSize(40, 40)
        self._btn_play.clicked.connect(self._toggle_play)
        control_layout.addWidget(self._btn_play)
        
        self._btn_backward = QPushButton("⏮ 5s")
        self._btn_backward.clicked.connect(lambda: self._seek(-5.0))
        control_layout.addWidget(self._btn_backward)
        
        self._btn_forward = QPushButton("5s ⏭")
        self._btn_forward.clicked.connect(lambda: self._seek(5.0))
        control_layout.addWidget(self._btn_forward)
        
        control_layout.addStretch()
        
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setVisible(False)
        control_layout.addWidget(self._progress_bar)
        
        main_layout.addWidget(control_widget)
        
        export_widget = QWidget()
        export_layout = QHBoxLayout(export_widget)
        export_layout.setContentsMargins(0, 0, 0, 0)
        
        self._btn_export_mp4 = QPushButton("导出 MP4 视频")
        self._btn_export_mp4.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1086e0; }
            QPushButton:disabled { background-color: #666; }
        """)
        self._btn_export_mp4.clicked.connect(self._export_mp4)
        export_layout.addWidget(self._btn_export_mp4)
        
        self._btn_export_gif = QPushButton("导出 GIF 动图")
        self._btn_export_gif.setStyleSheet("""
            QPushButton {
                background-color: #e8750a;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #f28a25; }
            QPushButton:disabled { background-color: #666; }
        """)
        self._btn_export_gif.clicked.connect(self._export_gif)
        export_layout.addWidget(self._btn_export_gif)
        
        export_layout.addStretch()
        
        self._btn_close = QPushButton("关闭")
        self._btn_close.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #555; }
        """)
        self._btn_close.clicked.connect(self.close)
        export_layout.addWidget(self._btn_close)
        
        main_layout.addWidget(export_widget)
        
        self._update_frame(0.0)
        self._update_time_label()
    
    def _init_player(self):
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._play_tick)
    
    def _toggle_play(self):
        if self._is_playing:
            self._stop_play()
        else:
            self._start_play()
    
    def _start_play(self):
        if self._current_time >= self._end_time:
            self._current_time = self._start_time
        self._is_playing = True
        self._btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self._play_timer.start(33)
    
    def _stop_play(self):
        self._is_playing = False
        self._btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._play_timer.stop()
    
    def _play_tick(self):
        self._current_time += 0.033
        if self._current_time >= self._end_time:
            self._current_time = self._start_time
        self._timeline_slider.blockSignals(True)
        self._timeline_slider.setValue(int(self._current_time * 100))
        self._timeline_slider.blockSignals(False)
        self._update_frame(self._current_time)
        self._update_time_label()
    
    def _seek(self, delta: float):
        new_time = max(self._start_time, min(self._end_time, self._current_time + delta))
        self._current_time = new_time
        self._timeline_slider.blockSignals(True)
        self._timeline_slider.setValue(int(new_time * 100))
        self._timeline_slider.blockSignals(False)
        self._update_frame(new_time)
        self._update_time_label()
    
    def _on_timeline_changed(self, value: int):
        self._current_time = value / 100.0
        self._update_frame(self._current_time)
        self._update_time_label()
    
    def _on_start_changed(self, value: float):
        if value >= self._end_time:
            self._start_spin.setValue(self._end_time - 0.1)
            return
        self._start_time = value
        if self._current_time < self._start_time:
            self._current_time = self._start_time
            self._timeline_slider.blockSignals(True)
            self._timeline_slider.setValue(int(self._current_time * 100))
            self._timeline_slider.blockSignals(False)
        self._update_duration_label()
    
    def _on_end_changed(self, value: float):
        if value <= self._start_time:
            self._end_spin.setValue(self._start_time + 0.1)
            return
        self._end_time = value
        if self._current_time > self._end_time:
            self._current_time = self._end_time
            self._timeline_slider.blockSignals(True)
            self._timeline_slider.setValue(int(self._current_time * 100))
            self._timeline_slider.blockSignals(False)
        self._update_duration_label()
    
    def _update_time_label(self):
        self._time_label.setText(f"{self._current_time:.2f}s / {self._duration:.2f}s")
    
    def _update_duration_label(self):
        self._duration_label.setText(f"导出时长: {(self._end_time - self._start_time):.2f}s")
    
    def _update_frame(self, timestamp: float):
        cache_key = int(timestamp * 10)
        if cache_key in self._frame_cache:
            self._show_frame(self._frame_cache[cache_key])
            return
        
        frame = self._editor.get_video_frame(self._video_path, timestamp)
        if frame is not None:
            qimg = self._numpy_to_qimage(frame)
            pixmap = QPixmap.fromImage(qimg)
            self._frame_cache[cache_key] = pixmap
            if len(self._frame_cache) > 50:
                oldest = min(self._frame_cache.keys())
                del self._frame_cache[oldest]
            self._show_frame(pixmap)
    
    def _show_frame(self, pixmap: QPixmap):
        label_size = self._preview_label.size()
        scaled = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._preview_label.setPixmap(scaled)
    
    def _numpy_to_qimage(self, frame: np.ndarray) -> QImage:
        if len(frame.shape) == 2:
            h, w = frame.shape
            return QImage(frame.data, w, h, w, QImage.Format_Grayscale8).copy()
        elif frame.shape[2] == 3:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        return QImage()
    
    def _export_mp4(self):
        if self._end_time - self._start_time < 0.1:
            QMessageBox.warning(self, "提示", "导出时长过短")
            return
        
        default_name = f"video_clip_{int(self._start_time)}s_{int(self._end_time)}s.mp4"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "导出视频", default_name, "MP4 视频 (*.mp4)"
        )
        if not output_path:
            return
        
        self._set_buttons_enabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        
        import threading
        def do_export():
            result = self._editor.trim_video(self._video_path, output_path, self._start_time, self._end_time)
            QTimer.singleShot(0, lambda: self._on_export_done(result, output_path))
        
        threading.Thread(target=do_export, daemon=True).start()
    
    def _on_export_done(self, success: bool, path: str):
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        if success:
            QMessageBox.information(self, "完成", f"视频已导出:\n{path}")
            self.export_requested.emit(path)
        else:
            QMessageBox.critical(self, "错误", "导出失败")
    
    def _export_gif(self):
        if self._end_time - self._start_time < 0.1:
            QMessageBox.warning(self, "提示", "导出时长过短")
            return
        
        default_name = f"animation_{int(self._start_time)}s_{int(self._end_time)}s.gif"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "导出 GIF", default_name, "GIF 动图 (*.gif)"
        )
        if not output_path:
            return
        
        self._set_buttons_enabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        
        self._gif_exporter.export_from_video(
            self._video_path, output_path, fps=15, max_width=800,
            start_time=self._start_time, end_time=self._end_time
        )
    
    def _on_gif_progress(self, progress: int):
        self._progress_bar.setValue(progress)
    
    def _on_gif_finished(self, path: str):
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        QMessageBox.information(self, "完成", f"GIF 已导出:\n{path}")
        self.export_requested.emit(path)
    
    def _on_gif_error(self, error: str):
        self._progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        QMessageBox.critical(self, "错误", f"导出失败: {error}")
    
    def _set_buttons_enabled(self, enabled: bool):
        self._btn_export_mp4.setEnabled(enabled)
        self._btn_export_gif.setEnabled(enabled)
    
    def closeEvent(self, event):
        self._stop_play()
        super().closeEvent(event)
