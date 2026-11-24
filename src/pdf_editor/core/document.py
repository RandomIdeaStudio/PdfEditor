"""PDF document rendering (pypdfium2) and editing/redaction save engine (pypdf + Pillow)."""

from __future__ import annotations

import io
import math
import os
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageColor, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from .i18n import t
from .models import AnnotationItem, DocumentEditSession, PageEdits, RectNorm

BAKE_DPI = 250.0


def _load_unicode_font(pixel_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a Windows TrueType font with full Latin-Extended (Czech) support."""
    size = max(10, int(round(pixel_size)))
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf"):
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


def composite_annotations_on_image(
    base_image: Image.Image,
    edits: PageEdits,
    dpi: float = BAKE_DPI,
) -> Image.Image:
    """Render all redactions, shapes, highlights, text, and crop onto a PIL RGB image.

    Redactions are painted opaquely directly onto the raster image so no underlying
    text, vectors, or pixels survive.
    """
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

    # Layer 3: geometric shapes & text
    for item in edits.annotations:
        if item.kind in ("highlight", "redact_black", "redact_white"):
            continue
        rgb = _parse_rgb(item.color)
        rgba_color = (rgb[0], rgb[1], rgb[2], 255)
        stroke = max(1, int(round(item.stroke_width * scale)))

        if item.kind == "rect":
            r = item.rect()
            draw.rectangle(
                [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
                outline=rgba_color,
                width=stroke,
            )
        elif item.kind == "ellipse":
            r = item.rect()
            draw.ellipse(
                [r.x0 * img_w, r.y0 * img_h, r.x1 * img_w, r.y1 * img_h],
                outline=rgba_color,
                width=stroke,
            )
        elif item.kind == "line":
            draw.line(
                [
                    (item.x0 * img_w, item.y0 * img_h),
                    (item.x1 * img_w, item.y1 * img_h),
                ],
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
        elif item.kind == "text" and item.text:
            font = _load_unicode_font(int(round(item.font_size * scale)))
            draw.multiline_text(
                (item.x0 * img_w, item.y0 * img_h),
                item.text,
                fill=rgba_color,
                font=font,
            )

    rgb_out = rgba.convert("RGB")

    # Apply physical crop if set
    if edits.crop is not None:
        c = edits.crop.normalized()
        left = int(round(c.x0 * img_w))
        top = int(round(c.y0 * img_h))
        right = max(left + 1, int(round(c.x1 * img_w)))
        bottom = max(top + 1, int(round(c.y1 * img_h)))
        rgb_out = rgb_out.crop((left, top, right, bottom))

    return rgb_out


def _apply_vector_crop(page, crop: RectNorm) -> None:
    """Apply a clean CropBox/MediaBox update on an unrasterized PDF page."""
    c = crop.normalized()
    box = page.mediabox
    llx = float(box.left)
    lly = float(box.bottom)
    urx = float(box.right)
    ury = float(box.top)
    width = urx - llx
    height = ury - lly

    # Convert top-left normalized coordinates to bottom-left PDF coordinates
    new_llx = llx + c.x0 * width
    new_urx = llx + c.x1 * width
    new_ury = ury - c.y0 * height
    new_lly = ury - c.y1 * height

    rect = RectangleObject((new_llx, new_lly, new_urx, new_ury))
    page.mediabox = rect
    page.cropbox = rect


def _image_to_single_page_pdf(img: Image.Image, target_w_pt: float, target_h_pt: float):
    """Wrap a PIL RGB image into a single-page pypdf PageObject sized in PDF points."""
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
    """Manages an open PDF for rendering and saving edits with true redaction."""

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

        # Verify readability and check password protection with pypdf
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
        """Render a 0-based PDF page to a PIL RGB image at the requested DPI."""
        if self._pdfium_doc is None:
            raise RuntimeError("No PDF document is open.")
        page = self._pdfium_doc[page_index]
        try:
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            return bitmap.to_pil().convert("RGB")
        finally:
            page.close()

    def save(
        self,
        session: DocumentEditSession,
        output_path: str | Path | None = None,
    ) -> Path:
        """Persist all edits to `output_path` (or overwrite the open file atomically)."""
        if not self.is_open or self._path is None:
            raise RuntimeError("No PDF document is open.")

        src = self._path
        dst = Path(output_path).resolve() if output_path else src
        edited_pages = session.all_edited_pages()

        # Pre-render all pages that require raster baking while pdfium handle is open
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

        # Build output PDF in memory / temp file
        reader = PdfReader(str(src))
        if reader.is_encrypted:
            reader.decrypt("")

        writer = PdfWriter()
        for page_idx in range(len(reader.pages)):
            if page_idx in baked_pages:
                baked_img, target_w_pt, target_h_pt = baked_pages[page_idx]
                new_page = _image_to_single_page_pdf(baked_img, target_w_pt, target_h_pt)
                writer.add_page(new_page)
            else:
                writer.add_page(reader.pages[page_idx])
                edits = edited_pages.get(page_idx)
                if edits is not None and edits.crop is not None:
                    _apply_vector_crop(writer.pages[page_idx], edits.crop)

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
                # Release Windows file lock before replacing the open PDF
                self.close()

            tmp_path.replace(dst)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            if overwriting_open_file and not self.is_open:
                self.open(src)
            raise

        # Reopen the saved file so rendering reflects the new saved state
        self.open(dst)
        session.mark_saved()
        return dst
