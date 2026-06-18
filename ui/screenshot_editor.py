from PyQt5.QtWidgets import (QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QSpinBox, QColorDialog, QToolBar, QAction, QFileDialog, QMessageBox, QInputDialog, QSizePolicy)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal, QEvent
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QImage, QPainterPath, QFont, QGuiApplication
from typing import Optional, Tuple, List
from enum import Enum
import math


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
        self._annotations: List[ScreenshotAnnotation] = []
        self._current: Optional[ScreenshotAnnotation] = None
        self._tool = ScreenshotTool.NONE
        self._color: Tuple[int, int, int] = (255, 0, 0)
        self._thickness = 3
        self._mosaic_size = 15
        self._font_size = 14.0
        self._drawing = False

        self.setWindowTitle("截图编辑器 - 选择工具后按住鼠标左键拖拽标注")
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)

        arrow_action = QAction("→ 箭头", self)
        arrow_action.setShortcut("A")
        arrow_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.ARROW))
        toolbar.addAction(arrow_action)

        rect_action = QAction("□ 矩形", self)
        rect_action.setShortcut("R")
        rect_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.RECTANGLE))
        toolbar.addAction(rect_action)

        free_action = QAction("✏ 画笔", self)
        free_action.setShortcut("P")
        free_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.LINE))
        toolbar.addAction(free_action)

        text_action = QAction("T 文字", self)
        text_action.setShortcut("T")
        text_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.TEXT))
        toolbar.addAction(text_action)

        mosaic_action = QAction("▦ 马赛克", self)
        mosaic_action.setShortcut("M")
        mosaic_action.triggered.connect(lambda: self._select_tool(ScreenshotTool.MOSAIC))
        toolbar.addAction(mosaic_action)

        toolbar.addSeparator()

        color_action = QAction("🎨 颜色", self)
        color_action.triggered.connect(self._choose_color)
        toolbar.addAction(color_action)

        toolbar.addWidget(QLabel("粗细:"))
        self._thick_spin = QSpinBox()
        self._thick_spin.setRange(1, 30)
        self._thick_spin.setValue(3)
        self._thick_spin.valueChanged.connect(self._set_thickness)
        toolbar.addWidget(self._thick_spin)

        toolbar.addWidget(QLabel("字号:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 72)
        self._font_spin.setValue(14)
        self._font_spin.valueChanged.connect(self._set_font_size)
        toolbar.addWidget(self._font_spin)

        toolbar.addWidget(QLabel("马赛克:"))
        self._mosaic_spin = QSpinBox()
        self._mosaic_spin.setRange(5, 50)
        self._mosaic_spin.setValue(15)
        self._mosaic_spin.valueChanged.connect(self._set_mosaic_size)
        toolbar.addWidget(self._mosaic_spin)

        toolbar.addSeparator()

        undo_action = QAction("↶ 撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._undo)
        toolbar.addAction(undo_action)

        clear_action = QAction("✕ 清除", self)
        clear_action.triggered.connect(self._clear)
        toolbar.addAction(clear_action)

        toolbar.addSeparator()

        copy_action = QAction("📋 复制到剪贴板", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._copy_to_clipboard)
        toolbar.addAction(copy_action)

        save_action = QAction("💾 保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save)
        toolbar.addAction(save_action)

        main_layout.addWidget(toolbar)

        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setStyleSheet("background-color: #1e1e1e; border: 2px solid #444;")
        self._canvas.setMouseTracking(True)
        self._canvas.installEventFilter(self)
        main_layout.addWidget(self._canvas, 1)

        self._tool_label = QLabel("请先在工具栏选择一个标注工具")
        self._tool_label.setStyleSheet("color: #0078d4; padding: 6px; font-weight: bold;")
        main_layout.addWidget(self._tool_label)

        self.resize(min(1200, self._original.width() + 60), min(850, self._original.height() + 140))
        self._update_canvas()

    def _select_tool(self, tool: ScreenshotTool):
        self._tool = tool
        names = {
            ScreenshotTool.ARROW: "箭头 (A) - 按住拖拽绘制指向箭头",
            ScreenshotTool.RECTANGLE: "矩形 (R) - 按住拖拽绘制矩形高亮",
            ScreenshotTool.LINE: "自由绘制 (P) - 按住拖拽自由画线",
            ScreenshotTool.TEXT: "文字 (T) - 点击位置后输入文字",
            ScreenshotTool.MOSAIC: "马赛克 (M) - 按住拖拽遮盖敏感区域",
            ScreenshotTool.NONE: "请先选择一个标注工具"
        }
        self._tool_label.setText(f"当前工具: {names[tool]}")

        if tool in [ScreenshotTool.ARROW, ScreenshotTool.RECTANGLE, ScreenshotTool.MOSAIC, ScreenshotTool.LINE]:
            self._canvas.setCursor(Qt.CrossCursor)
        elif tool == ScreenshotTool.TEXT:
            self._canvas.setCursor(Qt.IBeamCursor)
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

    def _set_mosaic_size(self, v: int):
        self._mosaic_size = v

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
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._handle_mouse_press(event)
                return True
            elif event.type() == QEvent.MouseMove:
                self._handle_mouse_move(event)
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._handle_mouse_release(event)
                return True
        return super().eventFilter(obj, event)

    def _get_image_point(self, event_pos: QPoint) -> QPoint:
        canvas_rect = self._canvas.rect()
        orig_w = self._original.width()
        orig_h = self._original.height()
        cw, ch = canvas_rect.width(), canvas_rect.height()

        if orig_w <= 0 or orig_h <= 0 or cw <= 0 or ch <= 0:
            return QPoint(0, 0)

        scale = min(cw / orig_w, ch / orig_h)
        draw_w = int(orig_w * scale)
        draw_h = int(orig_h * scale)
        offset_x = (cw - draw_w) // 2
        offset_y = (ch - draw_h) // 2

        x = event_pos.x() - offset_x
        y = event_pos.y() - offset_y

        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if draw_w > 0:
            x = int(x * orig_w / draw_w)
        if draw_h > 0:
            y = int(y * orig_h / draw_h)

        x = max(0, min(orig_w - 1, x))
        y = max(0, min(orig_h - 1, y))
        return QPoint(x, y)

    def _handle_mouse_press(self, event):
        if self._tool == ScreenshotTool.NONE:
            self._tool_label.setText("⚠ 请先在工具栏选择一个标注工具！")
            return
        pos = self._get_image_point(event.pos())
        self._drawing = True
        ann = ScreenshotAnnotation(self._tool)
        ann.color = self._color
        ann.thickness = self._thickness
        ann.mosaic_size = self._mosaic_size
        ann.font_size = self._font_size
        ann.start = QPoint(pos)
        ann.end = QPoint(pos)
        ann.points = [QPoint(pos)]
        self._current = ann
        self._update_canvas()

    def _handle_mouse_move(self, event):
        if not self._drawing or not self._current:
            return
        pos = self._get_image_point(event.pos())
        self._current.end = QPoint(pos)
        self._current.points.append(QPoint(pos))
        self._update_canvas()

    def _handle_mouse_release(self, event):
        if not self._drawing or not self._current:
            return
        self._drawing = False

        if self._current.tool == ScreenshotTool.TEXT:
            text, ok = QInputDialog.getText(self, "输入文字", "请输入标注文字：")
            if not ok or not text.strip():
                self._current = None
                self._update_canvas()
                return
            self._current.text = text.strip()

        if self._current.tool == ScreenshotTool.TEXT or len(self._current.points) >= 1:
            self._annotations.append(self._current)
        self._current = None
        self._update_canvas()

    def _apply_mosaic_to_image(self, qimg: QImage, rect: QRect, block_size: int):
        if rect.width() < 2 or rect.height() < 2:
            return
        x1 = max(0, rect.left())
        y1 = max(0, rect.top())
        x2 = min(qimg.width() - 1, rect.right())
        y2 = min(qimg.height() - 1, rect.bottom())

        block_size = max(2, block_size)

        for by in range(y1, y2 + 1, block_size):
            for bx in range(x1, x2 + 1, block_size):
                end_x = min(bx + block_size - 1, x2)
                end_y = min(by + block_size - 1, y2)

                r_sum = g_sum = b_sum = 0
                count = 0
                for py in range(by, end_y + 1):
                    for px in range(bx, end_x + 1):
                        c = qimg.pixelColor(px, py)
                        r_sum += c.red()
                        g_sum += c.green()
                        b_sum += c.blue()
                        count += 1
                if count > 0:
                    avg_r = r_sum // count
                    avg_g = g_sum // count
                    avg_b = b_sum // count
                    fill_color = QColor(avg_r, avg_g, avg_b)
                    for py in range(by, end_y + 1):
                        for px in range(bx, end_x + 1):
                            qimg.setPixelColor(px, py, fill_color)

    def _render_image(self, include_current=True) -> QImage:
        qimg = QImage(self._original)

        all_annotations = list(self._annotations)
        if include_current and self._current:
            all_annotations.append(self._current)

        for ann in all_annotations:
            painter = QPainter(qimg)
            painter.setRenderHint(QPainter.Antialiasing)

            r, g, b = ann.color
            color = QColor(r, g, b)
            pen = QPen(color, ann.thickness)
            painter.setPen(pen)

            if ann.tool == ScreenshotTool.MOSAIC and ann.start and ann.end:
                rect = QRect(ann.start, ann.end).normalized()
                painter.end()
                self._apply_mosaic_to_image(qimg, rect, ann.mosaic_size)
                painter = QPainter(qimg)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor(200, 50, 50), 1, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)

            elif ann.tool == ScreenshotTool.ARROW and ann.start and ann.end:
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
                font.setBold(True)
                painter.setFont(font)
                pen = QPen(color, ann.thickness)
                painter.setPen(pen)
                painter.drawText(ann.start, ann.text)

            painter.end()

        return qimg

    def _update_canvas(self):
        rendered = self._render_image()
        canvas_size = self._canvas.size()
        scaled = rendered.scaled(canvas_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._canvas.setPixmap(QPixmap.fromImage(scaled))

    def _draw_arrow(self, painter: QPainter, start: QPoint, end: QPoint, color: QColor, thickness: int):
        painter.drawLine(start, end)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx == 0 and dy == 0:
            return
        angle = math.atan2(dy, dx)
        size = max(12, thickness * 5)
        p1x = int(end.x() - size * math.cos(angle - math.pi / 6))
        p1y = int(end.y() - size * math.sin(angle - math.pi / 6))
        p2x = int(end.x() - size * math.cos(angle + math.pi / 6))
        p2y = int(end.y() - size * math.sin(angle + math.pi / 6))
        painter.setBrush(QBrush(color))
        path = QPainterPath()
        path.moveTo(end)
        path.lineTo(QPoint(p1x, p1y))
        path.lineTo(QPoint(p2x, p2y))
        path.closeSubpath()
        painter.drawPath(path)

    def _copy_to_clipboard(self):
        rendered = self._render_image(include_current=False)
        clipboard = QGuiApplication.clipboard()
        clipboard.setImage(rendered)
        self._tool_label.setText(f"✅ 已复制到剪贴板！共 {len(self._annotations)} 个标注")
        QMessageBox.information(self, "完成", f"已复制到剪贴板！\n共包含 {len(self._annotations)} 个标注。")

    def _save(self):
        rendered = self._render_image(include_current=False)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", "screenshot.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)"
        )
        if path:
            rendered.save(path)
            QMessageBox.information(self, "完成", f"已保存到:\n{path}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_canvas()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
