"""Interactive PySide6 PDF page canvas with zoom, shapes, fill, custom polygons, and text boxes."""

from __future__ import annotations

import math

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
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
    """Displays a rendered PDF page and captures interactive drawing, polygon, text box, and crop edits."""

    annotation_created = Signal(object)  # AnnotationItem
    crop_selected = Signal(object)  # RectNorm
    zoom_requested = Signal(float)  # delta factor
    status_hint = Signal(str)  # localized status message

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._edits: PageEdits = PageEdits()
        self._tool: ToolKind = ToolKind.PAN
        self._color: str = "#D1242F"
        self._filled: bool = False
        self._fill_color: str = "#FEE2E2"
        self._stroke_width: float = 3.0
        self._font_family: str = "Segoe UI"
        self._font_size: float = 16.0
        self._bold: bool = False
        self._italic: bool = False
        self._underline: bool = False
        self._zoom: float = 1.0

        self._dragging: bool = False
        self._start_norm: tuple[float, float] | None = None
        self._curr_norm: tuple[float, float] | None = None
        self._poly_points: list[tuple[float, float]] = []
        self._hover_norm: tuple[float, float] | None = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(100, 100)

    def set_page_image(self, pil_img: Image.Image, edits: PageEdits, zoom: float) -> None:
        self._pixmap = pil_to_qpixmap(pil_img)
        self._edits = edits
        self._zoom = zoom
        self._poly_points.clear()
        self.setFixedSize(self._pixmap.size())
        self.update()

    def clear_page(self) -> None:
        self._pixmap = None
        self._edits = PageEdits()
        self._poly_points.clear()
        self.update()

    def set_edits(self, edits: PageEdits) -> None:
        self._edits = edits
        self.update()

    def set_tool(self, tool: ToolKind) -> None:
        if tool != self._tool:
            self._poly_points.clear()
            self._dragging = False
        self._tool = tool
        if tool == ToolKind.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color

    def set_filled(self, filled: bool) -> None:
        self._filled = filled

    def set_fill_color(self, hex_color: str) -> None:
        self._fill_color = hex_color

    def set_stroke_width(self, width: float) -> None:
        self._stroke_width = max(1.0, float(width))

    def set_font_family(self, family: str) -> None:
        self._font_family = family

    def set_font_size(self, size: float) -> None:
        self._font_size = max(8.0, float(size))

    def set_bold(self, bold: bool) -> None:
        self._bold = bold

    def set_italic(self, italic: bool) -> None:
        self._italic = italic

    def set_underline(self, underline: bool) -> None:
        self._underline = underline

    def _to_norm(self, pos: QPointF) -> tuple[float, float]:
        w = max(1, self.width())
        h = max(1, self.height())
        nx = max(0.0, min(1.0, pos.x() / w))
        ny = max(0.0, min(1.0, pos.y() / h))
        return nx, ny

    def _finish_polygon(self) -> None:
        if len(self._poly_points) >= 3:
            item = AnnotationItem(
                kind="polygon",
                points=tuple(self._poly_points),
                color=self._color,
                filled=self._filled,
                fill_color=self._fill_color,
                stroke_width=self._stroke_width,
            )
            self._poly_points.clear()
            self.annotation_created.emit(item)
        else:
            self._poly_points.clear()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._tool == ToolKind.POLYGON and self._poly_points:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish_polygon()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._poly_points.clear()
                self.update()
                event.accept()
                return
        super().keyPressEvent(event)

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

    def mouseDoubleClickEvent(self, event) -> None:
        if self._tool == ToolKind.POLYGON and len(self._poly_points) >= 3:
            self._finish_polygon()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._pixmap is None:
            return super().mousePressEvent(event)

        self.setFocus()

        # Right-click finishes an in-progress custom polygon
        if event.button() == Qt.MouseButton.RightButton and self._tool == ToolKind.POLYGON:
            if len(self._poly_points) >= 3:
                self._finish_polygon()
            else:
                self._poly_points.clear()
                self.update()
            return

        if event.button() != Qt.MouseButton.LeftButton or self._tool == ToolKind.PAN:
            return super().mousePressEvent(event)

        nx, ny = self._to_norm(event.position())

        if self._tool == ToolKind.POLYGON:
            # Clicking close to the starting point closes the polygon when >= 3 points exist
            if len(self._poly_points) >= 3:
                fx, fy = self._poly_points[0]
                dist_px = math.hypot((nx - fx) * self.width(), (ny - fy) * self.height())
                if dist_px <= 12.0:
                    self._finish_polygon()
                    return
            self._poly_points.append((nx, ny))
            self.status_hint.emit(t("status.polygon_drawing", count=len(self._poly_points)))
            self.update()
            return

        # All other tools (including TEXT box, CROP, shapes, redactions) start a drag
        self._dragging = True
        self._start_norm = (nx, ny)
        self._curr_norm = (nx, ny)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._pixmap is None:
            return super().mouseMoveEvent(event)
        pos = self._to_norm(event.position())
        self._hover_norm = pos
        if self._dragging:
            self._curr_norm = pos
            self.update()
            return
        if self._tool == ToolKind.POLYGON and self._poly_points:
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
        if math.hypot((x1 - x0) * self.width(), (y1 - y0) * self.height()) < 6.0:
            self.update()
            return

        if self._tool == ToolKind.CROP:
            rect = RectNorm(x0, y0, x1, y1).normalized()
            if rect.width >= 0.03 and rect.height >= 0.03:
                self.crop_selected.emit(rect)
        elif self._tool == ToolKind.TEXT:
            rect = RectNorm(x0, y0, x1, y1).normalized()
            text, ok = QInputDialog.getMultiLineText(
                self,
                t("dialog.text_input.title"),
                t("dialog.text_input.prompt"),
            )
            if ok and text.strip():
                item = AnnotationItem(
                    kind="text",
                    x0=rect.x0,
                    y0=rect.y0,
                    x1=rect.x1,
                    y1=rect.y1,
                    color=self._color,
                    font_family=self._font_family,
                    font_size=self._font_size,
                    bold=self._bold,
                    italic=self._italic,
                    underline=self._underline,
                    text=text,
                )
                self.annotation_created.emit(item)
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
                filled=self._filled if self._tool in (ToolKind.RECT, ToolKind.ELLIPSE) else False,
                fill_color=self._fill_color,
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
        pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(item.fill_color)) if item.filled else Qt.BrushStyle.NoBrush)

        if item.kind == "rect":
            r = item.rect()
            painter.drawRect(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
        elif item.kind == "ellipse":
            r = item.rect()
            painter.drawEllipse(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
        elif item.kind == "polygon" and len(item.points) >= 3:
            poly = QPolygonF([QPointF(px * w, py * h) for px, py in item.points])
            painter.drawPolygon(poly)
        elif item.kind == "line":
            painter.drawLine(QPointF(item.x0 * w, item.y0 * h), QPointF(item.x1 * w, item.y1 * h))
        elif item.kind == "arrow":
            self._draw_arrow(painter, item.x0 * w, item.y0 * h, item.x1 * w, item.y1 * h, color, stroke)
        elif item.kind == "text" and item.text:
            r = item.rect()
            box_w = r.width * w if r.width > 0.005 else max(50.0, w - r.x0 * w)
            box_h = r.height * h if r.height > 0.005 else max(50.0, h - r.y0 * h)
            rect_f = QRectF(r.x0 * w, r.y0 * h, box_w, box_h)

            # Subtle dashed guide for text box in editor preview
            painter.save()
            painter.setPen(QPen(QColor(148, 163, 184, 150), 1.0, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect_f)
            painter.restore()

            font = QFont(item.font_family)
            font.setPixelSize(max(10, int(round(item.font_size * self._zoom * 1.45))))
            font.setBold(item.bold)
            font.setItalic(item.italic)
            font.setUnderline(item.underline)
            painter.setFont(font)
            painter.setPen(QPen(color))
            painter.drawText(
                rect_f,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
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

    def _draw_polygon_preview(self, painter: QPainter) -> None:
        if not self._poly_points:
            return
        w = float(self.width())
        h = float(self.height())
        color = QColor(self._color)
        stroke = max(1.0, self._stroke_width * self._zoom)

        pts = [QPointF(px * w, py * h) for px, py in self._poly_points]
        if self._hover_norm is not None:
            pts_with_hover = pts + [QPointF(self._hover_norm[0] * w, self._hover_norm[1] * h)]
        else:
            pts_with_hover = pts

        if self._filled and len(pts_with_hover) >= 3:
            fill_c = QColor(self._fill_color)
            fill_c.setAlpha(140)
            painter.setBrush(QBrush(fill_c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF(pts_with_hover))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, stroke, Qt.PenStyle.DashLine))
        for idx in range(len(pts_with_hover) - 1):
            painter.drawLine(pts_with_hover[idx], pts_with_hover[idx + 1])

        # Draw vertex handles (first vertex highlighted larger so user sees close target)
        for idx, pt in enumerate(pts):
            radius = 5.5 if idx == 0 and len(pts) >= 3 else 3.5
            painter.setBrush(QBrush(QColor("#16A34A") if idx == 0 and len(pts) >= 3 else color))
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            painter.drawEllipse(pt, radius, radius)

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

        # In-progress polygon preview
        if self._tool == ToolKind.POLYGON and self._poly_points:
            self._draw_polygon_preview(painter)

        # Live drag preview
        if self._dragging and self._start_norm is not None and self._curr_norm is not None:
            x0, y0 = self._start_norm
            x1, y1 = self._curr_norm
            if self._tool == ToolKind.CROP:
                self._draw_crop_overlay(painter, RectNorm(x0, y0, x1, y1))
            elif self._tool == ToolKind.TEXT:
                r = RectNorm(x0, y0, x1, y1).normalized()
                painter.setBrush(QBrush(QColor(59, 130, 246, 28)))
                painter.setPen(QPen(QColor(37, 99, 235), 1.8, Qt.PenStyle.DashLine))
                painter.drawRect(
                    QRectF(r.x0 * self.width(), r.y0 * self.height(), r.width * self.width(), r.height * self.height())
                )
            elif self._tool not in (ToolKind.PAN, ToolKind.POLYGON):
                preview = AnnotationItem(
                    kind=self._tool.value,  # type: ignore[arg-type]
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    color=self._color,
                    filled=self._filled if self._tool in (ToolKind.RECT, ToolKind.ELLIPSE) else False,
                    fill_color=self._fill_color,
                    stroke_width=self._stroke_width,
                )
                self._draw_annotation(painter, preview)
