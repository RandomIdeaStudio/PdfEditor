# Changelog

All notable changes to PDF Editor are documented in this file.

## [1.0.0] - 2026-11-24
### Added
- PySide6 desktop PDF editor with continuous page scrolling, zoom, mouse panning, Undo/Redo, Save (`Ctrl+S`) and Save As (`Ctrl+Shift+S`).
- Editing tools: Crop, Rectangle, Ellipse, Custom Shape, Line, Arrow, Highlighter, Pen, Image stamp, Text box (with Czech diacritics), Select/move/delete, and True Irreversible Redaction (Blackout & Erase).
- Page management: rotate, insert, merge, move, delete, extract and watermark.
- Built-in PDF downsizing engine with 3 presets (Email, Balanced, High Quality).
- Silent background conversion to PDF for images, text, HTML and Office documents (MS Office COM / LibreOffice fallback).
- Single-file Windows 10 & 11 executable with `HKCU` right-click menu integration and an Installed apps uninstall entry.
- Czech and English UI loaded from `locales/*.json` with automated key-parity tests.
- Privacy policy (`PRIVACY.md`) and code signing policy; this release is not code-signed yet.
