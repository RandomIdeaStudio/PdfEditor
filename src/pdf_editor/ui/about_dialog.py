"""About dialog displaying version, copyright, and third-party notices."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import VERSION
from ..core.i18n import t
from . import load_app_icon


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("about.title"))
        self.setWindowIcon(load_app_icon())
        self.setFixedWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title_lbl = QLabel(t("app.name"))
        title_lbl.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title_lbl)

        ver_lbl = QLabel(t("about.version", version=VERSION))
        ver_lbl.setStyleSheet("color: #59636E;")
        layout.addWidget(ver_lbl)

        desc_lbl = QLabel(t("about.description"))
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        copy_lbl = QLabel(t("about.copyright"))
        copy_lbl.setStyleSheet("color: #59636E;")
        layout.addWidget(copy_lbl)

        privacy_lbl = QLabel(t("about.privacy"))
        privacy_lbl.setWordWrap(True)
        layout.addWidget(privacy_lbl)

        lic_header = QLabel(t("about.licenses_header"))
        lic_header.setStyleSheet("font-weight: 600; margin-top: 6px;")
        layout.addWidget(lic_header)

        lic_body = QLabel(t("about.licenses_body"))
        lic_body.setWordWrap(True)
        lic_body.setStyleSheet("color: #374151;")
        layout.addWidget(lic_body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
