from PyQt5.QtWidgets import QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QSpinBox, QColorDialog, QInputDialog, QToolBar, QAction, QMenu
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPixmap, QPainterPath, QMouseEvent, QKeyEvent
from typing import Optional, Tuple, List
from core.annotation_engine import AnnotationEngine, AnnotationType


class AnnotationOverlay(QWidget):
    annotation_started = pyqtSignal()
    annotation_finished = pyqtSignal()
    tool_changed = pyqtSignal(str)
    
    def __init__(self, engine: AnnotationEngine):
        super().__init__()
        self._engine = engine
        self._engine.annotations_changed.connect(self.update)
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        
        self._current_tool: Optional[AnnotationType] = None
        self._current_color: Tuple[int, int, int] = (255, 0, 0)
        self._current_thickness = 3
        self._mosaic_size = 15
        self._drawing = False
        self._start_point: Optional[QPoint] = None
        self._end_point: Optional[QPoint] = None
        self._points: List[QPoint] = []
        
        self._toolbar_visible = True
        self._init_ui()
        
        self._engine.set_active(True)
    
    def _init_ui(self):
        screen = self.screen().geometry() if self.screen() else QRect(0, 0, 1920, 1080)
        self.setGeometry(screen)
        
        self._toolbar = QWidget(self)
        self._toolbar.setStyleSheet("""
            QWidget {
                background-color: rgba(50, 50, 50, 230);
                border-radius: 8px;
                padding: 4px;
            }
            QPushButton {
                background-color: rgba(70, 70, 70, 200);
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                margin: 2px;
                font-size: 12px;
                min-width: 40px;
            }
            QPushButton:hover {
                background-color: rgba(100, 100, 100, 200);
            }
            QPushButton:checked {
                background-color: rgba(0, 120, 215, 200);
            }
            QComboBox, QSpinBox {
                background-color: rgba(70, 70, 70, 200);
                color: white;
                border: 1px solid rgba(100, 100, 100, 200);
                border-radius: 4px;
                padding: 4px;
                margin: 2px;
                font-size: 12px;
            }
        """)
        
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(2)
        
        self._btn_arrow = QPushButton("→")
        self._btn_arrow.setCheckable(True)
        self._btn_arrow.setToolTip("箭头 (A)")
        self._btn_arrow.clicked.connect(lambda: self._select_tool(AnnotationType.ARROW))
        toolbar_layout.addWidget(self._btn_arrow)
        
        self._btn_rect = QPushButton("□")
        self._btn_rect.setCheckable(True)
        self._btn_rect.setToolTip("矩形 (R)")
        self._btn_rect.clicked.connect(lambda: self._select_tool(AnnotationType.RECTANGLE))
        toolbar_layout.addWidget(self._btn_rect)
        
        self._btn_line = QPushButton("✏")
        self._btn_line.setCheckable(True)
        self._btn_line.setToolTip("自由绘制 (P)")
        self._btn_line.clicked.connect(lambda: self._select_tool(AnnotationType.LINE))
        toolbar_layout.addWidget(self._btn_line)
        
        self._btn_text = QPushButton("T")
        self._btn_text.setCheckable(True)
        self._btn_text.setToolTip("文字 (T)")
        self._btn_text.clicked.connect(lambda: self._select_tool(AnnotationType.TEXT))
        toolbar_layout.addWidget(self._btn_text)
        
        self._btn_mosaic = QPushButton("▦")
        self._btn_mosaic.setCheckable(True)
        self._btn_mosaic.setToolTip("马赛克 (M)")
        self._btn_mosaic.clicked.connect(lambda: self._select_tool(AnnotationType.MOSAIC))
        toolbar_layout.addWidget(self._btn_mosaic)
        
        toolbar_layout.addSpacing(8)
        
        self._color_btn = QPushButton("色")
        self._color_btn.setToolTip("选择颜色")
        self._update_color_button()
        self._color_btn.clicked.connect(self._choose_color)
        toolbar_layout.addWidget(self._color_btn)
        
        thickness_label = QLabel("粗")
        thickness_label.setStyleSheet("color: white; font-size: 11px;")
        toolbar_layout.addWidget(thickness_label)
        self._thickness_spin = QSpinBox()
        self._thickness_spin.setRange(1, 30)
        self._thickness_spin.setValue(3)
        self._thickness_spin.valueChanged.connect(self._set_thickness)
        toolbar_layout.addWidget(self._thickness_spin)
        
        mosaic_label = QLabel("马")
        mosaic_label.setStyleSheet("color: white; font-size: 11px;")
        toolbar_layout.addWidget(mosaic_label)
        self._mosaic_spin = QSpinBox()
        self._mosaic_spin.setRange(5, 50)
        self._mosaic_spin.setValue(15)
        self._mosaic_spin.valueChanged.connect(self._set_mosaic_size)
        toolbar_layout.addWidget(self._mosaic_spin)
        
        toolbar_layout.addSpacing(8)
        
        self._btn_undo = QPushButton("↶")
        self._btn_undo.setToolTip("撤销 (Ctrl+Z)")
        self._btn_undo.clicked.connect(self._engine.undo)
        toolbar_layout.addWidget(self._btn_undo)
        
        self._btn_clear = QPushButton("✕")
        self._btn_clear.setToolTip("清除全部")
        self._btn_clear.clicked.connect(self._engine.clear)
        toolbar_layout.addWidget(self._btn_clear)
        
        toolbar_layout.addSpacing(8)
        
        self._btn_close = QPushButton("隐藏")
        self._btn_close.setToolTip("隐藏工具栏 (F2)")
        self._btn_close.clicked.connect(self._toggle_toolbar)
        toolbar_layout.addWidget(self._btn_close)
        
        toolbar_width = self._toolbar.sizeHint().width()
        toolbar_x = (screen.width() - toolbar_width) // 2
        self._toolbar.move(toolbar_x, 10)
    
    def _select_tool(self, tool: AnnotationType):
        self._current_tool = tool
        self.tool_changed.emit(tool.value)
        
        self._btn_arrow.setChecked(tool == AnnotationType.ARROW)
        self._btn_rect.setChecked(tool == AnnotationType.RECTANGLE)
        self._btn_line.setChecked(tool == AnnotationType.LINE)
        self._btn_text.setChecked(tool == AnnotationType.TEXT)
        self._btn_mosaic.setChecked(tool == AnnotationType.MOSAIC)
    
    def _choose_color(self):
        color = QColorDialog.getColor(QColor(*self._current_color), self, "选择颜色")
        if color.isValid():
            self._current_color = (color.red(), color.green(), color.blue())
            self._update_color_button()
    
    def _update_color_button(self):
        r, g, b = self._current_color
        self._color_btn.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); color: white;")
    
    def _set_thickness(self, value: int):
        self._current_thickness = value
        self._engine.set_thickness(value)
    
    def _set_mosaic_size(self, value: int):
        self._mosaic_size = value
        self._engine.set_mosaic_size(value)
    
    def _toggle_toolbar(self):
        self._toolbar_visible = not self._toolbar_visible
        self._toolbar.setVisible(self._toolbar_visible)
    
    def show_overlay(self):
        self.showFullScreen()
        self._drawing = False
    
    def hide_overlay(self):
        self.hide()
        self._drawing = False
        self._current_tool = None
        self._engine.cancel_current()
        self._btn_arrow.setChecked(False)
        self._btn_rect.setChecked(False)
        self._btn_line.setChecked(False)
        self._btn_text.setChecked(False)
        self._btn_mosaic.setChecked(False)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._current_tool:
            self._drawing = True
            x, y = event.x(), event.y()
            self._start_point = QPoint(x, y)
            self._end_point = QPoint(x, y)
            self._points = [QPoint(x, y)]
            
            self._engine.set_color(self._current_color)
            self._engine.set_thickness(self._current_thickness)
            self._engine.set_mosaic_size(self._mosaic_size)
            self._engine.start_annotation(self._current_tool, (x, y))
            self.annotation_started.emit()
            self.update()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drawing and self._current_tool:
            x, y = event.x(), event.y()
            self._end_point = QPoint(x, y)
            self._points.append(QPoint(x, y))
            self._engine.update_annotation((x, y))
            self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._drawing:
            self._drawing = False
            
            text = ""
            if self._current_tool == AnnotationType.TEXT:
                text, ok = QInputDialog.getText(self, "输入文字", "请输入标注文字：")
                if not ok:
                    self._engine.cancel_current()
                    self.update()
                    return
            
            self._engine.finish_annotation(text)
            self.annotation_finished.emit()
            self.update()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_F2:
            self._toggle_toolbar()
        elif event.key() == Qt.Key_A:
            self._select_tool(AnnotationType.ARROW)
        elif event.key() == Qt.Key_R:
            self._select_tool(AnnotationType.RECTANGLE)
        elif event.key() == Qt.Key_T:
            self._select_tool(AnnotationType.TEXT)
        elif event.key() == Qt.Key_M:
            self._select_tool(AnnotationType.MOSAIC)
        elif event.key() == Qt.Key_P:
            self._select_tool(AnnotationType.LINE)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            self._engine.undo()
        elif event.key() == Qt.Key_Escape:
            self._engine.cancel_current()
            self._drawing = False
            self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for ann in self._engine.get_annotations():
            self._draw_annotation(painter, ann)
        
        current = self._engine.get_current_annotation()
        if current:
            self._draw_annotation(painter, current)
    
    def _draw_annotation(self, painter: QPainter, ann):
        r, g, b = ann.color
        color = QColor(r, g, b, int(255 * ann.opacity))
        pen = QPen(color, ann.thickness)
        painter.setPen(pen)
        
        if ann.type == AnnotationType.ARROW and ann.start_point and ann.end_point:
            self._draw_arrow(painter, QPoint(*ann.start_point), QPoint(*ann.end_point), color, ann.thickness)
        
        elif ann.type == AnnotationType.RECTANGLE and ann.start_point and ann.end_point:
            rect = QRect(QPoint(*ann.start_point), QPoint(*ann.end_point)).normalized()
            if ann.fill:
                painter.setBrush(QBrush(color))
            else:
                painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
        
        elif ann.type == AnnotationType.LINE and len(ann.points) >= 2:
            path = QPainterPath()
            path.moveTo(QPoint(*ann.points[0]))
            for p in ann.points[1:]:
                path.lineTo(QPoint(*p))
            painter.drawPath(path)
        
        elif ann.type == AnnotationType.ELLIPSE and ann.start_point and ann.end_point:
            rect = QRect(QPoint(*ann.start_point), QPoint(*ann.end_point)).normalized()
            if ann.fill:
                painter.setBrush(QBrush(color))
            else:
                painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)
        
        elif ann.type == AnnotationType.TEXT and ann.start_point and ann.text:
            font = QFont()
            font.setPointSizeF(14 * ann.font_scale)
            painter.setFont(font)
            painter.setPen(pen)
            painter.drawText(QPoint(*ann.start_point), ann.text)
        
        elif ann.type == AnnotationType.MOSAIC and ann.start_point and ann.end_point:
            rect = QRect(QPoint(*ann.start_point), QPoint(*ann.end_point)).normalized()
            painter.setBrush(QBrush(QColor(100, 100, 100, 150)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(rect)
            painter.setPen(QPen(QColor(200, 50, 50), 2, Qt.DashLine))
            painter.drawRect(rect)
    
    def _draw_arrow(self, painter: QPainter, start: QPoint, end: QPoint, color: QColor, thickness: int):
        pen = QPen(color, thickness)
        painter.setPen(pen)
        painter.drawLine(start, end)
        
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx == 0 and dy == 0:
            return
        
        import math
        angle = math.atan2(dy, dx)
        arrow_size = max(15, thickness * 4)
        
        p1 = QPoint(
            int(end.x() - arrow_size * math.cos(angle - math.pi / 6)),
            int(end.y() - arrow_size * math.sin(angle - math.pi / 6))
        )
        p2 = QPoint(
            int(end.x() - arrow_size * math.cos(angle + math.pi / 6)),
            int(end.y() - arrow_size * math.sin(angle + math.pi / 6))
        )
        
        painter.setBrush(QBrush(color))
        path = QPainterPath()
        path.moveTo(end)
        path.lineTo(p1)
        path.lineTo(p2)
        path.closeSubpath()
        painter.drawPath(path)
