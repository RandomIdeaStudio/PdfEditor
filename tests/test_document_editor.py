"""Tests for PDF rendering, undo/redo, cropping, shapes, text, and true irreversible redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdf_editor.core.document import PdfDocumentService, parse_page_range
from pdf_editor.core.models import AnnotationItem, DocumentEditSession, RectNorm


def _create_vector_text_pdf(target: Path, page_texts: list[str]) -> Path:
    """Create a real multi-page vector PDF containing extractable text."""
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=595, height=842)
        font_dict = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(font_dict)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 24 Tf 72 720 Td ({safe_text}) Tj ET".encode("latin-1"))
        stream_ref = writer._add_object(stream)
        page[NameObject("/Contents")] = stream_ref

    with target.open("wb") as handle:
        writer.write(handle)
    return target


def test_true_irreversible_redaction_destroys_underlying_text(tmp_path: Path) -> None:
    pdf_path = _create_vector_text_pdf(
        tmp_path / "secret.pdf",
        ["SECRET_TOKEN_99421", "PUBLIC_PAGE_TWO_TEXT"],
    )

    # Confirm secret text is initially extractable
    initial_reader = PdfReader(str(pdf_path))
    assert "SECRET_TOKEN_99421" in initial_reader.pages[0].extract_text()
    assert "PUBLIC_PAGE_TWO_TEXT" in initial_reader.pages[1].extract_text()

    doc = PdfDocumentService()
    session = DocumentEditSession()
    doc.open(pdf_path)

    # Apply true blackout redaction over the top band of page 0
    session.add_annotation(
        0,
        AnnotationItem(
            kind="redact_black",
            x0=0.05,
            y0=0.05,
            x1=0.90,
            y1=0.25,
        ),
    )

    # Save overwriting original file (Ctrl+S behavior)
    saved_path = doc.save(session)
    assert saved_path == pdf_path.resolve()
    assert not session.is_dirty

    # Verify page 0 no longer contains any extractable secret text
    after_reader = PdfReader(str(saved_path))
    assert "SECRET_TOKEN_99421" not in (after_reader.pages[0].extract_text() or "")

    # Verify unmodified page 1 retained its original selectable vector text
    assert "PUBLIC_PAGE_TWO_TEXT" in (after_reader.pages[1].extract_text() or "")

    # Verify rendered pixel inside the redacted box is solid black
    rendered = doc.render_page(0, dpi=72.0)
    px = rendered.getpixel((int(rendered.width * 0.3), int(rendered.height * 0.15)))
    assert max(px) < 15, f"Expected solid black pixel in redacted region, got {px}"
    doc.close()


def test_shapes_text_and_crop_save_and_undo_redo(tmp_path: Path) -> None:
    pdf_path = _create_vector_text_pdf(tmp_path / "contract.pdf", ["Page One"])
    doc = PdfDocumentService()
    session = DocumentEditSession()
    doc.open(pdf_path)

    session.add_annotation(
        0,
        AnnotationItem(
            kind="rect",
            x0=0.1,
            y0=0.2,
            x1=0.4,
            y1=0.4,
            filled=True,
            fill_color="#00AA00",
            stroke_width=4.0,
        ),
    )
    session.add_annotation(0, AnnotationItem(kind="ellipse", x0=0.5, y0=0.2, x1=0.8, y1=0.4))
    session.add_annotation(
        0,
        AnnotationItem(
            kind="polygon",
            points=((0.15, 0.55), (0.35, 0.50), (0.40, 0.65), (0.20, 0.68)),
            color="#1D4ED8",
            filled=True,
            fill_color="#93C5FD",
            stroke_width=3.0,
        ),
    )
    session.add_annotation(0, AnnotationItem(kind="arrow", x0=0.5, y0=0.5, x1=0.8, y1=0.6))
    session.add_annotation(
        0,
        AnnotationItem(
            kind="text",
            x0=0.1,
            y0=0.7,
            x1=0.8,
            y1=0.9,
            text="Příliš žluťoučký kůň úpěl ďábelské ódy",
            font_family="Arial",
            font_size=18.0,
            bold=True,
            italic=True,
            underline=True,
        ),
    )
    session.set_crop(0, RectNorm(0.05, 0.05, 0.95, 0.95))

    assert session.can_undo
    assert session.undo() == 0
    assert session.page_edits(0).crop is None
    assert session.can_redo
    assert session.redo() == 0
    assert session.page_edits(0).crop is not None

    out_path = tmp_path / "contract_out.pdf"
    doc.save(session, output_path=out_path)
    assert out_path.exists()
    assert len(PdfReader(str(out_path)).pages) == 1

    # Verify filled rectangle actually painted green pixels inside the saved PDF
    rendered = doc.render_page(0, dpi=72.0)
    r, g, b = rendered.getpixel((int(rendered.width * 0.25), int(rendered.height * 0.30)))
    assert g > r + 40 and g > b + 40, f"Expected green filled rectangle pixel, got {(r, g, b)}"
    doc.close()


def test_vector_only_crop_preserves_selectable_text(tmp_path: Path) -> None:
    pdf_path = _create_vector_text_pdf(tmp_path / "crop_only.pdf", ["KEEP_VECTOR_TEXT"])
    doc = PdfDocumentService()
    session = DocumentEditSession()
    doc.open(pdf_path)

    orig_w, orig_h = doc.get_page_size_pt(0)
    session.set_crop(0, RectNorm(0.0, 0.0, 0.5, 0.5))
    doc.save(session)

    new_w, new_h = doc.get_page_size_pt(0)
    assert abs(new_w - orig_w * 0.5) < 2.0
    assert abs(new_h - orig_h * 0.5) < 2.0
    assert "KEEP_VECTOR_TEXT" in (PdfReader(str(pdf_path)).pages[0].extract_text() or "")
    doc.close()


def test_freehand_image_and_select_move_delete_undo(tmp_path: Path) -> None:
    pdf_path = _create_vector_text_pdf(tmp_path / "sign.pdf", ["Sign here"])
    stamp_path = tmp_path / "stamp.png"
    Image.new("RGBA", (120, 60), (0, 120, 255, 200)).save(stamp_path, "PNG")

    doc = PdfDocumentService()
    session = DocumentEditSession()
    doc.open(pdf_path)

    session.add_annotation(
        0,
        AnnotationItem(
            kind="freehand",
            points=((0.1, 0.2), (0.2, 0.25), (0.3, 0.22)),
            color="#111827",
            stroke_width=3.0,
        ),
    )
    session.add_annotation(
        0,
        AnnotationItem(
            kind="image",
            x0=0.4,
            y0=0.4,
            x1=0.7,
            y1=0.55,
            image_path=str(stamp_path),
        ),
    )

    assert session.page_edits(0).annotations[1].hit_test(0.55, 0.45)
    session.move_annotation(0, 1, 0.1, 0.1)
    assert abs(session.page_edits(0).annotations[1].x0 - 0.5) < 1e-6

    session.undo()
    assert abs(session.page_edits(0).annotations[1].x0 - 0.4) < 1e-6
    session.redo()
    assert abs(session.page_edits(0).annotations[1].x0 - 0.5) < 1e-6

    session.delete_annotation(0, 0)
    assert len(session.page_edits(0).annotations) == 1
    session.undo()
    assert len(session.page_edits(0).annotations) == 2

    out = tmp_path / "signed_out.pdf"
    doc.save(session, output_path=out)
    assert out.exists()
    doc.close()


def test_page_management_rotate_insert_move_delete_extract_watermark(tmp_path: Path) -> None:
    pdf_a = _create_vector_text_pdf(tmp_path / "a.pdf", ["PAGE_A1", "PAGE_A2"])
    pdf_b = _create_vector_text_pdf(tmp_path / "b.pdf", ["PAGE_B1"])

    doc = PdfDocumentService()
    doc.open(pdf_a)
    assert doc.page_count == 2

    # Rotate page 0 by 90 degrees (width/height swap)
    w0, h0 = doc.get_page_size_pt(0)
    doc.rotate_page(0, 90)
    w1, h1 = doc.get_page_size_pt(0)
    assert abs(w1 - h0) < 2.0 and abs(h1 - w0) < 2.0

    # Insert blank page after page 0
    assert doc.insert_blank_page(1) == 1
    assert doc.page_count == 3

    # Insert/merge pdf_b after blank page
    assert doc.insert_pdf(2, pdf_b) == 1
    assert doc.page_count == 4

    # Move inserted pdf_b page to front
    doc.move_page(2, 0)
    assert "PAGE_B1" in (PdfReader(str(pdf_a)).pages[0].extract_text() or "")

    # Extract pages 1-2 to a new PDF
    assert parse_page_range("1-2, 4", 4) == [0, 1, 3]
    with pytest.raises(ValueError):
        parse_page_range("0-2", 4)
    extracted = doc.extract_pages([0, 1], tmp_path / "split.pdf")
    assert len(PdfReader(str(extracted)).pages) == 2

    # Delete a page
    doc.delete_page(1)
    assert doc.page_count == 3

    # Watermark all pages
    doc.apply_watermark("KOPIE")
    assert doc.page_count == 3

    # Deleting down to 1 page works, deleting last page raises
    doc.delete_page(0)
    doc.delete_page(0)
    assert doc.page_count == 1
    with pytest.raises(ValueError):
        doc.delete_page(0)

    doc.close()
