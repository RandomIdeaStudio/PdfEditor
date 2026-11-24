"""PySide6 graphical user interface layer for PdfEditor."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def load_app_icon() -> QIcon:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "app.ico")
    candidates.append(Path(__file__).resolve().parents[3] / "assets" / "app.ico")
    for path in candidates:
        if path.exists():
            return QIcon(str(path))
    return QIcon()
