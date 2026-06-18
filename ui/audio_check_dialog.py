import numpy as np
from PyQt5.QtWidgets import (QDialog, QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QImage, QFont
from typing import Optional, Dict, Any
from core.audio_analyzer import AudioAnalyzer


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._waveform = np.array([])
        self._color = QColor("#0078d4")
        self._bg_color = QColor("#1e1e1e")

    def set_waveform(self, waveform: np.ndarray, color: str = "#0078d4"):
        self._waveform = waveform
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, self._bg_color)

        if len(self._waveform) == 0:
            painter.setPen(QPen(QColor("#555"), 1, Qt.DashLine))
            painter.drawLine(0, h // 2, w, h // 2)
            return

        painter.setPen(QPen(self._color, 1))
        mid = h // 2
        n = len(self._waveform)
        max_val = np.max(self._waveform) if np.max(self._waveform) > 0.001 else 1.0

        for i in range(n):
            x = int(i * w / n)
            bar_h = int((self._waveform[i] / max_val) * (h // 2 - 2))
            painter.drawLine(x, mid - bar_h, x, mid + bar_h)

        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawLine(0, mid, w, mid)


class AudioCheckDialog(QDialog):
    rerecord_requested = pyqtSignal()

    def __init__(self, mic_data, mic_sr, sys_data, sys_sr, parent=None):
        super().__init__(parent)
        self.setWindowTitle("音频质量检查")
        self.setMinimumSize(640, 480)

        self._mic_analysis = AudioAnalyzer.analyze(mic_data, mic_sr)
        self._sys_analysis = AudioAnalyzer.analyze(sys_data, sys_sr)

        self._build_ui()
        self._populate_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("🎵 音频质量检查报告")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #333;")
        layout.addWidget(title)

        summary = QLabel()
        summary.setObjectName("summary_label")
        summary.setStyleSheet("padding: 12px; background: #f0f0f0; border-radius: 6px; color: #333;")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self._summary_label = summary

        layout.addSpacing(8)

        mic_panel = self._build_channel_panel("🎙 麦克风", self._mic_analysis, "#d4380d")
        layout.addWidget(mic_panel)

        sys_panel = self._build_channel_panel("🔊 系统声音", self._sys_analysis, "#0078d4")
        layout.addWidget(sys_panel)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        rerecord_btn = QPushButton("🔄 重新录制")
        rerecord_btn.setStyleSheet("""
            QPushButton { padding: 10px 24px; background: #d4380d; color: white; 
                          border: none; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #e55b2f; }
        """)
        rerecord_btn.clicked.connect(self._on_rerecord)
        btn_row.addWidget(rerecord_btn)

        ok_btn = QPushButton("✓ 确认")
        ok_btn.setStyleSheet("""
            QPushButton { padding: 10px 28px; background: #0078d4; color: white; 
                          border: none; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #1a86e0; }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def _build_channel_panel(self, title: str, analysis: Dict[str, Any], color: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { background: #f9f9f9; border: 1px solid #ddd; border-radius: 6px; }")

        panel_layout = QVBoxLayout(frame)
        panel_layout.setContentsMargins(14, 10, 14, 14)
        panel_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        title_row.addWidget(title_label)

        status_label = QLabel()
        status_label.setObjectName("status_label")
        status_text, status_type = AudioAnalyzer.status_label(analysis)
        status_label.setText(status_text)

        status_style = ""
        if status_type == "good":
            status_style = "color: #0a7c0a; background: #e6f7e6; padding: 3px 10px; border-radius: 10px; font-weight: bold;"
        elif status_type == "warning":
            status_style = "color: #b37400; background: #fff7e6; padding: 3px 10px; border-radius: 10px; font-weight: bold;"
        else:
            status_style = "color: #a31010; background: #fde8e8; padding: 3px 10px; border-radius: 10px; font-weight: bold;"
        status_label.setStyleSheet(status_style)
        title_row.addStretch()
        title_row.addWidget(status_label)
        panel_layout.addLayout(title_row)

        waveform = WaveformWidget()
        waveform.set_waveform(analysis.get("waveform", np.array([])), color)
        panel_layout.addWidget(waveform)

        info_row = QHBoxLayout()
        info_row.setSpacing(20)

        def stat(label, value, unit=""):
            w = QLabel(f"<b>{label}:</b> {value}{unit}")
            w.setStyleSheet("color: #555;")
            return w

        info_row.addWidget(stat("峰值", AudioAnalyzer.format_db(analysis.get("peak_db", -float("inf")))))
        info_row.addWidget(stat("平均响度", AudioAnalyzer.format_db(analysis.get("rms_db", -float("inf")))))
        silence_pct = analysis.get("silence_ratio", 1.0) * 100
        info_row.addWidget(stat("静音占比", f"{silence_pct:.1f}", "%"))
        info_row.addWidget(stat("时长", f"{analysis.get('duration', 0):.1f}", "s"))
        info_row.addStretch()
        panel_layout.addLayout(info_row)

        return frame

    def _populate_data(self):
        mic_has = self._mic_analysis["has_data"] and not self._mic_analysis["is_silent"]
        sys_has = self._sys_analysis["has_data"] and not self._sys_analysis["is_silent"]

        issues = []
        if not self._mic_analysis["has_data"]:
            issues.append("• 麦克风未采集到任何数据")
        elif self._mic_analysis["is_silent"]:
            issues.append("• 麦克风几乎全静音，请检查设备或音量")

        if not self._sys_analysis["has_data"]:
            issues.append("• 系统声音未采集到任何数据，请换用其他系统声音设备重录")
        elif self._sys_analysis["is_silent"]:
            issues.append("• 系统声音几乎全静音，请确认播放设备有声音输出，或换用其他系统声音设备")

        if issues:
            summary = "⚠️ <b>发现音频问题，建议检查后重新录制：</b><br>" + "<br>".join(issues)
            self._summary_label.setStyleSheet(
                "padding: 12px; background: #fff7e6; border: 1px solid #ffe58f; "
                "border-radius: 6px; color: #8b6914;"
            )
        else:
            summary = "✅ <b>两路音频均正常，可以继续</b>"
            self._summary_label.setStyleSheet(
                "padding: 12px; background: #e6f7e6; border: 1px solid #b7eb8f; "
                "border-radius: 6px; color: #237804;"
            )

        self._summary_label.setText(summary)

    def _on_rerecord(self):
        self.rerecord_requested.emit()
        self.reject()

    def has_mic_audio(self) -> bool:
        return self._mic_analysis["has_data"] and not self._mic_analysis["is_silent"]

    def has_system_audio(self) -> bool:
        return self._sys_analysis["has_data"] and not self._sys_analysis["is_silent"]
