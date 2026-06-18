from PyQt5.QtWidgets import (QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QComboBox, QSpinBox, QColorDialog, QToolBar, QAction, QFileDialog, QMessageBox, QInputDialog, QSizePolicy)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QImage, QPainterPath, QMouseEvent, QFont, QGuiApplication, QFontMetrics
from typing import Optional, Tuple, List
from enum import Enum
import numpy as np
import cv2


class ScreenshotTool(Enum):
    NONE = "none"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    TEXT = "text"
    MOSAIC = "mosaic"
    LINE = "freehand"


class ScreenshotAnnotation:
    def __init__(self, tool: ScreenshotTool):
        self.tool = tool
        self.color: Tuple[int, int, int] = (255, 0, 0)
        self.thickness: int = 3
        self.start: Optional[QPoint] = None
        self.end: Optional[QPoint] = None
        self.points: List[QPoint] = []
        self.text: str = ""
        self.font_size: float = 14.0
        self.mosaic_size: int = 15


class ScreenshotEditor(QWidget):
    closed = pyqtSignal()
    
    def __init__(self, screenshot: QPixmap):
        super().__init__()
        self._original = screenshot
        self._pixmap = screenshot.copy()
        self._annotations: List[ScreenshotAnnotation] = []
        self._current: Optional[ScreenshotAnnotation] = None
        self._tool = ScreenshotTool.NONE
        self._color: Tuple[int, int, int] = (255, 0, 0)
        self._thickness = 3
        self._mosaic_size = 15
        self._font_size = 14.0
        self._drawing = False
        self._zoom = 1.0
        
        self.setWindowTitle("截图编辑器")
        self._init_ui()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        
        arrow_action = QAction("箭头", self)
        arrow_action.setShortcut("A")
        arrow_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.ARROW))
        toolbar.addAction(arrow_action)
        
        rect_action = QAction("矩形", self)
        rect_action.setShortcut("R")
        rect_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.RECTANGLE))
        toolbar.addAction(rect_action)
        
        free_action = QAction("画笔", self)
        free_action.setShortcut("P")
        free_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.LINE))
        toolbar.addAction(free_action)
        
        text_action = QAction("文字", self)
        text_action.setShortcut("T")
        text_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.TEXT))
        toolbar.addAction(text_action)
        
        mosaic_action = QAction("马赛克", self)
        mosaic_action.setShortcut("M")
        mosaic_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.MOSAIC))
        toolbar.addAction(mosaic_action)
        
        toolbar.addSeparator()
        
        color_action = QAction("颜色", self)
        color_action.triggered.connect(self._choose_color)
        toolbar.addAction(color_action)
        
        toolbar.addWidget(QLabel(" 粗细:"))
        self._thick_spin = QSpinBox()
        self._thick_spin.setRange(1, 30)
        self._thick_spin.setValue(3)
        self._thick_spin.valueChanged.connect(self._set_thickness)
        toolbar.addWidget(self._thick_spin)
        
        toolbar.addWidget(QLabel(" 字号:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 72)
        self._font_spin.setValue(14)
        self._font_spin.valueChanged.connect(self._set_font_size)
        toolbar.addWidget(self._font_spin)
        
        toolbar.addSeparator()
        
        undo_action = QAction("撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._undo)
        toolbar.addAction(undo_action)
        
        clear_action = QAction("清除", self)
        clear_action.triggered.connect(self._clear)
        toolbar.addAction(clear_action)
        
        toolbar.addSeparator()
        
        copy_action = QAction("复制到剪贴板", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._copy_to_clipboard)
        toolbar.addAction(copy_action)
        
        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save)
        toolbar.addAction(save_action)
        
        main_layout.addWidget(toolbar)
        
        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setStyleSheet("background-color: #2b2b2b;")
        self._canvas.setMouseTracking(True)
        self._canvas.installEventFilter(self)
        main_layout.addWidget(self._canvas, 1)
        
        self._tool_label = QLabel("")
        self._tool_label.setStyleSheet("color: #888; padding: 4px;")
        main_layout.addWidget(self._tool_label)
        
        self.resize(min(1200, self._original.width() + 50), min(800, self._original.height() + 120))
        self._update_canvas()
    
    def _select_tool(self, tool: ScreenshotTool):
        self._tool = tool
        names = {
            ScreenshotTool.ARROW: "箭头 (A)",
            ScreenshotTool.RECTANGLE: "矩形 (R)",
            ScreenshotTool.LINE: "自由绘制 (P)",
            ScreenshotTool.TEXT: "文字 (T)",
            ScreenshotTool.MOSAIC: "马赛克 (M)",
            ScreenshotTool.NONE: "选择工具"
        }
        self._tool_label.setText(f"当前工具: {names[tool]}")
        
        if tool in [ScreenshotTool.ARROW, ScreenshotTool.RECTANGLE, ScreenshotTool.MOSAIC]:
            self._canvas.setCursor(Qt.CrossCursor)
        elif tool == ScreenshotTool.TEXT:
            self._canvas.setCursor(Qt.IBeamCursor)
        elif tool == ScreenshotTool.LINE:
            self._canvas.setCursor(Qt.PointingHandCursor)
        else:
            self._canvas.setCursor(Qt.ArrowCursor)
    
    def _choose_color(self):
        r, g, b = self._color
        color = QColorDialog.getColor(QColor(r, g, b), self, "选择颜色")
        if color.isValid():
            self._color = (color.red(), color.green(), color.blue())
    
    def _set_thickness(self, v: int):
        self._thickness = v
    
    def _set_font_size(self, v: int):
        self._font_size = float(v)
    
    def _undo(self):
        if self._annotations:
            self._annotations.pop()
            self._update_canvas()
    
    def _clear(self):
        self._annotations.clear()
        self._current = None
        self._update_canvas()
    
    def eventFilter(self, obj, event):
        if obj is self._canvas:
            if event.type() == QMouseEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._handle_mouse_press(event)
                return True
            elif event.type() == QMouseEvent.MouseMove:
                self._handle_mouse_move(event)
                return True
            elif event.type() == QMouseEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._handle_mouse_release(event)
                return True
        return super().eventFilter(obj, event)
    
    def _get_image_point(self, event_pos: QPoint) -> QPoint:
        canvas_rect = self._canvas.rect()
        pm_size = self._pixmap.size()
        scaled = self._pixmap.scaled(canvas_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled_rect = QRect(
            (canvas_rect.width() - scaled.width()) // 2,
            (canvas_rect.height() - scaled.height()) // 2,
            scaled.width(), scaled.height()
        )
        
        x_in_scaled = event_pos.x() - scaled_rect.x()
        y_in_scaled = event_pos.y() - scaled_rect.y()
        
        if scaled.width() > 0 and scaled.height() > 0:
            scale_x = pm_size.width() / scaled.width()
            scale_y = pm_size.height() / scaled.height()
            return QPoint(int(x_in_scaled * scale_x), int(y_in_scaled * scale_y))
        return QPoint(0, 0)
    
    def _handle_mouse_press(self, event):
        if self._tool == ScreenshotTool.NONE:
            return
        pos = self._get_image_point(event.pos())
        self._drawing = True
        ann = ScreenshotAnnotation(self._tool)
        ann.color = self._color
        ann.thickness = self._thickness
        ann.mosaic_size = self._mosaic_size
        ann.font_size = self._font_size
        ann.start = pos
        ann.end = pos
        ann.points = [pos]
        self._current = ann
    
    def _handle_mouse_move(self, event):
        if not self._drawing or not self._current:
            return
        pos = self._get_image_point(event.pos())
        self._current.end = pos
        self._current.points.append(pos)
        self._update_canvas()
    
    def _handle_mouse_release(self, event):
        if not self._drawing or not self._current:
            return
        self._drawing = False
        
        if self._current.tool == ScreenshotTool.TEXT:
            text, ok = QInputDialog.getText(self, "输入文字", "请输入标注文字：")
            if not ok:
                self._current = None
                self._update_canvas()
                return
            self._current.text = text
        
        self._annotations.append(self._current)
        self._current = None
        self._update_canvas()
    
    def _update_canvas(self):
        result = self._original.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for ann in self._annotations:
            self._draw_annotation(painter, ann)
        if self._current:
            self._draw_annotation(painter, self._current)
        
        painter.end()
        
        canvas_size = self._canvas.size()
        scaled = result.scaled(canvas_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._canvas.setPixmap(scaled)
    
    def _draw_annotation(self, painter: QPainter, ann: ScreenshotAnnotation):
        r, g, b = ann.color
        color = QColor(r, g, b)
        pen = QPen(color, ann.thickness)
        painter.setPen(pen)
        
        if ann.tool == ScreenshotTool.ARROW and ann.start and ann.end:
            self._draw_arrow(painter, ann.start, ann.end, color, ann.thickness)
        
        elif ann.tool == ScreenshotTool.RECTANGLE and ann.start and ann.end:
            rect = QRect(ann.start, ann.end).normalized()
            painter.drawRect(rect)
        
        elif ann.tool == ScreenshotTool.LINE and len(ann.points) >= 2:
            path = QPainterPath()
            path.moveTo(ann.points[0])
            for p in ann.points[1:]:
                path.lineTo(p)
            painter.drawPath(path)
        
        elif ann.tool == ScreenshotTool.TEXT and ann.start and ann.text:
            font = QFont()
            font.setPointSizeF(ann.font_size)
            painter.setFont(font)
            painter.drawText(ann.start, ann.text)
        
        elif ann.tool == ScreenshotTool.MOSAIC and ann.start and ann.end:
            rect = QRect(ann.start, ann.end).normalized()
            painter.setBrush(QBrush(QColor(100, 100, 100, 180)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(rect)
            painter.setPen(QPen(QColor(200, 50, 50), 2, Qt.DashLine))
            painter.drawRect(rect)
    
    def _draw_arrow(self, painter, start, end, color, thickness):
        painter.drawLine(start, end)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx == 0 and dy == 0:
            return
        import math
        angle = math.atan2(dy, dx)
        size = max(15, thickness * 4)
        p1 = QPoint(int(end.x() - size * math.cos(angle - math.pi / 6)),
                              int(end.y() - size * math.sin(angle - math.pi / 6)))
        p2 = QPoint(int(end.x() - size * math.cos(angle + math.pi / 6)),
                              int(end.y() - size * math.sin(angle + math.pi / 6)))
        painter.setBrush(QBrush(color))
        path = QPainterPath()
        path.moveTo(end)
        path.lineTo(p1)
        path.lineTo(p2)
        path.closeSubpath()
        painter.drawPath(path)
    
    def _copy_to_clipboard(self):
        result = self._original.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        for ann in self._annotations:
            self._draw_annotation(painter, ann)
        painter.end()
        
        clipboard = QGuiApplication.clipboard()
        clipboard.setPixmap(result)
        QMessageBox.information(self, "完成", "已复制到剪贴板！")
    
    def _save(self):
        result = self._original.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        for ann in self._annotations:
            self._draw_annotation(painter, ann)
        painter.end()
        
        path, _ = QFileDialog.getSaveFileName(self, "保存截图", "screenshot.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        if path:
            result.save(path)
            QMessageBox.information(self, "完成", f"已保存到:\n{path}")
    
    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
