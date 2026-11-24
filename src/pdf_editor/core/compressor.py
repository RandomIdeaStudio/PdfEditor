"""PDF downsizing engine preserving sharp vector text."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image
from pypdf import PdfReader, PdfWriter

from .. import OUTPUT_SUFFIX
from .i18n import t
from .presets import CompressionPreset, get_preset


@dataclass(frozen=True)
class CompressionResult:
    input_path: Path
    output_path: Path
    preset: CompressionPreset
    original_bytes: int
    compressed_bytes: int
    pages: int
    images_seen: int
    images_recompressed: int

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.compressed_bytes

    @property
    def saved_percent(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return (self.saved_bytes / self.original_bytes) * 100.0


def format_size(num_bytes: int) -> str:
    """Format byte size into a human-readable string."""
    value = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def build_output_path(input_path: Path, suffix: str = OUTPUT_SUFFIX) -> Path:
    """Return a unique output path `<name>_zmenseno.pdf` (with `_2`, `_3` fallback)."""
    stem = input_path.stem
    parent = input_path.parent
    candidate = parent / f"{stem}{suffix}.pdf"
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = parent / f"{stem}{suffix}_{index}.pdf"
        if not candidate.exists():
            return candidate
        index += 1


def _has_transparency(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def _compute_target_bounds(page, preset: CompressionPreset) -> tuple[int, int]:
    try:
        width_pt = float(page.mediabox.width)
        height_pt = float(page.mediabox.height)
    except Exception:
        return preset.max_long_edge, preset.max_long_edge

    max_w = max(400, int(round((width_pt / 72.0) * preset.target_dpi)))
    max_h = max(400, int(round((height_pt / 72.0) * preset.target_dpi)))
    cap = preset.max_long_edge * 2
    return min(max_w, cap), min(max_h, cap)


def _prepare_resized_image(
    pil_img: Image.Image,
    max_w: int,
    max_h: int,
    preset: CompressionPreset,
) -> tuple[Image.Image, bool]:
    orig_w, orig_h = pil_img.size
    if orig_w <= 0 or orig_h <= 0:
        return pil_img, False

    scale = min(1.0, max_w / orig_w, max_h / orig_h)
    if max(orig_w, orig_h) > preset.max_long_edge:
        scale = min(scale, preset.max_long_edge / max(orig_w, orig_h))

    resized = pil_img
    if scale < 0.98:
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        resized = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if _has_transparency(resized) or resized.mode == "1":
        return resized, False

    if resized.mode not in ("RGB", "L"):
        resized = resized.convert("RGB")

    return resized, True


def _estimate_jpeg_size(img: Image.Image, quality: int) -> int:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.tell()


def compress_pdf(
    input_path: str | Path,
    preset_key: str = "balanced",
    output_path: str | Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CompressionResult:
    """Downsize a PDF according to `preset_key` and save to `<name>_zmenseno.pdf`."""
    src = Path(input_path).resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(t("error.file_not_found", path=str(src)))
    if src.suffix.lower() != ".pdf":
        raise ValueError(t("error.not_a_pdf", filename=src.name))

    preset = get_preset(preset_key)
    dst = Path(output_path).resolve() if output_path else build_output_path(src)
    original_bytes = src.stat().st_size

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise PermissionError(t("error.encrypted_pdf"))
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError(t("error.encrypted_pdf")) from exc

    writer = PdfWriter()
    writer.append(reader)

    total_pages = len(writer.pages)
    images_seen = 0
    images_recompressed = 0
    processed_refs: set[tuple[int, int]] = set()

    for page_idx, page in enumerate(writer.pages):
        max_w, max_h = _compute_target_bounds(page, preset)

        try:
            page_images = list(page.images)
        except Exception:
            page_images = []

        for img_file in page_images:
            indirect_ref = getattr(img_file, "indirect_reference", None)
            if indirect_ref is not None:
                ref_key = (indirect_ref.idnum, indirect_ref.generation)
                if ref_key in processed_refs:
                    continue
                processed_refs.add(ref_key)

            images_seen += 1
            try:
                pil_img = img_file.image
                if pil_img is None:
                    continue

                raw_size = len(img_file.data) if getattr(img_file, "data", None) else 0
                orig_size = pil_img.size

                candidate_img, use_jpeg = _prepare_resized_image(
                    pil_img, max_w, max_h, preset
                )

                if use_jpeg:
                    est_size = _estimate_jpeg_size(candidate_img, preset.jpeg_quality)
                    if raw_size == 0 or est_size < raw_size * 0.95:
                        img_file.replace(
                            candidate_img,
                            quality=preset.jpeg_quality,
                            optimize=True,
                        )
                        images_recompressed += 1
                elif candidate_img.size != orig_size:
                    img_file.replace(candidate_img)
                    images_recompressed += 1
            except Exception:
                continue

        try:
            page.compress_content_streams(level=9)
        except Exception:
            pass

        if progress_callback:
            progress_callback(page_idx + 1, total_pages)

    try:
        writer.compress_identical_objects(
            remove_duplicates=True,
            remove_unreferenced=True,
        )
    except TypeError:
        try:
            writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        except Exception:
            pass
    except Exception:
        pass

    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".pdfeditor_downsize_", suffix=".tmp", dir=str(dst.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        with tmp_path.open("wb") as handle:
            writer.write(handle)

        compressed_bytes = tmp_path.stat().st_size
        if compressed_bytes >= original_bytes:
            shutil.copy2(src, dst)
            tmp_path.unlink(missing_ok=True)
            compressed_bytes = dst.stat().st_size
        else:
            tmp_path.replace(dst)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return CompressionResult(
        input_path=src,
        output_path=dst,
        preset=preset,
        original_bytes=original_bytes,
        compressed_bytes=compressed_bytes,
        pages=total_pages,
        images_seen=images_seen,
        images_recompressed=images_recompressed,
    )
