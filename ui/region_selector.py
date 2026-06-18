from PyQt5.QtWidgets import QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QMouseEvent, QPixmap, QGuiApplication
from typing import Optional, Tuple


class RegionSelector(QWidget):
    region_selected = pyqtSignal(int, int, int, int)
    selection_cancelled = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._start_point: Optional[QPoint] = None
        self._end_point: Optional[QPoint] = None
        self._selecting = False
        self._selected_region: Optional[QRect] = None
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        
        screen = self._get_fullscreen_geometry()
        self.setGeometry(screen)
        
        self._init_ui()
    
    def _get_fullscreen_geometry(self) -> QRect:
        screens = QGuiApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        
        virtual_geometry = QRect()
        for screen in screens:
            virtual_geometry = virtual_geometry.united(screen.geometry())
        return virtual_geometry
    
    def _init_ui(self):
        self._info_label = QLabel("按住鼠标左键拖拽选择录制区域\n按 Enter 确认 | 按 Esc 取消", self)
        self._info_label.setStyleSheet("""
            background-color: rgba(50, 50, 50, 220);
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 14px;
        """)
        self._info_label.setAlignment(Qt.AlignCenter)
        self._info_label.adjustSize()
        
        screen_geo = self.geometry()
        self._info_label.move(
            (screen_geo.width() - self._info_label.width()) // 2,
            screen_geo.top() + 30
        )
    
    def show_selector(self):
        self._start_point = None
        self._end_point = None
        self._selecting = False
        self._selected_region = None
        self.showFullScreen()
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._selecting = True
            self._start_point = event.pos()
            self._end_point = event.pos()
            self.update()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._selecting:
            self._end_point = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            if self._start_point and self._end_point:
                region = QRect(self._start_point, self._end_point).normalized()
                if region.width() >= 10 and region.height() >= 10:
                    self._selected_region = region
                    self.update()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self._selected_region:
                self._confirm_selection()
        elif event.key() == Qt.Key_Escape:
            self.hide()
            self.selection_cancelled.emit()
    
    def _confirm_selection(self):
        if self._selected_region:
            geo = self._selected_region
            self.hide()
            self.region_selected.emit(geo.x(), geo.y(), geo.width(), geo.height())
    
    def paintEvent(self, event):
        painter = QPainter(self)
        
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        
        if self._start_point and self._end_point:
            region = QRect(self._start_point, self._end_point).normalized()
            
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(region, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            
            pen = QPen(QColor(0, 120, 215), 3)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(region)
            
            if region.width() >= 50 and region.height() >= 50:
                size_text = f"{region.width()} × {region.height()}"
                font = painter.font()
                font.setBold(True)
                font.setPointSize(12)
                painter.setFont(font)
                
                text_rect = painter.fontMetrics().boundingRect(size_text)
                text_bg = QRect(
                    region.center().x() - text_rect.width() // 2 - 10,
                    region.bottom() + 5,
                    text_rect.width() + 20,
                    text_rect.height() + 10
                )
                if text_bg.bottom() > self.rect().bottom() - 10:
                    text_bg.moveBottom(region.top() - 5)
                
                painter.fillRect(text_bg, QColor(0, 120, 215, 220))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(text_bg, Qt.AlignCenter, size_text)
