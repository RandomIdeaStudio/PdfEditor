"""Main PySide6 window for PdfEditor."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.compressor import compress_pdf, format_size
from ..core.converter import CONVERTIBLE_EXTENSIONS, convert_to_pdf, is_convertible
from ..core.document import PdfDocumentService
from ..core.i18n import get_i18n, t
from ..core.models import AnnotationItem, DocumentEditSession, RectNorm, ToolKind
from ..core.presets import PRESETS
from . import load_app_icon
from .about_dialog import AboutDialog
from .canvas import PdfCanvasWidget
from .setup_dialog import SetupDialog


class MainWindow(QMainWindow):
    """Primary PDF editor window with integrated downsizing and file conversion."""

    def __init__(self, initial_file: Path | None = None) -> None:
        super().__init__()
        self._doc = PdfDocumentService()
        self._session = DocumentEditSession()
        self._page_index: int = 0
        self._zoom: float = 1.0
        self._active_color: str = "#D1242F"

        self.setWindowIcon(load_app_icon())
        self.resize(1180, 820)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menus()
        self._build_toolbars()
        self._retranslate_ui()
        self._update_controls_state()

        if initial_file is not None:
            self.open_path(initial_file)

    # ------------------------------------------------------------------ UI setup

    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Page 0: Empty welcome state
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.setSpacing(14)

        self._empty_headline = QLabel()
        self._empty_headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_headline.setStyleSheet("font-size: 22px; font-weight: 700; color: #1F2328;")
        welcome_layout.addWidget(self._empty_headline)

        self._empty_subtext = QLabel()
        self._empty_subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_subtext.setStyleSheet("font-size: 13px; color: #59636E;")
        welcome_layout.addWidget(self._empty_subtext)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(10)

        self._empty_open_btn = QPushButton()
        self._empty_open_btn.setStyleSheet(
            "QPushButton { background: #D1242F; color: #FFFFFF; font-weight: 600; "
            "padding: 10px 20px; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #A40E26; }"
        )
        self._empty_open_btn.clicked.connect(self._on_open_pdf)
        btn_row.addWidget(self._empty_open_btn)

        self._empty_convert_btn = QPushButton()
        self._empty_convert_btn.setStyleSheet("QPushButton { padding: 10px 18px; }")
        self._empty_convert_btn.clicked.connect(self._on_convert_file)
        btn_row.addWidget(self._empty_convert_btn)

        self._empty_setup_btn = QPushButton()
        self._empty_setup_btn.setStyleSheet("QPushButton { padding: 10px 18px; }")
        self._empty_setup_btn.clicked.connect(self._on_open_setup)
        btn_row.addWidget(self._empty_setup_btn)

        welcome_layout.addLayout(btn_row)
        self._stack.addWidget(welcome)

        # Page 1: Scrollable PDF canvas
        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet("QScrollArea { background: #E5E7EB; border: none; }")
        self._canvas = PdfCanvasWidget()
        self._canvas.annotation_created.connect(self._on_annotation_created)
        self._canvas.crop_selected.connect(self._on_crop_selected)
        self._canvas.zoom_requested.connect(self._on_zoom_factor)
        self._scroll.setWidget(self._canvas)
        self._stack.addWidget(self._scroll)

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File menu
        self._menu_file = mb.addMenu("")
        self._act_open = QAction(self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.triggered.connect(self._on_open_pdf)
        self._menu_file.addAction(self._act_open)

        self._act_save = QAction(self)
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.triggered.connect(self._on_save)
        self._menu_file.addAction(self._act_save)

        self._act_save_as = QAction(self)
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.triggered.connect(self._on_save_as)
        self._menu_file.addAction(self._act_save_as)

        self._menu_file.addSeparator()

        self._act_convert = QAction(self)
        self._act_convert.triggered.connect(self._on_convert_file)
        self._menu_file.addAction(self._act_convert)

        self._menu_file.addSeparator()

        self._act_exit = QAction(self)
        self._act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_exit.triggered.connect(self.close)
        self._menu_file.addAction(self._act_exit)

        # Edit menu
        self._menu_edit = mb.addMenu("")
        self._act_undo = QAction(self)
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_undo.triggered.connect(self._on_undo)
        self._menu_edit.addAction(self._act_undo)

        self._act_redo = QAction(self)
        self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._act_redo.triggered.connect(self._on_redo)
        self._menu_edit.addAction(self._act_redo)

        self._menu_edit.addSeparator()

        self._act_clear_page = QAction(self)
        self._act_clear_page.triggered.connect(self._on_clear_page)
        self._menu_edit.addAction(self._act_clear_page)

        # Tools menu
        self._menu_tools = mb.addMenu("")
        self._downsize_actions: list[tuple[str, QAction]] = []
        for preset in PRESETS:
            act = QAction(self)
            act.triggered.connect(lambda _checked=False, k=preset.key: self._on_downsize_current(k))
            self._menu_tools.addAction(act)
            self._downsize_actions.append((preset.key, act))

        self._menu_tools.addSeparator()

        self._act_windows_integration = QAction(self)
        self._act_windows_integration.triggered.connect(self._on_open_setup)
        self._menu_tools.addAction(self._act_windows_integration)

        # Language menu
        self._menu_lang = mb.addMenu("")
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)
        self._act_lang_cs = QAction(self)
        self._act_lang_cs.setCheckable(True)
        self._act_lang_cs.triggered.connect(lambda: self._on_switch_language("cs"))
        self._lang_group.addAction(self._act_lang_cs)
        self._menu_lang.addAction(self._act_lang_cs)

        self._act_lang_en = QAction(self)
        self._act_lang_en.setCheckable(True)
        self._act_lang_en.triggered.connect(lambda: self._on_switch_language("en"))
        self._lang_group.addAction(self._act_lang_en)
        self._menu_lang.addAction(self._act_lang_en)

        # Help menu
        self._menu_help = mb.addMenu("")
        self._act_about = QAction(self)
        self._act_about.triggered.connect(self._on_about)
        self._menu_help.addAction(self._act_about)

    def _build_toolbars(self) -> None:
        # Drawing tools toolbar
        self._tools_bar = QToolBar()
        self._tools_bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._tools_bar)

        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions: dict[ToolKind, QAction] = {}

        tool_order = [
            ToolKind.PAN,
            ToolKind.CROP,
            ToolKind.RECT,
            ToolKind.ELLIPSE,
            ToolKind.LINE,
            ToolKind.ARROW,
            ToolKind.HIGHLIGHT,
            ToolKind.TEXT,
            ToolKind.REDACT_BLACK,
            ToolKind.REDACT_WHITE,
        ]
        for kind in tool_order:
            act = QAction(self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, k=kind: self._select_tool(k))
            self._tool_group.addAction(act)
            self._tools_bar.addAction(act)
            self._tool_actions[kind] = act
            if kind in (ToolKind.CROP, ToolKind.TEXT):
                self._tools_bar.addSeparator()

        self._tool_actions[ToolKind.PAN].setChecked(True)

        # Properties & navigation toolbar
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self._props_bar = QToolBar()
        self._props_bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._props_bar)

        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._on_pick_color)
        self._update_color_button_style()
        self._props_bar.addWidget(self._color_btn)

        self._props_bar.addSeparator()

        self._stroke_lbl = QLabel()
        self._stroke_lbl.setContentsMargins(6, 0, 4, 0)
        self._props_bar.addWidget(self._stroke_lbl)

        self._stroke_spin = QSpinBox()
        self._stroke_spin.setRange(1, 24)
        self._stroke_spin.setValue(3)
        self._stroke_spin.valueChanged.connect(lambda v: self._canvas.set_stroke_width(float(v)))
        self._props_bar.addWidget(self._stroke_spin)

        self._font_lbl = QLabel()
        self._font_lbl.setContentsMargins(10, 0, 4, 0)
        self._props_bar.addWidget(self._font_lbl)

        self._font_spin = QSpinBox()
        self._font_spin.setRange(8, 72)
        self._font_spin.setValue(16)
        self._font_spin.valueChanged.connect(lambda v: self._canvas.set_font_size(float(v)))
        self._props_bar.addWidget(self._font_spin)

        self._props_bar.addSeparator()

        self._act_prev_page = QAction(self)
        self._act_prev_page.triggered.connect(self._on_prev_page)
        self._props_bar.addAction(self._act_prev_page)

        self._page_lbl = QLabel()
        self._page_lbl.setContentsMargins(8, 0, 8, 0)
        self._props_bar.addWidget(self._page_lbl)

        self._act_next_page = QAction(self)
        self._act_next_page.triggered.connect(self._on_next_page)
        self._props_bar.addAction(self._act_next_page)

        self._props_bar.addSeparator()

        self._act_zoom_out = QAction(self)
        self._act_zoom_out.triggered.connect(lambda: self._on_zoom_factor(1.0 / 1.15))
        self._props_bar.addAction(self._act_zoom_out)

        self._act_zoom_fit = QAction(self)
        self._act_zoom_fit.triggered.connect(self._on_zoom_fit)
        self._props_bar.addAction(self._act_zoom_fit)

        self._act_zoom_in = QAction(self)
        self._act_zoom_in.triggered.connect(lambda: self._on_zoom_factor(1.15))
        self._props_bar.addAction(self._act_zoom_in)

    def _retranslate_ui(self) -> None:
        self._update_window_title()

        self._menu_file.setTitle(t("menu.file"))
        self._act_open.setText(t("menu.file.open"))
        self._act_save.setText(t("menu.file.save"))
        self._act_save_as.setText(t("menu.file.save_as"))
        self._act_convert.setText(t("menu.file.convert_to_pdf"))
        self._act_exit.setText(t("menu.file.exit"))

        self._menu_edit.setTitle(t("menu.edit"))
        self._act_undo.setText(t("menu.edit.undo"))
        self._act_redo.setText(t("menu.edit.redo"))
        self._act_clear_page.setText(t("menu.edit.clear_page"))

        self._menu_tools.setTitle(t("menu.tools"))
        preset_map = {p.key: p for p in PRESETS}
        for key, act in self._downsize_actions:
            act.setText(t("menu.tools.downsize_preset", preset=preset_map[key].label))
        self._act_windows_integration.setText(t("menu.tools.windows_integration"))

        self._menu_lang.setTitle(t("menu.language"))
        self._act_lang_cs.setText(t("menu.language.cs"))
        self._act_lang_en.setText(t("menu.language.en"))
        current_lang = get_i18n().language
        self._act_lang_cs.setChecked(current_lang == "cs")
        self._act_lang_en.setChecked(current_lang == "en")

        self._menu_help.setTitle(t("menu.help"))
        self._act_about.setText(t("menu.help.about"))

        for kind, act in self._tool_actions.items():
            act.setText(t(f"tool.{kind.value}"))
            act.setToolTip(t(f"tool.{kind.value}.tip"))

        self._color_btn.setText(t("toolbar.color"))
        self._stroke_lbl.setText(t("toolbar.stroke"))
        self._font_lbl.setText(t("toolbar.font_size"))
        self._act_prev_page.setText(t("toolbar.prev_page"))
        self._act_next_page.setText(t("toolbar.next_page"))
        self._act_zoom_out.setText(t("toolbar.zoom_out"))
        self._act_zoom_fit.setText(t("toolbar.zoom_fit"))
        self._act_zoom_in.setText(t("toolbar.zoom_in"))

        self._empty_headline.setText(t("empty.headline"))
        self._empty_subtext.setText(t("empty.subtext"))
        self._empty_open_btn.setText(t("empty.open_button"))
        self._empty_convert_btn.setText(t("empty.convert_button"))
        self._empty_setup_btn.setText(t("empty.setup_button"))

        self._update_page_indicator()
        if not self._doc.is_open:
            self.statusBar().showMessage(t("status.ready"))

    # ------------------------------------------------------------------ State helpers

    def _update_window_title(self) -> None:
        if self._doc.is_open and self._doc.path is not None:
            key = "app.title_with_file_dirty" if self._session.is_dirty else "app.title_with_file"
            self.setWindowTitle(t(key, filename=self._doc.path.name))
        else:
            self.setWindowTitle(t("app.title"))

    def _update_page_indicator(self) -> None:
        if self._doc.is_open:
            self._page_lbl.setText(
                t("toolbar.page_indicator", current=self._page_index + 1, total=self._doc.page_count)
            )
        else:
            self._page_lbl.setText(t("toolbar.no_document"))

    def _update_controls_state(self) -> None:
        opened = self._doc.is_open
        self._stack.setCurrentIndex(1 if opened else 0)
        self._act_save.setEnabled(opened)
        self._act_save_as.setEnabled(opened)
        self._act_undo.setEnabled(opened and self._session.can_undo)
        self._act_redo.setEnabled(opened and self._session.can_redo)
        self._act_clear_page.setEnabled(
            opened and not self._session.page_edits(self._page_index).is_empty
        )
        for _key, act in self._downsize_actions:
            act.setEnabled(opened)
        self._act_prev_page.setEnabled(opened and self._page_index > 0)
        self._act_next_page.setEnabled(opened and self._page_index < self._doc.page_count - 1)
        self._act_zoom_in.setEnabled(opened)
        self._act_zoom_out.setEnabled(opened)
        self._act_zoom_fit.setEnabled(opened)
        self._update_page_indicator()
        self._update_window_title()

    def _update_color_button_style(self) -> None:
        c = QColor(self._active_color)
        luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        text_color = "#1F2328" if luminance > 155 else "#FFFFFF"
        self._color_btn.setStyleSheet(
            f"QPushButton {{ background: {self._active_color}; color: {text_color}; "
            "font-weight: 600; padding: 4px 12px; border-radius: 4px; border: 1px solid #9CA3AF; }}"
        )

    def _render_current_page(self) -> None:
        if not self._doc.is_open:
            self._canvas.clear_page()
            return
        dpi = max(48.0, min(320.0, 110.0 * self._zoom))
        pil_img = self._doc.render_page(self._page_index, dpi=dpi)
        self._canvas.set_page_image(
            pil_img, self._session.page_edits(self._page_index), self._zoom
        )
        self._update_controls_state()

    def _confirm_discard_unsaved(self) -> bool:
        if not self._session.is_dirty or not self._doc.is_open or self._doc.path is None:
            return True
        reply = QMessageBox.question(
            self,
            t("dialog.unsaved.title"),
            t("dialog.unsaved.message", filename=self._doc.path.name),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self._on_save()
        return reply == QMessageBox.StandardButton.Discard

    # ------------------------------------------------------------------ Actions

    def open_path(self, path: Path) -> None:
        if not self._confirm_discard_unsaved():
            return
        try:
            if path.suffix.lower() != ".pdf" and is_convertible(path):
                res = convert_to_pdf(path)
                self.statusBar().showMessage(
                    t("status.converted", filename=res.output_path.name, size=format_size(res.output_bytes))
                )
                path = res.output_path

            pages = self._doc.open(path)
            self._session.reset()
            self._page_index = 0
            self._zoom = 1.0
            self._render_current_page()
            self.statusBar().showMessage(t("status.opened", filename=path.name, pages=pages))
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))

    def _on_open_pdf(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            t("dialog.open_pdf.title"),
            "",
            t("dialog.open_pdf.filter"),
        )
        if selected:
            self.open_path(Path(selected))

    def _on_save(self) -> bool:
        if not self._doc.is_open or self._doc.path is None:
            return False
        had_redactions = self._session.has_any_redactions()
        try:
            saved = self._doc.save(self._session)
            self._page_index = min(self._page_index, max(0, self._doc.page_count - 1))
            self._render_current_page()
            key = "status.saved_redacted" if had_redactions else "status.saved"
            self.statusBar().showMessage(t(key, filename=saved.name))
            return True
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))
            return False

    def _on_save_as(self) -> bool:
        if not self._doc.is_open or self._doc.path is None:
            return False
        selected, _ = QFileDialog.getSaveFileName(
            self,
            t("dialog.save_pdf.title"),
            str(self._doc.path),
            t("dialog.open_pdf.filter"),
        )
        if not selected:
            return False
        had_redactions = self._session.has_any_redactions()
        try:
            saved = self._doc.save(self._session, output_path=Path(selected))
            self._page_index = min(self._page_index, max(0, self._doc.page_count - 1))
            self._render_current_page()
            key = "status.saved_redacted" if had_redactions else "status.saved"
            self.statusBar().showMessage(t(key, filename=saved.name))
            return True
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))
            return False

    def _on_convert_file(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in CONVERTIBLE_EXTENSIONS)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            t("dialog.convert.title"),
            "",
            t("dialog.convert.filter", patterns=patterns),
        )
        if selected:
            self.open_path(Path(selected))

    def _on_downsize_current(self, preset_key: str) -> None:
        if not self._doc.is_open or self._doc.path is None:
            return
        if self._session.is_dirty:
            if not self._confirm_discard_unsaved():
                return
        try:
            res = compress_pdf(self._doc.path, preset_key=preset_key)
            self.statusBar().showMessage(
                t(
                    "status.downsized",
                    filename=res.output_path.name,
                    orig=format_size(res.original_bytes),
                    new=format_size(res.compressed_bytes),
                    pct=f"{res.saved_percent:.0f}",
                )
            )
            QMessageBox.information(
                self,
                t("toast.downsized_title"),
                t(
                    "toast.downsized_detail",
                    filename=res.output_path.name,
                    orig=format_size(res.original_bytes),
                    new=format_size(res.compressed_bytes),
                    pct=f"{res.saved_percent:.0f}",
                ),
            )
        except Exception as exc:
            QMessageBox.critical(self, t("error.title"), t("error.generic", detail=str(exc)))

    def _select_tool(self, kind: ToolKind) -> None:
        self._canvas.set_tool(kind)

    def _on_pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._active_color), self, t("dialog.color.title"))
        if chosen.isValid():
            self._active_color = chosen.name()
            self._canvas.set_color(self._active_color)
            self._update_color_button_style()

    def _on_annotation_created(self, item: AnnotationItem) -> None:
        self._session.add_annotation(self._page_index, item)
        self._canvas.set_edits(self._session.page_edits(self._page_index))
        self._update_controls_state()
        if item.is_redaction:
            self.statusBar().showMessage(t("status.redaction_added"))

    def _on_crop_selected(self, crop: RectNorm) -> None:
        self._session.set_crop(self._page_index, crop)
        self._canvas.set_edits(self._session.page_edits(self._page_index))
        self._update_controls_state()
        self.statusBar().showMessage(t("status.crop_applied", page=self._page_index + 1))

    def _on_undo(self) -> None:
        changed_page = self._session.undo()
        if changed_page is not None:
            self._page_index = changed_page
            self._render_current_page()

    def _on_redo(self) -> None:
        changed_page = self._session.redo()
        if changed_page is not None:
            self._page_index = changed_page
            self._render_current_page()

    def _on_clear_page(self) -> None:
        self._session.clear_page(self._page_index)
        self._render_current_page()

    def _on_prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._render_current_page()

    def _on_next_page(self) -> None:
        if self._doc.is_open and self._page_index < self._doc.page_count - 1:
            self._page_index += 1
            self._render_current_page()

    def _on_zoom_factor(self, factor: float) -> None:
        if not self._doc.is_open:
            return
        self._zoom = max(0.35, min(3.0, self._zoom * factor))
        self._render_current_page()

    def _on_zoom_fit(self) -> None:
        if not self._doc.is_open:
            return
        w_pt, _h_pt = self._doc.get_page_size_pt(self._page_index)
        viewport_w = max(200, self._scroll.viewport().width() - 40)
        base_px_at_1 = w_pt * (110.0 / 72.0)
        self._zoom = max(0.35, min(3.0, viewport_w / max(1.0, base_px_at_1)))
        self._render_current_page()

    def _on_switch_language(self, lang: str) -> None:
        if get_i18n().language == lang:
            return
        get_i18n().set_language(lang, persist=True)
        self._retranslate_ui()
        QMessageBox.information(
            self,
            t("dialog.language_changed.title"),
            t("dialog.language_changed.message"),
        )

    def _on_open_setup(self) -> None:
        dlg = SetupDialog(self, show_open_editor=False)
        dlg.exec()

    def _on_about(self) -> None:
        dlg = AboutDialog(self)
        dlg.exec()

    # ------------------------------------------------------------------ Drag & drop / Close

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.open_path(Path(local))
                break

    def closeEvent(self, event) -> None:
        if not self._confirm_discard_unsaved():
            event.ignore()
            return
        self._doc.close()
        event.accept()
