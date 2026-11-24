"""Application entry point for PdfEditor (CLI, context menu tasks, setup, and GUI editor)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, VERSION
from .core.compressor import compress_pdf, format_size
from .core.converter import convert_to_pdf, is_convertible
from .core.i18n import t
from .core.presets import DEFAULT_PRESET_KEY, PRESETS_BY_KEY
from .core.registry import get_install_status, install_app, is_frozen, uninstall_app


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Standalone PDF Editor, PDF Downsizer, and silent converter to PDF.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to a PDF to edit/downsize or a supported file to convert to PDF.",
    )
    parser.add_argument(
        "--preset",
        choices=list(PRESETS_BY_KEY.keys()),
        default=None,
        help="Downsize the input PDF using the specified preset.",
    )
    parser.add_argument(
        "--convert",
        action="store_true",
        help="Silently convert the input file to PDF.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path for silent CLI operations.",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Run without GUI (console output only).",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Open the Windows right-click integration setup window.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install PdfEditor into HKCU Windows context menus.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove PdfEditor from Windows context menus and uninstall.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current Windows installation status.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {VERSION}",
    )
    return parser


def _ensure_qt_app():
    from PySide6.QtWidgets import QApplication
    from .ui import load_app_icon

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(load_app_icon())
    return app


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.status:
        st = get_install_status()
        print(f"installed={st.installed}")
        print(f"install_dir={st.install_dir}")
        if st.registered_command:
            print(f"command={st.registered_command}")
        return 0

    if args.install:
        st = install_app()
        if args.silent:
            print(f"installed={st.installed_exe}")
            return 0
        from PySide6.QtWidgets import QMessageBox

        _ensure_qt_app()
        QMessageBox.information(
            None,
            t("setup.msg.installed_title"),
            t("setup.msg.installed_body", path=str(st.installed_exe)),
        )
        return 0

    if args.uninstall:
        uninstall_app()
        if args.silent:
            print("uninstalled=true")
            return 0
        from PySide6.QtWidgets import QMessageBox

        _ensure_qt_app()
        QMessageBox.information(
            None,
            t("setup.msg.uninstalled_title"),
            t("setup.msg.uninstalled_body"),
        )
        return 0

    # Background downsizing from context menu or CLI
    if args.file and args.preset:
        input_path = Path(args.file)
        if args.silent:
            res = compress_pdf(
                input_path,
                preset_key=args.preset,
                output_path=args.output,
            )
            print(
                f"{res.output_path} | "
                f"{format_size(res.original_bytes)} -> {format_size(res.compressed_bytes)} "
                f"(-{res.saved_percent:.1f}%)"
            )
            return 0
        from .ui.toast import run_downsize_toast

        app = _ensure_qt_app()
        return run_downsize_toast(app, input_path, args.preset)

    # Background conversion to PDF from context menu or CLI
    if args.file and args.convert:
        input_path = Path(args.file)
        if args.silent:
            res = convert_to_pdf(input_path, output_path=args.output)
            print(f"{res.output_path} | {format_size(res.output_bytes)} ({res.engine})")
            return 0
        from .ui.toast import run_convert_toast

        app = _ensure_qt_app()
        return run_convert_toast(app, input_path)

    # Silent default fallback if --silent passed with a file
    if args.file and args.silent:
        input_path = Path(args.file)
        if input_path.suffix.lower() != ".pdf" and is_convertible(input_path):
            res = convert_to_pdf(input_path, output_path=args.output)
            print(f"{res.output_path} | {format_size(res.output_bytes)} ({res.engine})")
            return 0
        res = compress_pdf(
            input_path,
            preset_key=DEFAULT_PRESET_KEY,
            output_path=args.output,
        )
        print(
            f"{res.output_path} | "
            f"{format_size(res.original_bytes)} -> {format_size(res.compressed_bytes)}"
        )
        return 0

    app = _ensure_qt_app()

    # Dedicated setup mode, or first-run of a distributed Setup executable
    exe_name = Path(sys.executable).name.lower() if is_frozen() else ""
    first_run_setup = (
        args.setup
        or (
            not args.file
            and is_frozen()
            and "setup" in exe_name
            and not get_install_status().installed
        )
    )
    if first_run_setup:
        from .ui.setup_dialog import SetupDialog

        dlg = SetupDialog(show_open_editor=True)
        dlg.exec()
        if not dlg.open_editor_requested:
            return 0

    from .ui.main_window import MainWindow

    initial = Path(args.file) if args.file else None
    win = MainWindow(initial_file=initial)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
