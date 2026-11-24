"""Floating PySide6 progress & result toast for background context-menu tasks."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..core.compressor import CompressionResult, compress_pdf, format_size
from ..core.converter import ConversionResult, convert_to_pdf
from ..core.i18n import t
from ..core.presets import get_preset


class _DownsizeWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, preset_key: str) -> None:
        super().__init__()
        self._path = path
        self._preset_key = preset_key

    def run(self) -> None:
        try:
            res = compress_pdf(
                self._path,
                preset_key=self._preset_key,
                progress_callback=lambda c, tot: self.progress.emit(c, tot),
            )
            self.finished_ok.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ConvertWorker(QThread):
    status_key = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            res = convert_to_pdf(
                self._path,
                status_key_callback=lambda key: self.status_key.emit(key),
            )
            self.finished_ok.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class _FloatingToast(QWidget):
    def __init__(self, initial_title: str, initial_detail: str) -> None:
        super().__init__()
        self.exit_code = 0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFixedSize(390, 126)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #D0D7DE; border-radius: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self.title_lbl = QLabel(initial_title)
        self.title_lbl.setStyleSheet("border: none; font-size: 13px; font-weight: 700; color: #1F2328;")
        layout.addWidget(self.title_lbl)

        self.detail_lbl = QLabel(initial_detail)
        self.detail_lbl.setWordWrap(True)
        self.detail_lbl.setStyleSheet("border: none; font-size: 12px; color: #59636E;")
        layout.addWidget(self.detail_lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        outer.addWidget(card)
        self._position_bottom_right()

    def _position_bottom_right(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 20)

    def mousePressEvent(self, event) -> None:
        self.close()

    def show_success(self, title: str, detail: str, timeout_ms: int = 5500) -> None:
        self.bar.hide()
        self.title_lbl.setText(f"{title} ✓")
        self.title_lbl.setStyleSheet("border: none; font-size: 13px; font-weight: 700; color: #1A7F37;")
        self.detail_lbl.setText(detail)
        QTimer.singleShot(timeout_ms, self.close)

    def show_error(self, detail: str, timeout_ms: int = 9000) -> None:
        self.exit_code = 1
        self.bar.hide()
        self.title_lbl.setText(t("toast.error_title"))
        self.title_lbl.setStyleSheet("border: none; font-size: 13px; font-weight: 700; color: #D1242F;")
        self.detail_lbl.setText(detail)
        QTimer.singleShot(timeout_ms, self.close)


def run_downsize_toast(app: QApplication, input_path: Path, preset_key: str) -> int:
    preset = get_preset(preset_key)
    toast = _FloatingToast(
        t("toast.downsizing", preset=preset.short_label),
        input_path.name,
    )
    worker = _DownsizeWorker(input_path, preset.key)

    def on_progress(cur: int, tot: int) -> None:
        toast.detail_lbl.setText(
            t("toast.downsizing_page", filename=input_path.name, current=cur, total=tot)
        )

    def on_done(res: CompressionResult) -> None:
        orig_s = format_size(res.original_bytes)
        new_s = format_size(res.compressed_bytes)
        if res.saved_bytes > 0:
            detail = t(
                "toast.downsized_detail",
                filename=res.output_path.name,
                orig=orig_s,
                new=new_s,
                pct=f"{res.saved_percent:.0f}",
            )
        else:
            detail = t(
                "toast.downsized_already_optimal",
                filename=res.output_path.name,
                orig=orig_s,
            )
        toast.show_success(t("toast.downsized_title"), detail)

    worker.progress.connect(on_progress)
    worker.finished_ok.connect(on_done)
    worker.failed.connect(toast.show_error)

    toast.show()
    worker.start()
    app.exec()
    worker.wait()
    return toast.exit_code


def run_convert_toast(app: QApplication, input_path: Path) -> int:
    toast = _FloatingToast(t("toast.converting"), input_path.name)
    worker = _ConvertWorker(input_path)

    def on_status(key: str) -> None:
        toast.title_lbl.setText(t(key))

    def on_done(res: ConversionResult) -> None:
        toast.show_success(
            t("toast.converted_title"),
            t(
                "toast.converted_detail",
                filename=res.output_path.name,
                size=format_size(res.output_bytes),
            ),
        )

    worker.status_key.connect(on_status)
    worker.finished_ok.connect(on_done)
    worker.failed.connect(toast.show_error)

    toast.show()
    worker.start()
    app.exec()
    worker.wait()
    return toast.exit_code
