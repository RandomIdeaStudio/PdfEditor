# PDF Editor

Free and open-source PDF editor for Windows 10 and Windows 11 by [Random Idea Studio](https://randomideastudio.com). Works fully offline.

**Download:** [latest release](https://github.com/RandomIdeaStudio/PdfEditor/releases/latest) (`PdfEditor_Setup_vX.Y.Z.exe`, with its SHA-256 checksum).

## Features

1. **Simple PDF editor**
   - Page cropping (destructive crop when combined with redaction, clean cropbox otherwise)
   - Shapes (rectangle, ellipse, line, arrow, polygon, highlighter), freehand pen, image stamp
   - Text annotations with full Unicode / Czech diacritics support
   - **True irreversible redaction & erasing** (blackout / whiteout): physically destroys underlying text, vector paths and image pixels on redacted pages, so nothing can be selected, copied or recovered
   - Page management: rotate, insert, merge, move, delete, extract, watermark
   - Undo / Redo (`Ctrl+Z` / `Ctrl+Y`), Save (`Ctrl+S`), Save As (`Ctrl+Shift+S`)
2. **PDF downsizing** (3 presets: Email 100 DPI, Balanced 150 DPI, High Quality 230 DPI → `<name>_zmenseno.pdf`)
3. **Silent convert to PDF** (images, plain text, HTML, and MS Office / LibreOffice documents → `<same_name>.pdf`)
4. **Windows right-click integration** (single self-installing executable, no admin rights, uninstall from Windows Settings → Installed apps)
5. **Multilingual UI** (Czech and English)

## Install and uninstall

Run `PdfEditor_Setup_vX.Y.Z.exe`. The setup window copies the program to `%LOCALAPPDATA%\PdfEditor` and adds the right-click menu entries for the current user only. It lists these changes before you confirm them. To uninstall, use Windows Settings → Apps → Installed apps → PDF Editor, or run `PdfEditor.exe --uninstall`.

## Development

```powershell
# Run full test suite (including i18n key parity checks)
.\scripts\test.ps1

# Build the distributable executable (dist\PdfEditor_Setup_v<version>.exe + .sha256)
.\scripts\build.ps1

# Run in dev mode
python run_app.py
```

## CLI usage

- `PdfEditor.exe` – launch the PDF editor
- `PdfEditor.exe "C:\path\doc.pdf"` – open a PDF directly in the editor
- `PdfEditor.exe --preset balanced "C:\path\doc.pdf" [--silent]` – downsize a PDF
- `PdfEditor.exe --convert "C:\path\file.docx" [--silent]` – silently convert a supported file to PDF
- `PdfEditor.exe --setup` – open the Windows context menu installer window
- `PdfEditor.exe --install [--silent]` / `--uninstall [--silent]` – install or remove Windows integration

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- Committers and reviewers: [RandomIdeaStudio](https://github.com/RandomIdeaStudio)
- Approvers: [RandomIdeaStudio](https://github.com/RandomIdeaStudio)

Release binaries are built from tagged commits on `main` in GitHub Actions and every signing request is approved manually. Releases published before the signing was set up are unsigned and say so in their release notes.

## Privacy

This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it. See [PRIVACY.md](PRIVACY.md).

## License

[MIT License](LICENSE). Third-party components are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Security reports: [SECURITY.md](SECURITY.md).
