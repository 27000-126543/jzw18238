from PyQt5.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSpinBox, QColorDialog, QToolBar, QAction, QFileDialog, QMessageBox, QInputDialog, QSizePolicy, QMenu, QPushButton, QToolButton)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal, QEvent
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QImage, QPainterPath, QFont, QGuiApplication, QFontMetrics
from typing import Optional, Tuple, List
from enum import Enum
import math
import numpy as np


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
    file_saved = pyqtSignal(str)

    def __init__(self, screenshot: QPixmap):
        super().__init__()
        self._original_image = screenshot.toImage().convertToFormat(QImage.Format_RGB888).copy()
        self._annotations: List[ScreenshotAnnotation] = []
        self._current: Optional[ScreenshotAnnotation] = None
        self._tool = ScreenshotTool.NONE
        self._color: Tuple[int, int, int] = (255, 0, 0)
        self._thickness = 3
        self._mosaic_size = 15
        self._font_size = 14.0
        self._drawing = False
        self._error_msg = ""

        self.setWindowTitle("截图编辑器 - 先选工具再按住鼠标左键拖拽")
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

        copy_menu = QMenu()
        copy_full_action = QAction("📋 复制整张截图", self)
        copy_full_action.setShortcut("Ctrl+C")
        copy_full_action.triggered.connect(lambda: self._copy_to_clipboard(mode="full"))
        copy_menu.addAction(copy_full_action)

        copy_roi_action = QAction("✂ 仅复制标注区域", self)
        copy_roi_action.setShortcut("Ctrl+Shift+C")
        copy_roi_action.triggered.connect(lambda: self._copy_to_clipboard(mode="region"))
        copy_menu.addAction(copy_roi_action)

        copy_btn = QToolButton()
        copy_btn.setText("📋 复制")
        copy_btn.setMenu(copy_menu)
        copy_btn.setPopupMode(QToolButton.MenuButtonPopup)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(mode="full"))
        copy_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        copy_btn.setStyleSheet("QToolButton { padding: 4px 10px; }")
        toolbar.addWidget(copy_btn)

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
        self._canvas.setMinimumSize(640, 360)
        main_layout.addWidget(self._canvas, 1)

        self._tool_label = QLabel("请先在工具栏选择一个标注工具")
        self._tool_label.setStyleSheet("color: #0078d4; padding: 6px; font-weight: bold;")
        main_layout.addWidget(self._tool_label)

        w = min(1200, max(680, self._original_image.width() + 60))
        h = min(850, max(500, self._original_image.height() + 140))
        self.resize(w, h)

        from PyQt5.QtCore import QTimer
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._update_canvas_safe)
        self._update_timer.start(50)

    def _select_tool(self, tool: ScreenshotTool):
        self._tool = tool
        names = {
            ScreenshotTool.ARROW: "箭头 (A) - 按住拖拽",
            ScreenshotTool.RECTANGLE: "矩形 (R) - 按住拖拽",
            ScreenshotTool.LINE: "画笔 (P) - 按住拖拽",
            ScreenshotTool.TEXT: "文字 (T) - 点击输入",
            ScreenshotTool.MOSAIC: "马赛克 (M) - 按住拖拽",
            ScreenshotTool.NONE: "请先选择一个标注工具"
        }
        self._tool_label.setText(f"当前: {names[tool]}")

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
            self._schedule_update()

    def _clear(self):
        self._annotations.clear()
        self._current = None
        self._schedule_update()

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
        try:
            canvas_rect = self._canvas.rect()
            orig_w = self._original_image.width()
            orig_h = self._original_image.height()
            cw, ch = canvas_rect.width(), canvas_rect.height()

            if orig_w <= 0 or orig_h <= 0 or cw <= 0 or ch <= 0:
                return QPoint(0, 0)

            scale = min(cw / orig_w, ch / orig_h)
            draw_w = max(1, int(orig_w * scale))
            draw_h = max(1, int(orig_h * scale))
            offset_x = (cw - draw_w) // 2
            offset_y = (ch - draw_h) // 2

            x = event_pos.x() - offset_x
            y = event_pos.y() - offset_y
            x = max(0, min(draw_w - 1, x))
            y = max(0, min(draw_h - 1, y))

            ix = int(x * orig_w / draw_w)
            iy = int(y * orig_h / draw_h)
            ix = max(0, min(orig_w - 1, ix))
            iy = max(0, min(orig_h - 1, iy))
            return QPoint(ix, iy)
        except Exception:
            return QPoint(0, 0)

    def _handle_mouse_press(self, event):
        if self._tool == ScreenshotTool.NONE:
            self._tool_label.setText("⚠ 请先在工具栏选择一个标注工具！")
            return
        pos = self._get_image_point(event.pos())
        self._drawing = True
        ann = ScreenshotAnnotation(self._tool)
        ann.color = (self._color[0], self._color[1], self._color[2])
        ann.thickness = self._thickness
        ann.mosaic_size = self._mosaic_size
        ann.font_size = self._font_size
        ann.start = QPoint(pos)
        ann.end = QPoint(pos)
        ann.points = [QPoint(pos)]
        self._current = ann
        self._schedule_update()

    def _handle_mouse_move(self, event):
        if not self._drawing or not self._current:
            return
        pos = self._get_image_point(event.pos())
        self._current.end = QPoint(pos)
        self._current.points.append(QPoint(pos))
        self._schedule_update()

    def _handle_mouse_release(self, event):
        if not self._drawing or not self._current:
            return
        self._drawing = False
        if self._current.tool == ScreenshotTool.TEXT:
            text, ok = QInputDialog.getText(self, "输入文字", "请输入标注文字：")
            if not ok or not text.strip():
                self._current = None
                self._schedule_update()
                return
            self._current.text = text.strip()

        if self._current.tool == ScreenshotTool.TEXT or len(self._current.points) >= 1:
            self._annotations.append(self._current)
        self._current = None
        self._schedule_update()

    def _schedule_update(self):
        from PyQt5.QtCore import QTimer
        if not hasattr(self, '_update_timer'):
            self._update_timer = QTimer(self)
            self._update_timer.setSingleShot(True)
            self._update_timer.timeout.connect(self._update_canvas_safe)
        if not self._update_timer.isActive():
            self._update_timer.start(16)

    def _qimage_to_numpy(self, qimg: QImage) -> np.ndarray:
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(h * w * 3)
        arr = np.frombuffer(ptr, np.uint8).reshape(h, w, 3).copy()
        return arr

    def _numpy_to_qimage(self, arr: np.ndarray) -> QImage:
        h, w, ch = arr.shape
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
        qimg = QImage(arr.data, w, h, ch * w, QImage.Format_RGB888)
        return qimg.copy()

    def _apply_mosaic_numpy(self, qimg: QImage, rect: QRect, block_size: int) -> QImage:
        try:
            x1 = max(0, rect.left())
            y1 = max(0, rect.top())
            x2 = min(qimg.width() - 1, rect.right())
            y2 = min(qimg.height() - 1, rect.bottom())
            if x2 <= x1 or y2 <= y1:
                return qimg

            block_size = max(2, block_size)
            arr = self._qimage_to_numpy(qimg)
            roi = arr[y1:y2 + 1, x1:x2 + 1].copy()
            rh, rw = roi.shape[:2]

            new_h = max(1, rh // block_size)
            new_w = max(1, rw // block_size)
            import cv2
            small = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            mosaic = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
            arr[y1:y2 + 1, x1:x2 + 1] = mosaic
            return self._numpy_to_qimage(arr)
        except Exception:
            return qimg

    def _render_image(self, include_current: bool = True) -> Optional[QImage]:
        try:
            qimg = self._original_image.copy()
            if qimg.isNull():
                self._error_msg = "底图数据为空"
                return None

            all_anns = list(self._annotations)
            if include_current and self._current:
                all_anns.append(self._current)

            mosaic_rects = []
            for ann in all_anns:
                if ann.tool == ScreenshotTool.MOSAIC and ann.start and ann.end:
                    mosaic_rects.append((QRect(ann.start, ann.end).normalized(), ann.mosaic_size))

            if mosaic_rects:
                for rect, bs in mosaic_rects:
                    qimg = self._apply_mosaic_numpy(qimg, rect, bs)
                if qimg.isNull():
                    return self._original_image.copy()

            painter = QPainter(qimg)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)

                for ann in all_anns:
                    if ann.tool == ScreenshotTool.MOSAIC:
                        if ann.start and ann.end:
                            rect = QRect(ann.start, ann.end).normalized()
                            painter.setPen(QPen(QColor(200, 50, 50), 1, Qt.DashLine))
                            painter.setBrush(Qt.NoBrush)
                            painter.drawRect(rect)
                        continue

                    r, g, b = ann.color
                    color = QColor(r, g, b)
                    pen = QPen(color, ann.thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)

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
                        font.setBold(True)
                        painter.setFont(font)
                        painter.drawText(ann.start, ann.text)
            finally:
                painter.end()

            return qimg.copy()
        except Exception as e:
            self._error_msg = f"渲染错误: {str(e)}"
            return self._original_image.copy()

    def _update_canvas_safe(self):
        try:
            rendered = self._render_image()
            if rendered is None or rendered.isNull():
                self._canvas.setText(f"⚠ 渲染失败: {self._error_msg}")
                self._canvas.setStyleSheet("background-color: #3a1e1e; color: #ff6060; border: 2px solid #aa4444;")
                return

            self._canvas.setStyleSheet("background-color: #1e1e1e; border: 2px solid #444;")
            canvas_size = self._canvas.size()
            if canvas_size.width() <= 2 or canvas_size.height() <= 2:
                canvas_size = QSize(800, 500)

            scaled = rendered.scaled(
                canvas_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if scaled.isNull():
                self._canvas.setText("⚠ 缩放失败")
                return

            pix = QPixmap.fromImage(scaled)
            if pix.isNull():
                self._canvas.setText("⚠ Pixmap创建失败")
                return

            self._canvas.setPixmap(pix)
            if self._error_msg:
                self._tool_label.setText(f"当前: {len(self._annotations)} 个标注")
                self._error_msg = ""
        except Exception as e:
            self._canvas.setStyleSheet("background-color: #3a1e1e; color: #ff6060;")
            self._canvas.setText(f"⚠ 异常: {str(e)}")

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
        painter.setBrush(Qt.NoBrush)

    def _get_annotation_bounds(self, padding: int = 20) -> Optional[QRect]:
        if len(self._annotations) == 0:
            return None

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for ann in self._annotations:
            if ann.tool == ScreenshotTool.LINE and len(ann.points) > 0:
                for p in ann.points:
                    min_x = min(min_x, p.x())
                    min_y = min(min_y, p.y())
                    max_x = max(max_x, p.x())
                    max_y = max(max_y, p.y())
            elif ann.start and ann.end:
                rect = QRect(ann.start, ann.end).normalized()
                min_x = min(min_x, rect.left())
                min_y = min(min_y, rect.top())
                max_x = max(max_x, rect.right())
                max_y = max(max_y, rect.bottom())
            elif ann.start and ann.text:
                fm = QFontMetrics(QFont())
                text_rect = fm.boundingRect(ann.text)
                min_x = min(min_x, ann.start.x())
                min_y = min(min_y, ann.start.y() - text_rect.height())
                max_x = max(max_x, ann.start.x() + text_rect.width())
                max_y = max(max_y, ann.start.y())

        if min_x == float('inf'):
            return None

        img_w = self._original_image.width()
        img_h = self._original_image.height()
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x = min(img_w - 1, max_x + padding)
        max_y = min(img_h - 1, max_y + padding)

        return QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

    def _copy_to_clipboard(self, mode: str = "full"):
        try:
            rendered = self._render_image(include_current=False)
            if rendered is None or rendered.isNull():
                QMessageBox.warning(self, "失败", f"无法生成图像: {self._error_msg}")
                return

            final_img = rendered
            info_text = ""

            if mode == "region":
                bounds = self._get_annotation_bounds(padding=25)
                if bounds is None or bounds.width() < 10 or bounds.height() < 10:
                    QMessageBox.information(self, "提示", "还没有任何标注，无法复制标注区域\n请先画点东西再使用此功能")
                    return
                final_img = rendered.copy(bounds)
                info_text = f" ({bounds.width()}×{bounds.height()})"

            if final_img.isNull():
                QMessageBox.warning(self, "失败", "裁剪后的图像为空")
                return

            clipboard = QGuiApplication.clipboard()
            clipboard.setImage(final_img)
            count = len(self._annotations)
            mode_text = "整张截图" if mode == "full" else "标注区域"
            self._tool_label.setText(f"✅ 已复制{mode_text}！共 {count} 个标注{info_text}")
            QMessageBox.information(self, "成功",
                                    f"已复制{mode_text}到剪贴板！\n共 {count} 个标注{info_text}")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"复制出错: {str(e)}")

    def _save(self):
        try:
            rendered = self._render_image(include_current=False)
            if rendered is None or rendered.isNull():
                QMessageBox.warning(self, "失败", f"无法生成图像: {self._error_msg}")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "保存截图", "screenshot.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)"
            )
            if path:
                if rendered.save(path):
                    QMessageBox.information(self, "成功", f"已保存到:\n{path}")
                    self.file_saved.emit(path)
                else:
                    QMessageBox.critical(self, "失败", "保存失败")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"保存出错: {str(e)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_update()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_update()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
