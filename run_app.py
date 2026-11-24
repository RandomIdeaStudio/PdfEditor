"""Entry script for development execution and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pdf_editor.main import main

if __name__ == "__main__":
    sys.exit(main())
