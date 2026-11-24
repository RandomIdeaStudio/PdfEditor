# PdfEditor

Standalone Windows 10 & Windows 11 desktop application combining:

1. **Simple PDF Editor**
   - Page cropping (destructive crop when combined with redaction, clean cropbox otherwise)
   - Geometric shapes (rectangle, ellipse, line, arrow, highlighter)
   - Text annotations with full Unicode / Czech diacritics support
   - **True irreversible redaction & erasing** (blackout / whiteout): physically destroys underlying text, vector paths, and image pixels on redacted pages so nothing can be selected, copied, or recovered
   - Undo / Redo (`Ctrl+Z` / `Ctrl+Y`), Save (`Ctrl+S`), Save As (`Ctrl+Shift+S`), and built-in PDF downsizing
2. **PDF Downsizing** (3 presets: Email 100 DPI, Balanced 150 DPI, High Quality 230 DPI → `<name>_zmenseno.pdf`)
3. **Silent Convert to PDF** (images, plain text, HTML, and MS Office / LibreOffice documents → `<same_name>.pdf`)
4. **Windows Right-Click Integration** (single-file self-installing executable, no admin rights required)
5. **Multilingual UI** (Czech & English, loaded strictly from `locales/*.json`)

## Development Commands

```powershell
# Run full test suite (including i18n key parity checks)
.\scripts\test.ps1

# Build single distributable installer (dist\PdfEditor_Setup_v1.0.0.exe)
.\scripts\build.ps1
```

## CLI Usage

- `PdfEditor.exe` – launch the PDF editor
- `PdfEditor.exe "C:\path\doc.pdf"` – open a PDF directly in the editor
- `PdfEditor.exe --preset balanced "C:\path\doc.pdf" [--silent]` – downsize a PDF
- `PdfEditor.exe --convert "C:\path\file.docx" [--silent]` – silently convert a supported file to PDF
- `PdfEditor.exe --setup` – open the Windows context menu installer window
- `PdfEditor.exe --install [--silent]` / `--uninstall [--silent]` – install or remove Windows integration
