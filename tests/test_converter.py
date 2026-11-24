"""Tests for silent background conversion to PDF."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from pdf_editor.core.converter import build_converted_pdf_path, convert_to_pdf
from pdf_editor.main import main


def test_build_converted_pdf_path_unique(tmp_path: Path) -> None:
    src = tmp_path / "notes.txt"
    src.write_text("hello", encoding="utf-8")

    first = build_converted_pdf_path(src)
    assert first == tmp_path / "notes.pdf"
    first.write_bytes(b"%PDF-1.4")
    assert build_converted_pdf_path(src) == tmp_path / "notes_2.pdf"


def test_convert_png_with_transparency(tmp_path: Path) -> None:
    src = tmp_path / "logo.png"
    Image.new("RGBA", (400, 300), (209, 36, 47, 180)).save(src, "PNG")

    res = convert_to_pdf(src)
    assert res.output_path == tmp_path / "logo.pdf"
    assert len(PdfReader(str(res.output_path)).pages) == 1


def test_convert_multipage_tiff(tmp_path: Path) -> None:
    src = tmp_path / "scan.tiff"
    p1 = Image.new("RGB", (300, 400), (255, 255, 255))
    p2 = Image.new("RGB", (300, 400), (200, 220, 240))
    p1.save(src, "TIFF", save_all=True, append_images=[p2])

    res = convert_to_pdf(src)
    assert len(PdfReader(str(res.output_path)).pages) == 2


def test_convert_txt_and_html(tmp_path: Path) -> None:
    txt = tmp_path / "letter.txt"
    txt.write_text("Příliš žluťoučký kůň úpěl ďábelské ódy.", encoding="utf-8")
    res_txt = convert_to_pdf(txt)
    assert len(PdfReader(str(res_txt.output_path)).pages) >= 1

    html = tmp_path / "invoice.html"
    html.write_text("<html><body><h1>Faktura</h1><p>12 500 Kč</p></body></html>", encoding="utf-8")
    res_html = convert_to_pdf(html)
    assert len(PdfReader(str(res_html.output_path)).pages) >= 1


def test_convert_unsupported_raises(tmp_path: Path) -> None:
    src = tmp_path / "archive.zip"
    src.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError):
        convert_to_pdf(src)


def test_cli_convert_and_downsize_pipeline(tmp_path: Path) -> None:
    jpg = tmp_path / "photo.jpg"
    Image.effect_noise((1200, 1600), 35).convert("RGB").save(jpg, "JPEG", quality=95)

    assert main(["--convert", "--silent", str(jpg)]) == 0
    pdf_path = tmp_path / "photo.pdf"
    assert pdf_path.exists()

    assert main(["--preset", "email", "--silent", str(pdf_path)]) == 0
    small_pdf = tmp_path / "photo_zmenseno.pdf"
    assert small_pdf.exists()
    assert small_pdf.stat().st_size < pdf_path.stat().st_size
