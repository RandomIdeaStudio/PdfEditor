"""Interactive PySide6 PDF page canvas with zoom, drawing, crop, and redaction preview."""

from __future__ import annotations

import math

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QInputDialog, QWidget

from ..core.i18n import t
from ..core.models import AnnotationItem, PageEdits, RectNorm, ToolKind


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class PdfCanvasWidget(QWidget):
    """Displays a single rendered PDF page and captures interactive drawing/crop edits."""

    annotation_created = Signal(object)  # AnnotationItem
    crop_selected = Signal(object)  # RectNorm
    zoom_requested = Signal(float)  # delta factor

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._edits: PageEdits = PageEdits()
        self._tool: ToolKind = ToolKind.PAN
        self._color: str = "#D1242F"
        self._stroke_width: float = 3.0
        self._font_size: float = 16.0
        self._zoom: float = 1.0

        self._dragging: bool = False
        self._start_norm: tuple[float, float] | None = None
        self._curr_norm: tuple[float, float] | None = None

        self.setMouseTracking(True)
        self.setMinimumSize(100, 100)

    def set_page_image(self, pil_img: Image.Image, edits: PageEdits, zoom: float) -> None:
        self._pixmap = pil_to_qpixmap(pil_img)
        self._edits = edits
        self._zoom = zoom
        self.setFixedSize(self._pixmap.size())
        self.update()

    def clear_page(self) -> None:
        self._pixmap = None
        self._edits = PageEdits()
        self.update()

    def set_edits(self, edits: PageEdits) -> None:
        self._edits = edits
        self.update()

    def set_tool(self, tool: ToolKind) -> None:
        self._tool = tool
        if tool == ToolKind.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif tool == ToolKind.TEXT:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color

    def set_stroke_width(self, width: float) -> None:
        self._stroke_width = max(1.0, float(width))

    def set_font_size(self, size: float) -> None:
        self._font_size = max(8.0, float(size))

    def _to_norm(self, pos: QPointF) -> tuple[float, float]:
        w = max(1, self.width())
        h = max(1, self.height())
        nx = max(0.0, min(1.0, pos.x() / w))
        ny = max(0.0, min(1.0, pos.y() / h))
        return nx, ny

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_requested.emit(1.15)
            elif delta < 0:
                self.zoom_requested.emit(1.0 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._pixmap is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        if self._tool == ToolKind.PAN:
            return super().mousePressEvent(event)

        nx, ny = self._to_norm(event.position())
        if self._tool == ToolKind.TEXT:
            text, ok = QInputDialog.getMultiLineText(
                self,
                t("dialog.text_input.title"),
                t("dialog.text_input.prompt"),
            )
            if ok and text.strip():
                item = AnnotationItem(
                    kind="text",
                    x0=nx,
                    y0=ny,
                    x1=nx,
                    y1=ny,
                    color=self._color,
                    font_size=self._font_size,
                    text=text,
                )
                self.annotation_created.emit(item)
            return

        self._dragging = True
        self._start_norm = (nx, ny)
        self._curr_norm = (nx, ny)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._pixmap is not None:
            self._curr_norm = self._to_norm(event.position())
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._dragging or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)

        self._dragging = False
        start = self._start_norm
        end = self._to_norm(event.position())
        self._start_norm = None
        self._curr_norm = None

        if start is None:
            self.update()
            return

        x0, y0 = start
        x1, y1 = end
        # Ignore accidental micro-clicks
        if math.hypot((x1 - x0) * self.width(), (y1 - y0) * self.height()) < 6.0:
            self.update()
            return

        if self._tool == ToolKind.CROP:
            rect = RectNorm(x0, y0, x1, y1).normalized()
            if rect.width >= 0.03 and rect.height >= 0.03:
                self.crop_selected.emit(rect)
        elif self._tool in (
            ToolKind.RECT,
            ToolKind.ELLIPSE,
            ToolKind.LINE,
            ToolKind.ARROW,
            ToolKind.HIGHLIGHT,
            ToolKind.REDACT_BLACK,
            ToolKind.REDACT_WHITE,
        ):
            item = AnnotationItem(
                kind=self._tool.value,  # type: ignore[arg-type]
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                color=self._color,
                stroke_width=self._stroke_width,
            )
            self.annotation_created.emit(item)
        self.update()

    def _draw_arrow(
        self,
        painter: QPainter,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: QColor,
        stroke: float,
    ) -> None:
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return
        head_len = max(12.0, stroke * 4.5)
        head_w = max(8.0, stroke * 3.2)
        ux, uy = dx / length, dy / length
        bx = x1 - ux * head_len
        by = y1 - uy * head_len
        px, py = -uy * (head_w / 2.0), ux * (head_w / 2.0)

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        poly = QPolygonF(
            [QPointF(x1, y1), QPointF(bx + px, by + py), QPointF(bx - px, by - py)]
        )
        painter.drawPolygon(poly)

    def _draw_annotation(self, painter: QPainter, item: AnnotationItem) -> None:
        w = float(self.width())
        h = float(self.height())
        stroke = max(1.0, item.stroke_width * self._zoom)

        if item.kind == "highlight":
            r = item.rect()
            color = QColor(item.color)
            color.setAlpha(95)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
            return

        if item.kind == "redact_black":
            r = item.rect()
            rect_f = QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h)
            painter.setBrush(QBrush(QColor(0, 0, 0, 245)))
            painter.setPen(QPen(QColor(220, 38, 38), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(rect_f)
            return

        if item.kind == "redact_white":
            r = item.rect()
            rect_f = QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h)
            painter.setBrush(QBrush(QColor(255, 255, 255, 245)))
            painter.setPen(QPen(QColor(37, 99, 235), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(rect_f)
            return

        color = QColor(item.color)
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if item.kind == "rect":
            r = item.rect()
            painter.drawRect(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
        elif item.kind == "ellipse":
            r = item.rect()
            painter.drawEllipse(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
        elif item.kind == "line":
            painter.drawLine(QPointF(item.x0 * w, item.y0 * h), QPointF(item.x1 * w, item.y1 * h))
        elif item.kind == "arrow":
            self._draw_arrow(painter, item.x0 * w, item.y0 * h, item.x1 * w, item.y1 * h, color, stroke)
        elif item.kind == "text" and item.text:
            font = QFont("Segoe UI")
            font.setPixelSize(max(10, int(round(item.font_size * self._zoom * 1.45))))
            painter.setFont(font)
            painter.drawText(
                QRectF(item.x0 * w, item.y0 * h, max(50.0, w - item.x0 * w), max(50.0, h - item.y0 * h)),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                item.text,
            )

    def _draw_crop_overlay(self, painter: QPainter, crop: RectNorm) -> None:
        w = float(self.width())
        h = float(self.height())
        c = crop.normalized()
        left, top, right, bottom = c.x0 * w, c.y0 * h, c.x1 * w, c.y1 * h

        shade = QColor(0, 0, 0, 110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(shade))
        painter.drawRect(QRectF(0, 0, w, top))
        painter.drawRect(QRectF(0, bottom, w, h - bottom))
        painter.drawRect(QRectF(0, top, left, bottom - top))
        painter.drawRect(QRectF(right, top, w - right, bottom - top))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(22, 163, 74), 2.0, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(left, top, right - left, bottom - top))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if self._pixmap is None:
            return

        painter.drawPixmap(0, 0, self._pixmap)

        for item in self._edits.annotations:
            self._draw_annotation(painter, item)

        if self._edits.crop is not None:
            self._draw_crop_overlay(painter, self._edits.crop)

        # Live drag preview
        if self._dragging and self._start_norm is not None and self._curr_norm is not None:
            x0, y0 = self._start_norm
            x1, y1 = self._curr_norm
            if self._tool == ToolKind.CROP:
                self._draw_crop_overlay(painter, RectNorm(x0, y0, x1, y1))
            elif self._tool not in (ToolKind.PAN, ToolKind.TEXT):
                preview = AnnotationItem(
                    kind=self._tool.value,  # type: ignore[arg-type]
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    color=self._color,
                    stroke_width=self._stroke_width,
                )
                self._draw_annotation(painter, preview)
