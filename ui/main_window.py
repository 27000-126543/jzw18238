from PyQt5.QtWidgets import (QMainWindow, QWidget, QPushButton, QLabel, QComboBox, QSpinBox, QCheckBox, QVBoxLayout, QHBoxLayout, QGroupBox, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QAction, QStyle, QSizePolicy, QProgressBar, QApplication, QFrame)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal, QSize, QThread
from PyQt5.QtGui import QIcon, QPixmap, QImage, QPainter, QColor, QFont, QGuiApplication
import sys
import os
import time
import threading
import numpy as np
from typing import Optional, Tuple

from core.screen_capture import ScreenCapture, CaptureMode
from core.audio_recorder import AudioRecorder
from core.video_encoder import VideoEncoder
from core.annotation_engine import AnnotationEngine
from core.gif_exporter import GIFExporter

from ui.annotation_overlay import AnnotationOverlay
from ui.region_selector import RegionSelector
from ui.video_editor import VideoEditorWindow
from ui.screenshot_editor import ScreenshotEditor


class CaptureThread(QThread):
    frame_ready = pyqtSignal(np.ndarray)
    stopped = pyqtSignal()

    def __init__(self, screen_capture: ScreenCapture, annotation_engine: AnnotationEngine, video_encoder: VideoEncoder):
        super().__init__()
        self._screen_capture = screen_capture
        self._annotation_engine = annotation_engine
        self._video_encoder = video_encoder
        self._running = False
        self._frame_interval = 1.0 / 30.0

    def set_fps(self, fps: int):
        self._frame_interval = 1.0 / max(1, fps)

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        last_time = time.time()

        while self._running:
            try:
                current_time = time.time()
                elapsed = current_time - last_time

                if elapsed >= self._frame_interval:
                    frame = self._screen_capture.capture_frame()
                    if frame is not None:
                        annotated = self._annotation_engine.render_on_frame(frame)
                        self.frame_ready.emit(annotated)
                        self._video_encoder.add_frame(annotated)
                    last_time = current_time
                else:
                    time.sleep(max(0, self._frame_interval - elapsed))
            except Exception as e:
                print(f"Capture thread error: {e}")
                time.sleep(0.001)

        self.stopped.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕录制与标注工具")
        self.setMinimumSize(650, 600)

        self._screen_capture = ScreenCapture()
        self._audio_recorder = AudioRecorder()
        self._video_encoder = VideoEncoder()
        self._annotation_engine = AnnotationEngine()
        self._gif_exporter = GIFExporter()

        self._capture_thread: Optional[CaptureThread] = None
        self._is_recording = False
        self._is_paused = False
        self._record_start_time = 0.0
        self._elapsed_time = 0.0
        self._paused_duration = 0.0
        self._last_pause_start = 0.0

        self._annotation_overlay: Optional[AnnotationOverlay] = None
        self._region_selector: Optional[RegionSelector] = None
        self._video_editor: Optional[VideoEditorWindow] = None
        self._screenshot_editor: Optional[ScreenshotEditor] = None
        self._selected_region: Optional[Tuple[int, int, int, int]] = None
        self._selected_window: Optional[str] = None
        self._output_dir = os.path.expanduser("~/Videos")

        self._audio_level = 0.0
        self._init_ui()
        self._init_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_ui)
        self._timer.start(100)

        self._audio_recorder.level_changed.connect(self._on_audio_level)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title = QLabel("🎬 屏幕录制与实时标注工具")
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #0078d4;
            padding-bottom: 8px;
            border-bottom: 2px solid #e0e0e0;
            margin-bottom: 8px;
        """)
        main_layout.addWidget(title)

        mode_group = QGroupBox("录制模式")
        mode_group.setStyleSheet(self._group_style())
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(10)

        mode_row1 = QHBoxLayout()

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("全屏录制", CaptureMode.FULLSCREEN.value)
        self._mode_combo.addItem("指定窗口", CaptureMode.WINDOW.value)
        self._mode_combo.addItem("自定义区域", CaptureMode.REGION.value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row1.addWidget(QLabel("模式:"))
        mode_row1.addWidget(self._mode_combo, 1)

        mode_layout.addLayout(mode_row1)

        window_row = QHBoxLayout()
        self._window_combo = QComboBox()
        self._window_combo.addItem("(请先刷新窗口列表)", "")
        self._refresh_windows_btn = QPushButton("刷新")
        self._refresh_windows_btn.clicked.connect(self._refresh_window_list)
        self._window_combo.setEnabled(False)
        self._refresh_windows_btn.setEnabled(False)
        window_row.addWidget(QLabel("目标窗口:"))
        window_row.addWidget(self._window_combo, 1)
        window_row.addWidget(self._refresh_windows_btn)

        self._select_region_btn = QPushButton("选择区域")
        self._select_region_btn.clicked.connect(self._select_region)
        self._select_region_btn.setEnabled(False)

        mode_layout.addLayout(window_row)
        mode_layout.addWidget(self._select_region_btn)

        main_layout.addWidget(mode_group)

        audio_group = QGroupBox("音频设置")
        audio_group.setStyleSheet(self._group_style())
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setSpacing(8)

        audio_row1 = QHBoxLayout()
        self._cb_system_audio = QCheckBox("录制系统声音")
        self._cb_system_audio.setChecked(True)
        self._cb_microphone = QCheckBox("录制麦克风")
        self._cb_microphone.setChecked(True)
        audio_row1.addWidget(self._cb_system_audio)
        audio_row1.addWidget(self._cb_microphone)
        audio_row1.addStretch()

        self._audio_level_bar = QProgressBar()
        self._audio_level_bar.setRange(0, 100)
        self._audio_level_bar.setValue(0)
        self._audio_level_bar.setFixedWidth(150)
        self._audio_level_bar.setTextVisible(False)
        self._audio_level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                background: #f0f0f0;
                height: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop: 0 #00cc00, stop: 0.7 #ffcc00, stop: 1 #ff3333);
                border-radius: 3px;
            }
        """)
        audio_row1.addWidget(QLabel("音量:"))
        audio_row1.addWidget(self._audio_level_bar)

        audio_layout.addLayout(audio_row1)

        mic_row = QHBoxLayout()
        self._mic_combo = QComboBox()
        self._mic_combo.addItem("默认麦克风", -1)
        for dev in AudioRecorder.get_input_devices():
            self._mic_combo.addItem(f"{dev['name']} (输入)", dev['id'])
        mic_row.addWidget(QLabel("麦克风:"))
        mic_row.addWidget(self._mic_combo, 1)
        audio_layout.addLayout(mic_row)

        main_layout.addWidget(audio_group)

        quality_group = QGroupBox("画质设置")
        quality_group.setStyleSheet(self._group_style())
        quality_layout = QHBoxLayout(quality_group)
        quality_layout.setSpacing(10)

        quality_layout.addWidget(QLabel("分辨率:"))
        self._resolution_combo = QComboBox()
        self._resolution_combo.addItem("原始分辨率 (原始大小)", -1)
        self._resolution_combo.addItem("1920x1080 (Full HD)", 1080)
        self._resolution_combo.addItem("1280x720 (HD)", 720)
        self._resolution_combo.addItem("854x480 (SD)", 480)
        quality_layout.addWidget(self._resolution_combo, 1)

        quality_layout.addWidget(QLabel("帧率:"))
        self._fps_combo = QComboBox()
        for f in [15, 24, 30, 60]:
            self._fps_combo.addItem(f"{f} FPS", f)
        self._fps_combo.setCurrentIndex(2)
        quality_layout.addWidget(self._fps_combo)

        main_layout.addWidget(quality_group)

        action_group = QGroupBox("录制控制")
        action_group.setStyleSheet(self._group_style())
        action_layout = QVBoxLayout(action_group)
        action_layout.setSpacing(10)

        control_row = QHBoxLayout()
        self._btn_record = QPushButton("● 开始录制")
        self._btn_record.setStyleSheet(self._record_button_style(True))
        self._btn_record.setMinimumHeight(50)
        self._btn_record.clicked.connect(self._toggle_recording)

        self._btn_pause = QPushButton("⏸ 暂停")
        self._btn_pause.setEnabled(False)
        self._btn_pause.setMinimumHeight(50)
        self._btn_pause.clicked.connect(self._toggle_pause)

        self._btn_annotate = QPushButton("✏ 标注 (F8)")
        self._btn_annotate.setMinimumHeight(50)
        self._btn_annotate.clicked.connect(self._toggle_annotation)

        self._btn_screenshot = QPushButton("📷 截图")
        self._btn_screenshot.setMinimumHeight(50)
        self._btn_screenshot.clicked.connect(self._take_screenshot)

        control_row.addWidget(self._btn_record)
        control_row.addWidget(self._btn_pause)
        control_row.addWidget(self._btn_annotate)
        control_row.addWidget(self._btn_screenshot)
        action_layout.addLayout(control_row)

        info_row = QHBoxLayout()
        self._time_label = QLabel("00:00:00")
        self._time_label.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
            font-family: Consolas, monospace;
            color: #333;
            background: #f5f5f5;
            padding: 8px 20px;
            border-radius: 6px;
            border: 1px solid #ddd;
        """)
        self._time_label.setAlignment(Qt.AlignCenter)
        info_row.addWidget(self._time_label, 1)

        self._status_label = QLabel("准备就绪")
        self._status_label.setStyleSheet("color: #666; font-size: 12px;")
        info_row.addWidget(self._status_label)
        action_layout.addLayout(info_row)

        main_layout.addWidget(action_group)

        output_row = QHBoxLayout()
        self._output_label = QLabel(f"输出目录: " + self._output_dir)
        self._output_label.setStyleSheet("color: #666;")
        self._browse_btn = QPushButton("浏览...")
        self._browse_btn.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self._output_label, 1)
        output_row.addWidget(self._browse_btn)
        main_layout.addLayout(output_row)

        main_layout.addStretch()

        hint = QLabel("快捷键: F8 标注 | F9 录制/暂停 | F10 停止")
        hint.setStyleSheet("color: #999; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(hint)

    def _group_style(self) -> str:
        return """
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #ddd;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel { font-size: 12px; }
            QComboBox, QPushButton, QSpinBox {
                padding: 6px 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background: white;
                min-height: 24px;
            }
            QComboBox:hover, QPushButton:hover { border-color: #0078d4; }
            QCheckBox { spacing: 8px; }
        """

    def _record_button_style(self, is_start: bool) -> str:
        if is_start:
            return """
                QPushButton {
                    background-color: #e81123;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 15px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #cc0f1f; }
                QPushButton:disabled { background-color: #888; }
            """
        else:
            return """
                QPushButton {
                    background-color: #107c10;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 15px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #0e6b0e; }
            """

    def _init_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            icon = self.style().standardIcon(QStyle.SP_MediaPlay)
            self._tray.setIcon(icon)

            tray_menu = QMenu()
            record_action = QAction("开始/停止录制", self)
            record_action.triggered.connect(self._toggle_recording)
            tray_menu.addAction(record_action)

            annotate_action = QAction("标注", self)
            annotate_action.triggered.connect(self._toggle_annotation)
            tray_menu.addAction(annotate_action)

            show_action = QAction("显示主窗口", self)
            show_action.triggered.connect(self.showNormal)
            tray_menu.addAction(show_action)

            self._tray.setContextMenu(tray_menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()

    def _on_mode_changed(self, index: int):
        mode_value = self._mode_combo.currentData()
        is_window = (mode_value == CaptureMode.WINDOW.value)
        is_region = (mode_value == CaptureMode.REGION.value)

        self._window_combo.setEnabled(is_window)
        self._refresh_windows_btn.setEnabled(is_window)
        self._select_region_btn.setEnabled(is_region)

    def _refresh_window_list(self):
        self._window_combo.clear()
        windows = self._screen_capture.get_available_windows()
        for hwnd, title in windows:
            short_title = title if len(title) <= 50 else title[:47] + "..."
            self._window_combo.addItem(short_title, title)
        if len(windows) == 0:
            self._window_combo.addItem("无可用窗口", "")

    def _select_region(self):
        self.hide()
        if not self._region_selector:
            self._region_selector = RegionSelector()
            self._region_selector.region_selected.connect(self._on_region_selected)
            self._region_selector.selection_cancelled.connect(self._on_region_cancelled)
        self._region_selector.show_selector()

    def _on_region_selected(self, x, y, w, h):
        self._selected_region = (x, y, w, h)
        self._screen_capture.set_region(self._selected_region)
        self.show()
        self._status_label.setText(f"已选择区域: {w}x{h}")

    def _on_region_cancelled(self):
        self.show()

    def _choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self._output_dir)
        if d:
            self._output_dir = d
            self._output_label.setText("输出目录: " + d)

    def _on_audio_level(self, level: float):
        self._audio_level = level

    def _toggle_recording(self):
        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        mode_value = self._mode_combo.currentData()
        mode = CaptureMode(mode_value)
        self._screen_capture.set_mode(mode)

        if mode == CaptureMode.WINDOW:
            window_title = self._window_combo.currentData()
            if not window_title:
                QMessageBox.warning(self, "提示", "请选择一个目标窗口")
                return
            self._screen_capture.set_target_window(window_title)
        elif mode == CaptureMode.REGION and not self._selected_region:
            QMessageBox.warning(self, "提示", "请先选择录制区域")
            return

        fps = self._fps_combo.currentData()
        self._screen_capture.set_fps(fps)
        self._video_encoder.set_fps(fps)

        res = self._resolution_combo.currentData()
        orig_w, orig_h = self._screen_capture.get_current_resolution()
        if res == -1:
            self._video_encoder.set_resolution(orig_w, orig_h)
        else:
            ratio = orig_h / res
            target_h = res
            target_w = int(orig_w / ratio)
            self._video_encoder.set_resolution(target_w, target_h)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(self._output_dir, f"recording_{timestamp}.mp4")

        if not self._video_encoder.start_recording(output_path):
            QMessageBox.critical(self, "错误", "无法启动录制")
            return

        self._audio_recorder.set_record_system_audio(self._cb_system_audio.isChecked())
        self._audio_recorder.set_record_microphone(self._cb_microphone.isChecked())
        mic_id = self._mic_combo.currentData()
        if mic_id != -1:
            self._audio_recorder.set_microphone_device(mic_id)

        self._audio_recorder.start_recording()

        self._capture_thread = CaptureThread(self._screen_capture, self._annotation_engine, self._video_encoder)
        self._capture_thread.set_fps(fps)
        self._capture_thread.frame_ready.connect(self._on_frame)
        self._capture_thread.stopped.connect(self._on_capture_stopped)
        self._capture_thread.start()

        self._is_recording = True
        self._is_paused = False
        self._record_start_time = time.time()
        self._paused_duration = 0.0

        self._btn_record.setText("■ 停止录制")
        self._btn_record.setStyleSheet(self._record_button_style(False))
        self._btn_pause.setEnabled(True)
        self._status_label.setText("录制中...")
        self._mode_combo.setEnabled(False)
        self._window_combo.setEnabled(False)
        self._select_region_btn.setEnabled(False)
        self._refresh_windows_btn.setEnabled(False)

    def _stop_recording(self):
        self._is_recording = False
        self._btn_record.setEnabled(False)
        self._status_label.setText("正在保存...")

        if self._capture_thread:
            self._capture_thread.stop()

    def _on_frame(self, frame):
        pass

    def _on_capture_stopped(self):
        audio_path = self._audio_recorder.stop_recording()

        final_path = self._video_encoder.stop_recording(audio_path)

        self._btn_record.setEnabled(True)
        self._btn_record.setText("● 开始录制")
        self._btn_record.setStyleSheet(self._record_button_style(True))
        self._btn_pause.setEnabled(False)
        self._btn_pause.setText("⏸ 暂停")
        self._mode_combo.setEnabled(True)
        self._on_mode_changed(self._mode_combo.currentIndex())

        if self._annotation_overlay:
            self._annotation_overlay.hide_overlay()
            self._annotation_overlay = None

        if final_path and os.path.exists(final_path):
            self._status_label.setText(f"已保存: {os.path.basename(final_path)}")
            reply = QMessageBox.question(self, "录制完成",
                                       f"视频已保存到:\n{final_path}\n\n是否进入剪辑界面?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._open_video_editor(final_path)
        else:
            self._status_label.setText("录制已取消")

    def _toggle_pause(self):
        if not self._is_recording:
            return
        self._is_paused = not self._is_paused
        if self._is_paused:
            if self._capture_thread:
                self._capture_thread.stop()
                self._capture_thread.wait()
                self._capture_thread = None
            self._last_pause_start = time.time()
            self._btn_pause.setText("▶ 继续")
            self._status_label.setText("已暂停")
        else:
            fps = self._fps_combo.currentData()
            self._capture_thread = CaptureThread(self._screen_capture, self._annotation_engine, self._video_encoder)
            self._capture_thread.set_fps(fps)
            self._capture_thread.frame_ready.connect(self._on_frame)
            self._capture_thread.stopped.connect(self._on_capture_stopped)
            self._capture_thread.start()
            self._paused_duration += time.time() - self._last_pause_start
            self._btn_pause.setText("⏸ 暂停")
            self._status_label.setText("录制中...")

    def _toggle_annotation(self):
        if self._annotation_overlay and self._annotation_overlay.isVisible():
            self._annotation_overlay.hide_overlay()
            self._annotation_overlay = None
            self._annotation_engine.set_active(False)
            self._btn_annotate.setText("✏ 标注 (F8)")
        else:
            if self._annotation_overlay is None:
                self._annotation_overlay = AnnotationOverlay(self._annotation_engine)
            self._annotation_engine.set_active(True)
            self._annotation_overlay.show_overlay()
            self._btn_annotate.setText("✏ 关闭标注")

    def _take_screenshot(self):
        self.hide()
        QTimer.singleShot(300, self._do_screenshot_delayed)

    def _do_screenshot_delayed(self):
        try:
            frame = self._screen_capture.capture_frame()
            self.show()
            if frame is not None:
                from PyQt5.QtGui import QImage as _QImage
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qimg = _QImage(frame.data, w, h, bytes_per_line, _QImage.Format_RGB888).rgbSwapped()
                pixmap = QPixmap.fromImage(qimg)

                self._screenshot_editor = ScreenshotEditor(pixmap)
                self._screenshot_editor.show()
        except Exception as e:
            self.show()
            QMessageBox.critical(self, "错误", f"截图失败: {e}")

    def _open_video_editor(self, video_path: str):
        self._video_editor = VideoEditorWindow(video_path)
        self._video_editor.show()

    def _update_ui(self):
        if self._is_recording and not self._is_paused:
            elapsed = time.time() - self._record_start_time - self._paused_duration
        elif self._is_recording and self._is_paused:
            elapsed = self._last_pause_start - self._record_start_time - self._paused_duration
        else:
            elapsed = 0
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        self._time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

        self._audio_level_bar.setValue(int(self._audio_level * 100))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F8:
            self._toggle_annotation()
        elif event.key() == Qt.Key_F9:
            self._toggle_recording()
        elif event.key() == Qt.Key_F10:
            if self._is_recording:
                self._stop_recording()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._is_recording:
            reply = QMessageBox.question(self, "确认", "正在录制，确定退出?",
                                     QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return

        if self._annotation_overlay:
            self._annotation_overlay.close()
        if self._capture_thread:
            self._capture_thread.stop()
            self._capture_thread.wait()
        if hasattr(self, '_tray'):
            self._tray.hide()
        event.accept()
