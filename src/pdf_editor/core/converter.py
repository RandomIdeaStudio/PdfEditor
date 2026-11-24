"""Silent background conversion of images, text, HTML, and Office files to PDF."""

from __future__ import annotations

import html as html_lib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .i18n import t

IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
)
TEXT_EXTENSIONS: tuple[str, ...] = (".txt", ".log", ".md", ".csv")
HTML_EXTENSIONS: tuple[str, ...] = (".html", ".htm")
WORD_EXTENSIONS: tuple[str, ...] = (".docx", ".doc", ".rtf", ".odt")
EXCEL_EXTENSIONS: tuple[str, ...] = (".xlsx", ".xls", ".ods")
POWERPOINT_EXTENSIONS: tuple[str, ...] = (".pptx", ".ppt", ".odp")

OFFICE_EXTENSIONS: tuple[str, ...] = (
    WORD_EXTENSIONS + EXCEL_EXTENSIONS + POWERPOINT_EXTENSIONS
)

CONVERTIBLE_EXTENSIONS: tuple[str, ...] = (
    IMAGE_EXTENSIONS + TEXT_EXTENSIONS + HTML_EXTENSIONS + OFFICE_EXTENSIONS
)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


@dataclass(frozen=True)
class ConversionResult:
    input_path: Path
    output_path: Path
    output_bytes: int
    engine: str


def is_convertible(path: Path) -> bool:
    return path.suffix.lower() in CONVERTIBLE_EXTENSIONS


def build_converted_pdf_path(input_path: Path) -> Path:
    """Return a unique `<same_name>.pdf` path (with `_2.pdf` fallback)."""
    stem = input_path.stem
    parent = input_path.parent
    candidate = parent / f"{stem}.pdf"
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = parent / f"{stem}_{index}.pdf"
        if not candidate.exists():
            return candidate
        index += 1


def _find_browser_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    for cmd in ("msedge", "chrome"):
        found = shutil.which(cmd)
        if found:
            return Path(found)
    return None


def _find_libreoffice_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "LibreOffice"
        / "program"
        / "soffice.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "LibreOffice"
        / "program"
        / "soffice.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    found = shutil.which("soffice")
    return Path(found) if found else None


def _image_to_rgb_flat(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _convert_image(src: Path, dst: Path) -> str:
    with Image.open(src) as img:
        n_frames = getattr(img, "n_frames", 1)
        pages: list[Image.Image] = []
        for idx in range(n_frames):
            img.seek(idx)
            pages.append(_image_to_rgb_flat(img.copy()))

    if not pages:
        raise ValueError(t("error.conversion_failed"))

    first, rest = pages[0], pages[1:]
    first.save(
        dst,
        "PDF",
        resolution=150.0,
        save_all=bool(rest),
        append_images=rest,
    )
    return "Pillow"


def _convert_html_via_browser(html_path: Path, dst: Path) -> str:
    browser = _find_browser_exe()
    if browser is None:
        raise RuntimeError("No headless browser found.")

    uri = html_path.resolve().as_uri()
    user_data_dir = Path(tempfile.mkdtemp(prefix="pdfeditor_edge_"))
    try:
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            f"--user-data-dir={user_data_dir}",
            f"--print-to-pdf={dst}",
            uri,
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_CREATE_NO_WINDOW,
        )
        if not dst.exists() or dst.stat().st_size == 0:
            cmd[1] = "--headless"
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("Headless browser failed to produce PDF.")
        return browser.stem
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)


def _read_text_with_fallback(src: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return src.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return src.read_text(encoding="utf-8", errors="replace")


def _convert_text_offline_pillow(text: str, dst: Path) -> str:
    page_w, page_h = 1240, 1754
    margin = 80
    font_size = 20
    line_height = 28

    font = None
    for font_name in ("consola.ttf", "arial.ttf", "segoeui.ttf"):
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / font_name
        if font_path.exists():
            try:
                font = ImageFont.truetype(str(font_path), font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    max_text_w = page_w - 2 * margin
    wrapped_lines: list[str] = []
    measure_img = Image.new("RGB", (10, 10), (255, 255, 255))
    measure_draw = ImageDraw.Draw(measure_img)

    for raw_line in text.splitlines() or [""]:
        expanded = raw_line.replace("\t", "    ")
        if not expanded:
            wrapped_lines.append("")
            continue
        current = ""
        for ch in expanded:
            trial = current + ch
            bbox = measure_draw.textbbox((0, 0), trial, font=font)
            if (bbox[2] - bbox[0]) > max_text_w and current:
                wrapped_lines.append(current)
                current = ch
            else:
                current = trial
        wrapped_lines.append(current)

    lines_per_page = max(1, (page_h - 2 * margin) // line_height)
    pages: list[Image.Image] = []
    for start in range(0, len(wrapped_lines), lines_per_page):
        chunk = wrapped_lines[start : start + lines_per_page]
        page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
        draw = ImageDraw.Draw(page)
        y = margin
        for line in chunk:
            draw.text((margin, y), line, fill=(24, 24, 24), font=font)
            y += line_height
        pages.append(page)

    first, rest = pages[0], pages[1:]
    first.save(dst, "PDF", resolution=150.0, save_all=bool(rest), append_images=rest)
    return "Pillow"


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = True
        elif tag.lower() in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        lines = [line.strip() for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


def _convert_html(src: Path, dst: Path) -> str:
    try:
        return _convert_html_via_browser(src, dst)
    except Exception:
        raw_html = _read_text_with_fallback(src)
        extractor = _HtmlTextExtractor()
        extractor.feed(raw_html)
        text = extractor.get_text() or raw_html
        return _convert_text_offline_pillow(text, dst)


def _convert_text(src: Path, dst: Path) -> str:
    content = _read_text_with_fallback(src)
    browser = _find_browser_exe()
    if browser is not None:
        escaped = html_lib.escape(content)
        title = html_lib.escape(src.name)
        doc_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{
    font-family: "Consolas", "Segoe UI", monospace;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1f2328;
    margin: 0;
  }}
  pre {{ white-space: pre-wrap; word-wrap: break-word; margin: 0; font-family: inherit; }}
</style>
</head>
<body><pre>{escaped}</pre></body>
</html>"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="pdfeditor_txt_"))
        try:
            tmp_html = tmp_dir / "document.html"
            tmp_html.write_text(doc_html, encoding="utf-8")
            return _convert_html_via_browser(tmp_html, dst)
        except Exception:
            pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return _convert_text_offline_pillow(content, dst)


def _convert_office_via_com(src: Path, dst: Path) -> str:
    import pythoncom
    import win32com.client

    ext = src.suffix.lower()
    src_str = str(src.resolve())
    dst_str = str(dst.resolve())

    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        if ext in WORD_EXTENSIONS:
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0
            doc = app.Documents.Open(
                src_str,
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
            )
            doc.ExportAsFixedFormat(dst_str, 17)
            return "Microsoft Word"

        if ext in EXCEL_EXTENSIONS:
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            doc = app.Workbooks.Open(src_str, UpdateLinks=0, ReadOnly=True)
            doc.ExportAsFixedFormat(0, dst_str)
            return "Microsoft Excel"

        if ext in POWERPOINT_EXTENSIONS:
            app = win32com.client.DispatchEx("PowerPoint.Application")
            doc = app.Presentations.Open(
                src_str,
                ReadOnly=True,
                Untitled=False,
                WithWindow=False,
            )
            doc.SaveAs(dst_str, 32)
            return "Microsoft PowerPoint"

        raise ValueError(t("error.unsupported_format", ext=ext))
    finally:
        if doc is not None:
            try:
                if ext in POWERPOINT_EXTENSIONS:
                    doc.Close()
                else:
                    doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _convert_office_via_libreoffice(src: Path, dst: Path) -> str:
    soffice = _find_libreoffice_exe()
    if soffice is None:
        raise FileNotFoundError("LibreOffice not found.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="pdfeditor_lo_"))
    try:
        cmd = [
            str(soffice),
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(src.resolve()),
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=_CREATE_NO_WINDOW,
            check=True,
        )
        produced = tmp_dir / f"{src.stem}.pdf"
        if not produced.exists():
            pdfs = list(tmp_dir.glob("*.pdf"))
            if not pdfs:
                raise RuntimeError("LibreOffice produced no PDF output.")
            produced = pdfs[0]
        shutil.move(str(produced), str(dst))
        return "LibreOffice"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _convert_office(src: Path, dst: Path) -> str:
    try:
        engine = _convert_office_via_com(src, dst)
        if dst.exists() and dst.stat().st_size > 0:
            return engine
    except Exception:
        pass

    try:
        return _convert_office_via_libreoffice(src, dst)
    except Exception as exc:
        raise RuntimeError(t("error.office_missing")) from exc


def convert_to_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    status_key_callback: Callable[[str], None] | None = None,
) -> ConversionResult:
    """Silently convert a supported non-PDF file into `<same_name>.pdf`."""
    src = Path(input_path).resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(t("error.file_not_found", path=str(src)))

    ext = src.suffix.lower()
    if ext == ".pdf":
        raise ValueError(t("error.already_pdf"))
    if ext not in CONVERTIBLE_EXTENSIONS:
        raise ValueError(t("error.unsupported_format", ext=ext or "(none)"))

    dst = Path(output_path).resolve() if output_path else build_converted_pdf_path(src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=".pdfeditor_conv_", suffix=".pdf", dir=str(dst.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.unlink(missing_ok=True)

    try:
        if ext in IMAGE_EXTENSIONS:
            if status_key_callback:
                status_key_callback("toast.converting_image")
            engine = _convert_image(src, tmp_path)
        elif ext in TEXT_EXTENSIONS:
            if status_key_callback:
                status_key_callback("toast.converting_text")
            engine = _convert_text(src, tmp_path)
        elif ext in HTML_EXTENSIONS:
            if status_key_callback:
                status_key_callback("toast.converting_html")
            engine = _convert_html(src, tmp_path)
        elif ext in OFFICE_EXTENSIONS:
            if status_key_callback:
                status_key_callback("toast.converting_office")
            engine = _convert_office(src, tmp_path)
        else:
            raise ValueError(t("error.unsupported_format", ext=ext))

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError(t("error.conversion_failed"))

        tmp_path.replace(dst)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return ConversionResult(
        input_path=src,
        output_path=dst,
        output_bytes=dst.stat().st_size,
        engine=engine,
    )
