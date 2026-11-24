"""Domain models for PDF editing operations and undo/redo history.

All coordinates are normalized to [0.0, 1.0] relative to the page width and height
(top-left origin: x=0 left, y=0 top). This makes annotations resolution-independent
across zoom levels and high-DPI save/redaction rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

AVAILABLE_FONTS: tuple[str, ...] = (
    "Segoe UI",
    "Arial",
    "Calibri",
    "Times New Roman",
    "Consolas",
    "Georgia",
    "Tahoma",
    "Verdana",
)


class ToolKind(str, Enum):
    PAN = "pan"
    CROP = "crop"
    RECT = "rect"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"
    LINE = "line"
    ARROW = "arrow"
    HIGHLIGHT = "highlight"
    TEXT = "text"
    REDACT_BLACK = "redact_black"
    REDACT_WHITE = "redact_white"


@dataclass(frozen=True)
class RectNorm:
    """Normalized rectangle (0..1) in top-left origin coordinates."""

    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self) -> RectNorm:
        left = max(0.0, min(1.0, min(self.x0, self.x1)))
        right = max(0.0, min(1.0, max(self.x0, self.x1)))
        top = max(0.0, min(1.0, min(self.y0, self.y1)))
        bottom = max(0.0, min(1.0, max(self.y0, self.y1)))
        return RectNorm(left, top, right, bottom)

    @property
    def width(self) -> float:
        r = self.normalized()
        return r.x1 - r.x0

    @property
    def height(self) -> float:
        r = self.normalized()
        return r.y1 - r.y0


@dataclass(frozen=True)
class AnnotationItem:
    """Single visual or destructive edit placed on a PDF page."""

    kind: Literal[
        "rect",
        "ellipse",
        "polygon",
        "line",
        "arrow",
        "highlight",
        "text",
        "redact_black",
        "redact_white",
    ]
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    points: tuple[tuple[float, float], ...] = ()
    color: str = "#D1242F"
    filled: bool = False
    fill_color: str = "#FEE2E2"
    stroke_width: float = 3.0
    text: str = ""
    font_family: str = "Segoe UI"
    font_size: float = 16.0
    bold: bool = False
    italic: bool = False
    underline: bool = False

    @property
    def is_redaction(self) -> bool:
        return self.kind in ("redact_black", "redact_white")

    def rect(self) -> RectNorm:
        return RectNorm(self.x0, self.y0, self.x1, self.y1).normalized()


@dataclass
class PageEdits:
    """Mutable collection of edits for a single 0-based page index."""

    annotations: list[AnnotationItem] = field(default_factory=list)
    crop: RectNorm | None = None

    @property
    def has_redactions(self) -> bool:
        return any(item.is_redaction for item in self.annotations)

    @property
    def is_empty(self) -> bool:
        return not self.annotations and self.crop is None


@dataclass(frozen=True)
class _HistoryEntry:
    page_index: int
    action: Literal["add_annotation", "set_crop", "clear_page"]
    annotation: AnnotationItem | None = None
    previous_crop: RectNorm | None = None
    new_crop: RectNorm | None = None
    previous_annotations: tuple[AnnotationItem, ...] = ()


class DocumentEditSession:
    """Tracks per-page edits and supports full Undo / Redo."""

    def __init__(self) -> None:
        self._pages: dict[int, PageEdits] = {}
        self._undo_stack: list[_HistoryEntry] = []
        self._redo_stack: list[_HistoryEntry] = []
        self._dirty: bool = False

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def page_edits(self, page_index: int) -> PageEdits:
        return self._pages.setdefault(page_index, PageEdits())

    def all_edited_pages(self) -> dict[int, PageEdits]:
        return {idx: edits for idx, edits in self._pages.items() if not edits.is_empty}

    def has_any_redactions(self) -> bool:
        return any(edits.has_redactions for edits in self._pages.values())

    def add_annotation(self, page_index: int, item: AnnotationItem) -> None:
        self.page_edits(page_index).annotations.append(item)
        self._undo_stack.append(
            _HistoryEntry(page_index=page_index, action="add_annotation", annotation=item)
        )
        self._redo_stack.clear()
        self._dirty = True

    def set_crop(self, page_index: int, crop: RectNorm | None) -> None:
        edits = self.page_edits(page_index)
        prev = edits.crop
        normalized = crop.normalized() if crop is not None else None
        edits.crop = normalized
        self._undo_stack.append(
            _HistoryEntry(
                page_index=page_index,
                action="set_crop",
                previous_crop=prev,
                new_crop=normalized,
            )
        )
        self._redo_stack.clear()
        self._dirty = True

    def clear_page(self, page_index: int) -> None:
        edits = self.page_edits(page_index)
        if edits.is_empty:
            return
        prev_annots = tuple(edits.annotations)
        prev_crop = edits.crop
        edits.annotations.clear()
        edits.crop = None
        self._undo_stack.append(
            _HistoryEntry(
                page_index=page_index,
                action="clear_page",
                previous_crop=prev_crop,
                previous_annotations=prev_annots,
            )
        )
        self._redo_stack.clear()
        self._dirty = True

    def undo(self) -> int | None:
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        edits = self.page_edits(entry.page_index)
        if entry.action == "add_annotation" and edits.annotations:
            edits.annotations.pop()
        elif entry.action == "set_crop":
            edits.crop = entry.previous_crop
        elif entry.action == "clear_page":
            edits.annotations = list(entry.previous_annotations)
            edits.crop = entry.previous_crop
        self._redo_stack.append(entry)
        self._dirty = bool(self._undo_stack)
        return entry.page_index

    def redo(self) -> int | None:
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        edits = self.page_edits(entry.page_index)
        if entry.action == "add_annotation" and entry.annotation is not None:
            edits.annotations.append(entry.annotation)
        elif entry.action == "set_crop":
            edits.crop = entry.new_crop
        elif entry.action == "clear_page":
            edits.annotations.clear()
            edits.crop = None
        self._undo_stack.append(entry)
        self._dirty = True
        return entry.page_index

    def reset(self) -> None:
        self._pages.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._dirty = False

    def mark_saved(self) -> None:
        self.reset()
