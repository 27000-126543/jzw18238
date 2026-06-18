import numpy as np
import cv2
from typing import List, Tuple, Optional, Dict, Any
from PyQt5.QtCore import QObject, pyqtSignal
from enum import Enum


class AnnotationType(Enum):
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    TEXT = "text"
    MOSAIC = "mosaic"
    LINE = "line"
    ELLIPSE = "ellipse"


class Annotation:
    def __init__(self, annotation_type: AnnotationType):
        self.type = annotation_type
        self.color: Tuple[int, int, int] = (0, 255, 0)
        self.thickness: int = 3
        self.start_point: Optional[Tuple[int, int]] = None
        self.end_point: Optional[Tuple[int, int]] = None
        self.text: str = ""
        self.font_scale: float = 0.8
        self.mosaic_size: int = 15
        self.fill: bool = False
        self.opacity: float = 1.0
        self.points: List[Tuple[int, int]] = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type.value,
            'color': self.color,
            'thickness': self.thickness,
            'start_point': self.start_point,
            'end_point': self.end_point,
            'text': self.text,
            'font_scale': self.font_scale,
            'mosaic_size': self.mosaic_size,
            'fill': self.fill,
            'opacity': self.opacity,
            'points': self.points
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Annotation':
        ann = cls(AnnotationType(data['type']))
        ann.color = tuple(data['color'])
        ann.thickness = data['thickness']
        ann.start_point = tuple(data['start_point']) if data['start_point'] else None
        ann.end_point = tuple(data['end_point']) if data['end_point'] else None
        ann.text = data['text']
        ann.font_scale = data['font_scale']
        ann.mosaic_size = data['mosaic_size']
        ann.fill = data['fill']
        ann.opacity = data['opacity']
        ann.points = [tuple(p) for p in data['points']]
        return ann


class AnnotationEngine(QObject):
    annotations_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._annotations: List[Annotation] = []
        self._current_annotation: Optional[Annotation] = None
        self._active = False
    
    def set_active(self, active: bool):
        self._active = active
    
    def is_active(self) -> bool:
        return self._active
    
    def start_annotation(self, annotation_type: AnnotationType, point: Tuple[int, int]):
        self._current_annotation = Annotation(annotation_type)
        self._current_annotation.start_point = point
        self._current_annotation.end_point = point
        self._current_annotation.points = [point]
        self.annotations_changed.emit()
    
    def update_annotation(self, point: Tuple[int, int]):
        if self._current_annotation:
            self._current_annotation.end_point = point
            self._current_annotation.points.append(point)
            self.annotations_changed.emit()
    
    def finish_annotation(self, text: str = "") -> Optional[Annotation]:
        if self._current_annotation:
            if self._current_annotation.type == AnnotationType.TEXT:
                self._current_annotation.text = text
            self._annotations.append(self._current_annotation)
            completed = self._current_annotation
            self._current_annotation = None
            self.annotations_changed.emit()
            return completed
        return None
    
    def cancel_current(self):
        self._current_annotation = None
        self.annotations_changed.emit()
    
    def get_annotations(self) -> List[Annotation]:
        return self._annotations.copy()
    
    def get_current_annotation(self) -> Optional[Annotation]:
        return self._current_annotation
    
    def undo(self):
        if self._annotations:
            self._annotations.pop()
            self.annotations_changed.emit()
    
    def clear(self):
        self._annotations.clear()
        self._current_annotation = None
        self.annotations_changed.emit()
    
    def set_color(self, color: Tuple[int, int, int]):
        if self._current_annotation:
            self._current_annotation.color = color
    
    def set_thickness(self, thickness: int):
        if self._current_annotation:
            self._current_annotation.thickness = max(1, thickness)
    
    def set_text(self, text: str):
        if self._current_annotation and self._current_annotation.type == AnnotationType.TEXT:
            self._current_annotation.text = text
    
    def set_mosaic_size(self, size: int):
        if self._current_annotation:
            self._current_annotation.mosaic_size = max(5, size)
    
    def render_on_frame(self, frame: np.ndarray) -> np.ndarray:
        if not self._active and not self._current_annotation and len(self._annotations) == 0:
            return frame
        
        output = frame.copy()
        
        all_annotations = self._annotations.copy()
        if self._current_annotation:
            all_annotations.append(self._current_annotation)
        
        for ann in all_annotations:
            if ann.opacity < 1.0:
                overlay = output.copy()
                self._draw_annotation(overlay, ann)
                cv2.addWeighted(overlay, ann.opacity, output, 1 - ann.opacity, 0, output)
            else:
                self._draw_annotation(output, ann)
        
        return output
    
    def _draw_annotation(self, img: np.ndarray, ann: Annotation):
        color_bgr = (ann.color[2], ann.color[1], ann.color[0])
        
        if ann.type == AnnotationType.ARROW:
            if ann.start_point and ann.end_point:
                cv2.arrowedLine(img, ann.start_point, ann.end_point, color_bgr, ann.thickness, tipLength=0.2)
        
        elif ann.type == AnnotationType.RECTANGLE:
            if ann.start_point and ann.end_point:
                thickness = -1 if ann.fill else ann.thickness
                cv2.rectangle(img, ann.start_point, ann.end_point, color_bgr, thickness)
        
        elif ann.type == AnnotationType.LINE:
            if len(ann.points) >= 2:
                for i in range(len(ann.points) - 1):
                    cv2.line(img, ann.points[i], ann.points[i + 1], color_bgr, ann.thickness)
        
        elif ann.type == AnnotationType.ELLIPSE:
            if ann.start_point and ann.end_point:
                x1, y1 = ann.start_point
                x2, y2 = ann.end_point
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                ax = abs(x2 - x1) // 2
                ay = abs(y2 - y1) // 2
                thickness = -1 if ann.fill else ann.thickness
                cv2.ellipse(img, (cx, cy), (ax, ay), 0, 0, 360, color_bgr, thickness)
        
        elif ann.type == AnnotationType.TEXT:
            if ann.start_point and ann.text:
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(img, ann.text, ann.start_point, font, ann.font_scale, color_bgr, ann.thickness, cv2.LINE_AA)
        
        elif ann.type == AnnotationType.MOSAIC:
            if ann.start_point and ann.end_point:
                x1, y1 = ann.start_point
                x2, y2 = ann.end_point
                x_min, x_max = min(x1, x2), max(x1, x2)
                y_min, y_max = min(y1, y2), max(y1, y2)
                
                h, w = img.shape[:2]
                x_min, x_max = max(0, x_min), min(w, x_max)
                y_min, y_max = max(0, y_min), min(h, y_max)
                
                if x_max > x_min and y_max > y_min:
                    roi = img[y_min:y_max, x_min:x_max]
                    mh, mw = roi.shape[:2]
                    size = ann.mosaic_size
                    
                    small = cv2.resize(roi, (max(1, mw // size), max(1, mh // size)), interpolation=cv2.INTER_LINEAR)
                    mosaic = cv2.resize(small, (mw, mh), interpolation=cv2.INTER_NEAREST)
                    img[y_min:y_max, x_min:x_max] = mosaic
