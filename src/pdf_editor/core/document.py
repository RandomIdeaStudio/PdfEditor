"""PDF document rendering (pypdfium2), editing/redaction save engine, and page management (pypdf + Pillow)."""

from __future__ import annotations

import io
import math
import os
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from .i18n import t
from .models import AnnotationItem, DocumentEditSession, PageEdits, RectNorm

BAKE_DPI = 250.0

_FONT_FILES: dict[str, tuple[str, str, str, str]] = {
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
}


def parse_page_range(spec: str, total_pages: int) -> list[int]:
    """Parse 1-based page specification like '1-3, 5' into sorted 0-based page indices."""
    indices: list[int] = []
    seen: set[int] = set()
    cleaned = spec.strip()
    if not cleaned:
        raise ValueError(t("error.invalid_page_range", spec=spec, total=total_pages))

    for part in cleaned.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            bounds = token.split("-", 1)
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
            except ValueError as exc:
                raise ValueError(
                    t("error.invalid_page_range", spec=spec, total=total_pages)
                ) from exc
            if start < 1 or end > total_pages or start > end:
                raise ValueError(t("error.invalid_page_range", spec=spec, total=total_pages))
            for num in range(start, end + 1):
                idx = num - 1
                if idx not in seen:
                    seen.add(idx)
                    indices.append(idx)
        else:
            try:
                num = int(token)
            except ValueError as exc:
                raise ValueError(
                    t("error.invalid_page_range", spec=spec, total=total_pages)
                ) from exc
            if num < 1 or num > total_pages:
                raise ValueError(t("error.invalid_page_range", spec=spec, total=total_pages))
            idx = num - 1
            if idx not in seen:
                seen.add(idx)
                indices.append(idx)

    if not indices:
        raise ValueError(t("error.invalid_page_range", spec=spec, total=total_pages))
    return indices


def _load_unicode_font(
    pixel_size: int,
    family: str = "Segoe UI",
    bold: bool = False,
    italic: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(10, int(round(pixel_size)))
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

    style_idx = (1 if bold else 0) + (2 if italic else 0)
    candidates: list[str] = []
    if family in _FONT_FILES:
        files = _FONT_FILES[family]
        candidates.append(files[style_idx])
        candidates.append(files[0])
    for fallback_files in (_FONT_FILES["Segoe UI"], _FONT_FILES["Arial"]):
        candidates.append(fallback_files[style_idx])
        candidates.append(fallback_files[0])

    for name in candidates:
        candidate = fonts_dir / name
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _parse_rgb(hex_color: str) -> tuple[int, int, int]:
    try:
        rgb = ImageColor.getrgb(hex_color)
        return (rgb[0], rgb[1], rgb[2])
    except Exception:
        return (209, 36, 47)


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return
    head_len = max(14.0, width * 4.5)
    head_width = max(10.0, width * 3.2)
    ux, uy = dx / length, dy / length
    bx = x1 - ux * head_len
    by = y1 - uy * head_len
    px, py = -uy * (head_width / 2.0), ux * (head_width / 2.0)
    draw.polygon([(x1, y1), (bx + px, by + py), (bx - px, by - py)], fill=color)


def _wrap_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
) -> list[str]:
    lines: list[str] = []
    safe_max = max(20.0, max_width)
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = f"{current} {word}".strip() if current else word
            bbox = draw.textbbox((0, 0), trial, font=font)
            if (bbox[2] - bbox[0]) <= safe_max or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def _draw_bounded_text(
    rgba: Image.Image,
    item: AnnotationItem,
    scale: float,
) -> None:
    img_w, img_h = rgba.size
    r = item.rect()
    box_x = int(round(r.x0 * img_w))
    box_y = int(round(r.y0 * img_h))
    box_w = max(40, int(round(r.width * img_w))) if r.width > 0.005 else max(40, img_w - box_x)
    box_h = max(30, int(round(r.height * img_h))) if r.height > 0.005 else max(30, img_h - box_y)

    text_layer = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    font_px = int(round(item.font_size * scale * 1.45))
    font = _load_unicode_font(
        font_px,
        family=item.font_family,
        bold=item.bold,
        italic=item.italic,
    )
    rgb = _parse_rgb(item.color)
    rgba_color = (rgb[0], rgb[1], rgb[2], 255)

    lines = _wrap_text_to_width(tdraw, item.text, font, box_w - 4)
    sample_bbox = tdraw.textbbox((0, 0), "AgČý", font=font)
    line_h = max(font_px + 4, int(round((sample_bbox[3] - sample_bbox[1]) * 1.25)))
    underline_thickness = max(1, int(round(font_px / 14.0)))

    y = 2
    for line in lines:
        if y >= box_h:
            break
        tdraw.text((2, y), line, fill=rgba_color, font=font)
        if item.underline and line.strip():
            lb = tdraw.textbbox((2, y), line, font=font)
            uy = lb[3] + max(1, underline_thickness)
            tdraw.line([(lb[0], uy), (lb[2], uy)], fill=rgba_color, width=underline_thickness)
        y += line_h

    rgba.alpha_composite(text_layer, dest=(box_x, box_y))


def _draw_embedded_image(rgba: Image.Image, item: AnnotationItem) -> None:
    if not item.image_path:
        return
    src = Path(item.image_path)
    if not src.exists():
        return
    img_w, img_h = rgba.size
    r = item.rect()
    dst_x = int(round(r.x0 * img_w))
    dst_y = int(round(r.y0 * img_h))
    dst_w = max(8, int(round(r.width * img_w)))
    dst_h = max(8, int(round(r.height * img_h)))

    with Image.open(src) as raw_img:
        stamp = ImageOps.exif_transpose(raw_img).convert("RGBA")
        stamp = stamp.resize((dst_w, dst_h), Image.Resampling.LANCZOS)
        rgba.alpha_composite(stamp, dest=(dst_x, dst_y))


def _stamp_diagonal_watermark(
    base_image: Image.Image,
    text: str,
    color: str = "#6B7280",
    opacity: int = 55,
) -> Image.Image:
    rgba = base_image.convert("RGBA")
    w, h = rgba.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    font_px = max(36, int(round(min(w, h) * 0.11)))
    font = _load_unicode_font(font_px, family="Arial", bold=True)
    r, g, b = _parse_rgb(color)
    alpha = max(15, min(200, opacity))

    # Render watermark text centered on an oversized canvas and rotate 40 degrees
    diag = int(math.hypot(w, h))
    text_canvas = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_canvas)
    bbox = tdraw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tdraw.text(((diag - tw) // 2, (diag - th) // 2), text, fill=(r, g, b, alpha), font=font)
    rotated = text_canvas.rotate(38, resample=Image.Resampling.BICUBIC)
    crop_x = (diag - w) // 2
    crop_y = (diag - h) // 2
    overlay = rotated.crop((crop_x, crop_y, crop_x + w, crop_y + h))
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def composite_annotations_on_image(
    base_image: Image.Image,
    edits: PageEdits,
    dpi: float = BAKE_DPI,
) -> Image.Image:
    """Render all redactions, shapes, polygons, freehand, images, highlights, text, and crop."""
    rgba = base_image.convert("RGBA")
    img_w, img_h = rgba.size
    scale = dpi / 96.0

    # Layer 1: semi-transparent highlights
    highlight_layer = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(highlight_layer)
    for item in edits.annotations:
        if item.kind != "highlight":
            continue
        r = item.rect()
        rgb = _parse_rgb(item.color)
        hl_draw.rectangle(
            [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
            fill=(rgb[0], rgb[1], rgb[2], 95),
        )
    rgba = Image.alpha_composite(rgba, highlight_layer)

    # Layer 2: true irreversible redactions (opaque blackout / whiteout)
    draw = ImageDraw.Draw(rgba)
    for item in edits.annotations:
        if not item.is_redaction:
            continue
        r = item.rect()
        fill = (0, 0, 0, 255) if item.kind == "redact_black" else (255, 255, 255, 255)
        draw.rectangle(
            [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
            fill=fill,
        )

    # Layer 3: shapes, polygons, freehand, images, lines, arrows, and bounded rich text
    for item in edits.annotations:
        if item.kind in ("highlight", "redact_black", "redact_white"):
            continue
        rgb = _parse_rgb(item.color)
        rgba_color = (rgb[0], rgb[1], rgb[2], 255)
        stroke = max(1, int(round(item.stroke_width * scale)))

        fill_rgba: tuple[int, int, int, int] | None = None
        if item.filled:
            fr, fg, fb = _parse_rgb(item.fill_color)
            fill_rgba = (fr, fg, fb, 255)

        if item.kind == "rect":
            r = item.rect()
            draw.rectangle(
                [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
                fill=fill_rgba,
                outline=rgba_color,
                width=stroke,
            )
        elif item.kind == "ellipse":
            r = item.rect()
            draw.ellipse(
                [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
                fill=fill_rgba,
                outline=rgba_color,
                width=stroke,
            )
        elif item.kind == "polygon" and len(item.points) >= 3:
            pts = [(px * img_w, py * img_h) for px, py in item.points]
            if fill_rgba is not None:
                draw.polygon(pts, fill=fill_rgba)
            draw.line(pts + [pts[0]], fill=rgba_color, width=stroke, joint="curve")
        elif item.kind == "freehand" and len(item.points) >= 2:
            pts = [(px * img_w, py * img_h) for px, py in item.points]
            draw.line(pts, fill=rgba_color, width=stroke, joint="curve")
        elif item.kind == "line":
            draw.line(
                [(item.x0 * img_w, item.y0 * img_h), (item.x1 * img_w, item.y1 * img_h)],
                fill=rgba_color,
                width=stroke,
            )
        elif item.kind == "arrow":
            _draw_arrow(
                draw,
                item.x0 * img_w,
                item.y0 * img_h,
                item.x1 * img_w,
                item.y1 * img_h,
                rgba_color,
                stroke,
            )
        elif item.kind == "image":
            _draw_embedded_image(rgba, item)
            draw = ImageDraw.Draw(rgba)
        elif item.kind == "text" and item.text:
            _draw_bounded_text(rgba, item, scale)
            draw = ImageDraw.Draw(rgba)

    rgb_out = rgba.convert("RGB")

    if edits.crop is not None:
        c = edits.crop.normalized()
        left = int(round(c.x0 * img_w))
        top = int(round(c.y0 * img_h))
        right = max(left + 1, int(round(c.x1 * img_w)))
        bottom = max(top + 1, int(round(c.y1 * img_h)))
        rgb_out = rgb_out.crop((left, top, right, bottom))

    return rgb_out


def _apply_vector_crop(page, crop: RectNorm) -> None:
    c = crop.normalized()
    box = page.mediabox
    llx, lly, urx, ury = float(box.left), float(box.bottom), float(box.right), float(box.top)
    width, height = urx - llx, ury - lly
    rect = RectangleObject(
        (llx + c.x0 * width, ury - c.y1 * height, llx + c.x1 * width, ury - c.y0 * height)
    )
    page.mediabox = rect
    page.cropbox = rect


def _image_to_single_page_pdf(img: Image.Image, target_w_pt: float, target_h_pt: float):
    dpi_x = (img.width * 72.0) / max(1.0, target_w_pt)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=dpi_x, quality=92)
    buf.seek(0)
    tmp_reader = PdfReader(buf)
    page = tmp_reader.pages[0]
    page.mediabox = RectangleObject((0, 0, target_w_pt, target_h_pt))
    page.cropbox = RectangleObject((0, 0, target_w_pt, target_h_pt))
    return page


class PdfDocumentService:
    """Manages an open PDF for rendering, editing/redaction, and page manipulation."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._pdfium_doc: pdfium.PdfDocument | None = None
        self._page_count: int = 0

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def is_open(self) -> bool:
        return self._pdfium_doc is not None and self._path is not None

    def open(self, file_path: str | Path) -> int:
        src = Path(file_path).resolve()
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(t("error.file_not_found", path=str(src)))
        if src.suffix.lower() != ".pdf":
            raise ValueError(t("error.not_a_pdf", filename=src.name))

        reader = PdfReader(str(src))
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    raise PermissionError(t("error.encrypted_pdf"))
            except PermissionError:
                raise
            except Exception as exc:
                raise PermissionError(t("error.encrypted_pdf")) from exc

        self.close()
        self._pdfium_doc = pdfium.PdfDocument(str(src))
        self._path = src
        self._page_count = len(self._pdfium_doc)
        return self._page_count

    def close(self) -> None:
        if self._pdfium_doc is not None:
            try:
                self._pdfium_doc.close()
            except Exception:
                pass
            self._pdfium_doc = None
        self._path = None
        self._page_count = 0

    def get_page_size_pt(self, page_index: int) -> tuple[float, float]:
        if self._pdfium_doc is None:
            raise RuntimeError("No PDF document is open.")
        page = self._pdfium_doc[page_index]
        try:
            w, h = page.get_size()
            return float(w), float(h)
        finally:
            page.close()

    def render_page(self, page_index: int, dpi: float = 144.0) -> Image.Image:
        if self._pdfium_doc is None:
            raise RuntimeError("No PDF document is open.")
        page = self._pdfium_doc[page_index]
        try:
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            return bitmap.to_pil().convert("RGB")
        finally:
            page.close()

    def _atomic_write_and_reopen(self, writer: PdfWriter, dst: Path) -> Path:
        assert self._path is not None
        src = self._path
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".pdfeditor_save_", suffix=".tmp", dir=str(dst.parent)
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        overwriting_open_file = dst == src
        try:
            with tmp_path.open("wb") as handle:
                writer.write(handle)
            if overwriting_open_file:
                self.close()
            tmp_path.replace(dst)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            if overwriting_open_file and not self.is_open:
                self.open(src)
            raise

        self.open(dst)
        return dst

    def _open_reader(self) -> PdfReader:
        if not self.is_open or self._path is None:
            raise RuntimeError("No PDF document is open.")
        reader = PdfReader(str(self._path))
        if reader.is_encrypted:
            reader.decrypt("")
        return reader

    def save(
        self,
        session: DocumentEditSession,
        output_path: str | Path | None = None,
    ) -> Path:
        if not self.is_open or self._path is None:
            raise RuntimeError("No PDF document is open.")

        dst = Path(output_path).resolve() if output_path else self._path
        edited_pages = session.all_edited_pages()

        baked_pages: dict[int, tuple[Image.Image, float, float]] = {}
        for page_idx, edits in edited_pages.items():
            if edits.annotations:
                orig_w_pt, orig_h_pt = self.get_page_size_pt(page_idx)
                base_img = self.render_page(page_idx, dpi=BAKE_DPI)
                baked_img = composite_annotations_on_image(base_img, edits, dpi=BAKE_DPI)
                if edits.crop is not None:
                    c = edits.crop.normalized()
                    target_w_pt = max(10.0, orig_w_pt * c.width)
                    target_h_pt = max(10.0, orig_h_pt * c.height)
                else:
                    target_w_pt, target_h_pt = orig_w_pt, orig_h_pt
                baked_pages[page_idx] = (baked_img, target_w_pt, target_h_pt)

        reader = self._open_reader()
        writer = PdfWriter()
        for page_idx in range(len(reader.pages)):
            if page_idx in baked_pages:
                baked_img, target_w_pt, target_h_pt = baked_pages[page_idx]
                writer.add_page(_image_to_single_page_pdf(baked_img, target_w_pt, target_h_pt))
            else:
                writer.add_page(reader.pages[page_idx])
                edits = edited_pages.get(page_idx)
                if edits is not None and edits.crop is not None:
                    _apply_vector_crop(writer.pages[page_idx], edits.crop)

        saved = self._atomic_write_and_reopen(writer, dst)
        session.mark_saved()
        return saved

    # ------------------------------------------------------------------ Page management

    def rotate_page(self, page_index: int, degrees: int) -> None:
        reader = self._open_reader()
        writer = PdfWriter()
        for idx, page in enumerate(reader.pages):
            if idx == page_index:
                page.rotate(degrees)
            writer.add_page(page)
        assert self._path is not None
        self._atomic_write_and_reopen(writer, self._path)

    def delete_page(self, page_index: int) -> None:
        reader = self._open_reader()
        if len(reader.pages) <= 1:
            raise ValueError(t("error.cannot_delete_last_page"))
        writer = PdfWriter()
        for idx, page in enumerate(reader.pages):
            if idx != page_index:
                writer.add_page(page)
        assert self._path is not None
        self._atomic_write_and_reopen(writer, self._path)

    def move_page(self, from_index: int, to_index: int) -> None:
        reader = self._open_reader()
        pages = list(reader.pages)
        if not (0 <= from_index < len(pages)) or not (0 <= to_index < len(pages)):
            return
        moved = pages.pop(from_index)
        pages.insert(to_index, moved)
        writer = PdfWriter()
        for page in pages:
            writer.add_page(page)
        assert self._path is not None
        self._atomic_write_and_reopen(writer, self._path)

    def insert_blank_page(self, insert_at: int) -> int:
        reader = self._open_reader()
        pages = list(reader.pages)
        ref_idx = max(0, min(len(pages) - 1, insert_at - 1))
        ref_box = pages[ref_idx].mediabox
        w_pt = float(ref_box.width) if pages else 595.0
        h_pt = float(ref_box.height) if pages else 842.0

        writer = PdfWriter()
        for page in pages[:insert_at]:
            writer.add_page(page)
        writer.add_blank_page(width=w_pt, height=h_pt)
        for page in pages[insert_at:]:
            writer.add_page(page)

        assert self._path is not None
        self._atomic_write_and_reopen(writer, self._path)
        return 1

    def insert_pdf(self, insert_at: int, source_pdf: str | Path) -> int:
        src_path = Path(source_pdf).resolve()
        if not src_path.exists():
            raise FileNotFoundError(t("error.file_not_found", path=str(src_path)))
        other = PdfReader(str(src_path))
        if other.is_encrypted and other.decrypt("") == 0:
            raise PermissionError(t("error.encrypted_pdf"))

        reader = self._open_reader()
        pages = list(reader.pages)
        inserted_pages = list(other.pages)

        writer = PdfWriter()
        for page in pages[:insert_at]:
            writer.add_page(page)
        for page in inserted_pages:
            writer.add_page(page)
        for page in pages[insert_at:]:
            writer.add_page(page)

        assert self._path is not None
        self._atomic_write_and_reopen(writer, self._path)
        return len(inserted_pages)

    def extract_pages(self, page_indices: list[int], output_path: str | Path) -> Path:
        reader = self._open_reader()
        writer = PdfWriter()
        for idx in page_indices:
            writer.add_page(reader.pages[idx])

        dst = Path(output_path).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("wb") as handle:
            writer.write(handle)
        return dst

    def apply_watermark(
        self,
        text: str,
        color: str = "#6B7280",
        opacity: int = 55,
    ) -> None:
        if not self.is_open or self._path is None:
            raise RuntimeError("No PDF document is open.")
        rendered_pages: list[tuple[Image.Image, float, float]] = []
        for idx in range(self._page_count):
            w_pt, h_pt = self.get_page_size_pt(idx)
            img = self.render_page(idx, dpi=200.0)
            stamped = _stamp_diagonal_watermark(img, text=text, color=color, opacity=opacity)
            rendered_pages.append((stamped, w_pt, h_pt))

        writer = PdfWriter()
        for stamped, w_pt, h_pt in rendered_pages:
            writer.add_page(_image_to_single_page_pdf(stamped, w_pt, h_pt))

        self._atomic_write_and_reopen(writer, self._path)
