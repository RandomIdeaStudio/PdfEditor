"""Windows 10 & 11 right-click context menu setup dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import t
from ..core.registry import get_install_status, install_app, uninstall_app
from . import load_app_icon


class SetupDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, show_open_editor: bool = False) -> None:
        super().__init__(parent)
        self.open_editor_requested = False
        self.setWindowTitle(t("setup.title"))
        self.setWindowIcon(load_app_icon())
        self.setFixedWidth(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel(t("app.name"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(t("setup.subtitle"))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #59636E;")
        layout.addWidget(subtitle)

        # Status card
        status_frame = QFrame()
        status_frame.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #D0D7DE; border-radius: 6px; }"
        )
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(6)

        self._badge = QLabel()
        self._badge.setStyleSheet("border: none; font-weight: 600; padding: 3px 8px; border-radius: 4px;")
        status_layout.addWidget(self._badge)

        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("border: none; color: #59636E; font-size: 12px;")
        status_layout.addWidget(self._detail)
        layout.addWidget(status_frame)

        # Features card
        feat_frame = QFrame()
        feat_frame.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #D0D7DE; border-radius: 6px; }"
        )
        feat_layout = QVBoxLayout(feat_frame)
        feat_layout.setContentsMargins(14, 12, 14, 12)
        feat_layout.setSpacing(6)

        feat_header = QLabel(t("setup.features.header"))
        feat_header.setStyleSheet("border: none; font-weight: 600;")
        feat_layout.addWidget(feat_header)

        feat_pdf = QLabel(
            t(
                "setup.features.pdf",
                edit=t("context_menu.edit"),
                downsize=t("context_menu.downsize"),
            )
        )
        feat_pdf.setWordWrap(True)
        feat_pdf.setStyleSheet("border: none; color: #1F2328;")
        feat_layout.addWidget(feat_pdf)

        feat_other = QLabel(
            t("setup.features.other", convert=t("context_menu.convert"))
        )
        feat_other.setWordWrap(True)
        feat_other.setStyleSheet("border: none; color: #1F2328;")
        feat_layout.addWidget(feat_other)
        layout.addWidget(feat_frame)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._install_btn = QPushButton()
        self._install_btn.setStyleSheet(
            "QPushButton { background: #D1242F; color: #FFFFFF; font-weight: 600; "
            "padding: 8px 16px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #A40E26; }"
        )
        self._install_btn.clicked.connect(self._on_install)
        btn_row.addWidget(self._install_btn, stretch=1)

        self._uninstall_btn = QPushButton(t("setup.btn.uninstall"))
        self._uninstall_btn.setStyleSheet("QPushButton { padding: 8px 14px; }")
        self._uninstall_btn.clicked.connect(self._on_uninstall)
        btn_row.addWidget(self._uninstall_btn)

        if show_open_editor:
            open_btn = QPushButton(t("setup.btn.open_editor"))
            open_btn.setStyleSheet("QPushButton { padding: 8px 14px; }")
            open_btn.clicked.connect(self._on_open_editor)
            btn_row.addWidget(open_btn)

        close_btn = QPushButton(t("setup.btn.close"))
        close_btn.setStyleSheet("QPushButton { padding: 8px 14px; }")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        self._refresh()

    def _refresh(self) -> None:
        status = get_install_status()
        if status.installed:
            self._badge.setText(f"● {t('setup.status.installed')}")
            self._badge.setStyleSheet(
                "border: none; background: #DAFBE1; color: #1A7F37; "
                "font-weight: 600; padding: 4px 8px; border-radius: 4px;"
            )
            self._detail.setText(
                f"{t('setup.status.location', path=str(status.installed_exe))}\n"
                f"{t('setup.status.hint')}"
            )
            self._install_btn.setText(t("setup.btn.reinstall"))
            self._uninstall_btn.setEnabled(True)
        else:
            self._badge.setText(f"○ {t('setup.status.not_installed')}")
            self._badge.setStyleSheet(
                "border: none; background: #FFF8C5; color: #9A6700; "
                "font-weight: 600; padding: 4px 8px; border-radius: 4px;"
            )
            self._detail.setText(
                f"{t('setup.status.location', path=str(status.installed_exe))}\n"
                f"{t('setup.status.hint')}"
            )
            self._install_btn.setText(t("setup.btn.install"))
            self._uninstall_btn.setEnabled(False)

    def _on_install(self) -> None:
        try:
            st = install_app()
            self._refresh()
            QMessageBox.information(
                self,
                t("setup.msg.installed_title"),
                t("setup.msg.installed_body", path=str(st.installed_exe)),
            )
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))

    def _on_uninstall(self) -> None:
        reply = QMessageBox.question(
            self,
            t("setup.title"),
            t("setup.msg.uninstall_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            uninstall_app()
            self._refresh()
            QMessageBox.information(
                self,
                t("setup.msg.uninstalled_title"),
                t("setup.msg.uninstalled_body"),
            )
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))

    def _on_open_editor(self) -> None:
        self.open_editor_requested = True
        self.accept()
