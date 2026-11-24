"""Interactive PySide6 PDF page canvas: pan, select/move/delete, freehand pen, shapes, polygons, images, text, crop, redaction."""

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
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from ..core.i18n import t
from ..core.models import AnnotationItem, PageEdits, RectNorm, ToolKind


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class PdfCanvasWidget(QWidget):
    """Displays a rendered PDF page and captures interactive drawing, selection, pan, and crop edits."""

    annotation_created = Signal(object)  # AnnotationItem
    annotation_moved = Signal(int, float, float)  # index, dx_norm, dy_norm
    annotation_deleted = Signal(int)  # index
    crop_selected = Signal(object)  # RectNorm
    zoom_requested = Signal(float)  # delta factor
    pan_requested = Signal(int, int)  # dx, dy scroll deltas in pixels
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
        self._panning: bool = False
        self._last_pan_global: QPointF | None = None
        self._start_norm: tuple[float, float] | None = None
        self._curr_norm: tuple[float, float] | None = None
        self._poly_points: list[tuple[float, float]] = []
        self._freehand_points: list[tuple[float, float]] = []
        self._hover_norm: tuple[float, float] | None = None

        self._selected_index: int | None = None
        self._moving_selected: bool = False
        self._move_origin_norm: tuple[float, float] | None = None
        self._move_delta_norm: tuple[float, float] = (0.0, 0.0)
        self._image_cache: dict[str, QPixmap] = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(100, 100)

    def set_page_image(self, pil_img: Image.Image, edits: PageEdits, zoom: float) -> None:
        self._pixmap = pil_to_qpixmap(pil_img)
        self._edits = edits
        self._zoom = zoom
        self._poly_points.clear()
        self._freehand_points.clear()
        self._selected_index = None
        self.setFixedSize(self._pixmap.size())
        self.update()

    def clear_page(self) -> None:
        self._pixmap = None
        self._edits = PageEdits()
        self._poly_points.clear()
        self._freehand_points.clear()
        self._selected_index = None
        self.update()

    def set_edits(self, edits: PageEdits) -> None:
        self._edits = edits
        if self._selected_index is not None and self._selected_index >= len(edits.annotations):
            self._selected_index = None
        self.update()

    def set_tool(self, tool: ToolKind) -> None:
        if tool != self._tool:
            self._poly_points.clear()
            self._freehand_points.clear()
            self._dragging = False
            self._moving_selected = False
            if tool != ToolKind.SELECT:
                self._selected_index = None
        self._tool = tool
        if tool == ToolKind.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif tool == ToolKind.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
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

    def _get_cached_image(self, path: str) -> QPixmap | None:
        if not path:
            return None
        if path not in self._image_cache:
            pix = QPixmap(path)
            if not pix.isNull():
                self._image_cache[path] = pix
        return self._image_cache.get(path)

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
        if self._tool == ToolKind.SELECT and self._selected_index is not None:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                idx = self._selected_index
                self._selected_index = None
                self.annotation_deleted.emit(idx)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._selected_index = None
                self.update()
                event.accept()
                return

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

        if event.button() == Qt.MouseButton.RightButton and self._tool == ToolKind.POLYGON:
            if len(self._poly_points) >= 3:
                self._finish_polygon()
            else:
                self._poly_points.clear()
                self.update()
            return

        # Drag-to-pan: left button in PAN mode, or middle button in any tool
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._tool == ToolKind.PAN
        ):
            self._panning = True
            self._last_pan_global = event.globalPosition()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        nx, ny = self._to_norm(event.position())

        # Select / move existing annotation
        if self._tool == ToolKind.SELECT:
            hit_idx: int | None = None
            for idx in range(len(self._edits.annotations) - 1, -1, -1):
                if self._edits.annotations[idx].hit_test(nx, ny):
                    hit_idx = idx
                    break
            self._selected_index = hit_idx
            if hit_idx is not None:
                self._moving_selected = True
                self._move_origin_norm = (nx, ny)
                self._move_delta_norm = (0.0, 0.0)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.update()
            return

        if self._tool == ToolKind.POLYGON:
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

        if self._tool == ToolKind.FREEHAND:
            self._freehand_points = [(nx, ny)]
            self._dragging = True
            self.update()
            return

        self._dragging = True
        self._start_norm = (nx, ny)
        self._curr_norm = (nx, ny)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._pixmap is None:
            return super().mouseMoveEvent(event)

        if self._panning and self._last_pan_global is not None:
            curr_global = event.globalPosition()
            dx = int(round(curr_global.x() - self._last_pan_global.x()))
            dy = int(round(curr_global.y() - self._last_pan_global.y()))
            self._last_pan_global = curr_global
            if dx != 0 or dy != 0:
                self.pan_requested.emit(dx, dy)
            event.accept()
            return

        pos = self._to_norm(event.position())
        self._hover_norm = pos

        if self._moving_selected and self._move_origin_norm is not None:
            self._move_delta_norm = (
                pos[0] - self._move_origin_norm[0],
                pos[1] - self._move_origin_norm[1],
            )
            self.update()
            return

        if self._dragging:
            if self._tool == ToolKind.FREEHAND:
                last = self._freehand_points[-1]
                if math.hypot((pos[0] - last[0]) * self.width(), (pos[1] - last[1]) * self.height()) >= 2.5:
                    self._freehand_points.append(pos)
            else:
                self._curr_norm = pos
            self.update()
            return

        if self._tool == ToolKind.POLYGON and self._poly_points:
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._panning = False
            self._last_pan_global = None
            if self._tool == ToolKind.PAN:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._tool == ToolKind.SELECT:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        if self._moving_selected and event.button() == Qt.MouseButton.LeftButton:
            self._moving_selected = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            dx, dy = self._move_delta_norm
            self._move_delta_norm = (0.0, 0.0)
            self._move_origin_norm = None
            if (
                self._selected_index is not None
                and math.hypot(dx * self.width(), dy * self.height()) >= 2.0
            ):
                self.annotation_moved.emit(self._selected_index, dx, dy)
            self.update()
            return

        if not self._dragging or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)

        self._dragging = False
        if self._tool == ToolKind.FREEHAND:
            pts = tuple(self._freehand_points)
            self._freehand_points.clear()
            if len(pts) >= 2:
                item = AnnotationItem(
                    kind="freehand",
                    points=pts,
                    color=self._color,
                    stroke_width=self._stroke_width,
                )
                self.annotation_created.emit(item)
            self.update()
            return

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
        elif self._tool == ToolKind.IMAGE:
            rect = RectNorm(x0, y0, x1, y1).normalized()
            selected, _ = QFileDialog.getOpenFileName(
                self,
                t("dialog.insert_image.title"),
                "",
                t("dialog.insert_image.filter"),
            )
            if selected:
                item = AnnotationItem(
                    kind="image",
                    x0=rect.x0,
                    y0=rect.y0,
                    x1=rect.x1,
                    y1=rect.y1,
                    image_path=selected,
                )
                self.annotation_created.emit(item)
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

    # ------------------------------------------------------------------ Painting

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

    def _draw_freehand_points(
        self,
        painter: QPainter,
        points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
        hex_color: str,
        stroke_width: float,
    ) -> None:
        if len(points) < 2:
            return
        w = float(self.width())
        h = float(self.height())
        path = QPainterPath(QPointF(points[0][0] * w, points[0][1] * h))
        for px, py in points[1:]:
            path.lineTo(QPointF(px * w, py * h))
        pen = QPen(
            QColor(hex_color),
            max(1.0, stroke_width * self._zoom),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

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
            painter.setBrush(QBrush(QColor(0, 0, 0, 245)))
            painter.setPen(QPen(QColor(220, 38, 38), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
            return

        if item.kind == "redact_white":
            r = item.rect()
            painter.setBrush(QBrush(QColor(255, 255, 255, 245)))
            painter.setPen(QPen(QColor(37, 99, 235), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h))
            return

        if item.kind == "image":
            r = item.rect()
            rect_f = QRectF(r.x0 * w, r.y0 * h, r.width * w, r.height * h)
            pix = self._get_cached_image(item.image_path)
            if pix is not None:
                painter.drawPixmap(rect_f.toRect(), pix)
            return

        if item.kind == "freehand":
            self._draw_freehand_points(painter, item.points, item.color, item.stroke_width)
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
        pts_with_hover = (
            pts + [QPointF(self._hover_norm[0] * w, self._hover_norm[1] * h)]
            if self._hover_norm is not None
            else pts
        )

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

        for idx, item in enumerate(self._edits.annotations):
            drawn_item = item
            if idx == self._selected_index and self._moving_selected:
                drawn_item = item.translated(self._move_delta_norm[0], self._move_delta_norm[1])
            self._draw_annotation(painter, drawn_item)

            if idx == self._selected_index:
                b = drawn_item.bounding_rect()
                sel_rect = QRectF(
                    b.x0 * self.width() - 4,
                    b.y0 * self.height() - 4,
                    b.width * self.width() + 8,
                    b.height * self.height() + 8,
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(37, 99, 235), 2.0, Qt.PenStyle.DashLine))
                painter.drawRect(sel_rect)

        if self._edits.crop is not None:
            self._draw_crop_overlay(painter, self._edits.crop)

        if self._tool == ToolKind.POLYGON and self._poly_points:
            self._draw_polygon_preview(painter)

        if self._tool == ToolKind.FREEHAND and self._freehand_points:
            self._draw_freehand_points(painter, self._freehand_points, self._color, self._stroke_width)

        if self._dragging and self._start_norm is not None and self._curr_norm is not None:
            x0, y0 = self._start_norm
            x1, y1 = self._curr_norm
            if self._tool == ToolKind.CROP:
                self._draw_crop_overlay(painter, RectNorm(x0, y0, x1, y1))
            elif self._tool in (ToolKind.TEXT, ToolKind.IMAGE):
                r = RectNorm(x0, y0, x1, y1).normalized()
                painter.setBrush(QBrush(QColor(59, 130, 246, 28)))
                painter.setPen(QPen(QColor(37, 99, 235), 1.8, Qt.PenStyle.DashLine))
                painter.drawRect(
                    QRectF(
                        r.x0 * self.width(),
                        r.y0 * self.height(),
                        r.width * self.width(),
                        r.height * self.height(),
                    )
                )
            elif self._tool not in (ToolKind.PAN, ToolKind.SELECT, ToolKind.POLYGON, ToolKind.FREEHAND):
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
