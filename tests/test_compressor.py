"""Tests for PDF downsizing engine."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from pdf_editor.core.compressor import build_output_path, compress_pdf, format_size
from pdf_editor.core.presets import PRESETS, get_preset


def _create_heavy_image_pdf(target: Path, width: int = 1600, height: int = 2200) -> Path:
    rng = random.Random(42)
    img = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        row_r = (y * 255) // height
        for x in range(width):
            col_g = (x * 255) // width
            noise = rng.randint(-18, 18)
            r = max(0, min(255, row_r + noise))
            g = max(0, min(255, col_g + noise))
            b = max(0, min(255, ((x + y) // 16) % 255 + noise))
            pixels.append((r, g, b))
    img.putdata(pixels)
    img.save(target, "PDF", resolution=300.0)
    return target


def test_build_output_path_unique(tmp_path: Path) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4")

    first = build_output_path(src)
    assert first == tmp_path / "doc_zmenseno.pdf"
    first.write_bytes(b"%PDF-1.4")
    assert build_output_path(src) == tmp_path / "doc_zmenseno_2.pdf"


def test_format_size() -> None:
    assert format_size(512) == "512 B"
    assert format_size(1536) == "1.5 KB"


def test_presets_valid() -> None:
    assert len(PRESETS) == 3
    for p in PRESETS:
        assert get_preset(p.key) == p
    with pytest.raises(ValueError):
        get_preset("unknown")


def test_compress_pdf_reduces_size_across_presets(tmp_path: Path) -> None:
    src = _create_heavy_image_pdf(tmp_path / "scan.pdf")
    orig_size = src.stat().st_size

    res_email = compress_pdf(src, preset_key="email")
    res_balanced = compress_pdf(src, preset_key="balanced")
    res_high = compress_pdf(src, preset_key="high")

    assert res_email.compressed_bytes < res_balanced.compressed_bytes < res_high.compressed_bytes
    assert res_email.compressed_bytes < orig_size
    assert len(PdfReader(str(res_balanced.output_path)).pages) == 1
