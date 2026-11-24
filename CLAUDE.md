# PdfEditor – Project Guide

`PdfEditor` is a standalone Windows 10/11 desktop PDF editor, PDF downsizer, and silent file-to-PDF converter built by Random Idea Studio.

This repository is an application (not a Godot game) and therefore follows the Python + PySide6 desktop stack rather than Godot rules. All applicable studio rules from the workspace `CLAUDE.md` apply strictly.

## Stack & Licenses (Permissive / LGPL-only, no AGPL)
- **Python 3.12**
- **PySide6 (Qt 6)** – LGPL-3.0 (dynamically linked Qt binaries)
- **pypdfium2** (Google PDFium) – Apache-2.0 / BSD-3-Clause (page rendering)
- **pypdf** – BSD-3-Clause (PDF manipulation & compression)
- **Pillow** – MIT-CMU (image processing, redaction baking, image-to-PDF)
- **pywin32** – PSF-2.0 (silent MS Office COM conversion)

## Architecture
- `src/pdf_editor/core/` – Pure domain & PDF logic (strictly zero `PySide6` imports):
  - `i18n.py` – Multilingual localization (`locales/en.json`, `locales/cs.json`), persisted user preference, system-locale fallback
  - `models.py` – Typed data models (`RectF`, `PointF`, annotations, crop, undo/redo command stack)
  - `presets.py` – PDF downsizing presets (referencing i18n keys)
  - `document.py` – PDF rendering (`pypdfium2`), non-destructive vector/overlay save, and **true irreversible redaction** (high-DPI raster bake that physically destroys underlying text/vectors/pixels)
  - `compressor.py` – PDF downsizing engine
  - `converter.py` – Silent background conversion to PDF (images, text, HTML, Office COM / LibreOffice fallback)
  - `registry.py` – Windows 10/11 `HKCU` context menu registration & uninstallation (no admin rights)
- `src/pdf_editor/ui/` – `PySide6` GUI layer (main editor window, interactive PDF canvas, setup dialog, progress toast, about dialog)
- `locales/` – Translation JSON files (`en.json`, `cs.json`). **Zero user-visible strings in Python code.**

## Key Commands
- Run all tests: `.\scripts\test.ps1`
- Build single distributable installer: `.\scripts\build.ps1` (outputs `dist\PdfEditor_Setup_v1.0.0.exe`, never committed to git)
- Run app in dev mode: `python run_app.py`

## Rules Reminder
1. Talk to the user in Czech; keep all code, comments, identifiers, docs, and commit messages in English.
2. Never hardcode user-visible strings in code — always use `i18n.t("key")` and keep `locales/en.json` and `locales/cs.json` in 100% key parity (verified by `tests/test_i18n.py`).
3. Never commit build artifacts (`dist/`, `build/`, `*.exe`).
