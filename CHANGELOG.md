# Changelog

All notable changes to PdfEditor are documented in this file.

## [1.0.0] - 2026-11-24
### Added
- PySide6 desktop PDF editor with zoom, page navigation, Undo/Redo, Save (`Ctrl+S`), and Save As (`Ctrl+Shift+S`).
- Editing tools: Crop, Rectangle, Ellipse, Line, Arrow, Highlighter, Text (with Czech diacritics), and True Irreversible Redaction (Blackout & Whiteout).
- Built-in PDF Downsizing engine with 3 presets (Email, Balanced, High Quality).
- Silent background conversion to PDF for images, text, HTML, and Office documents (MS Office COM / LibreOffice fallback).
- Single-file Windows 10 & 11 installer with `HKCU` right-click context menu integration (Edit in PdfEditor, Downsize PDF submenu, Convert to PDF).
- Full multilingual support (`cs`, `en`) loaded from `locales/*.json` with automated key-parity tests.
