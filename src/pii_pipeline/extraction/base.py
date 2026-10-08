"""Shared types for the extraction module.

Security rule for this whole module: error messages, warnings and ``BlockMeta``
may mention the file name, a location, a code and a reason, but NEVER any text
taken from the document. Extracted text only ever leaves through ``TextBlock``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from pii_pipeline.schemas import TextBlock

#: (x0, y0, x1, y1). Units are given separately (see ``BlockMeta.bbox_unit``).
BBox = tuple[float, float, float, float]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ExtractionError(Exception):
    """Base class for every error raised by the extraction module."""


class UnsupportedFileError(ExtractionError):
    """The file type is not supported (or is encrypted / legacy binary)."""


class OCRUnavailableError(ExtractionError):
    """OCR is needed but the local Tesseract engine cannot be found."""


# --------------------------------------------------------------------------
# Warnings
# --------------------------------------------------------------------------
class ExtractionWarningCategory(UserWarning):
    """Category used with ``warnings.warn`` by :func:`extract_document`."""


@dataclass(frozen=True)
class ExtractionWarning:
    """Something suspicious that did not stop extraction. Never contains text."""

    code: str
    file: str
    location: str
    detail: str = ""

    def __str__(self) -> str:
        suffix = f": {self.detail}" if self.detail else ""
        return f"[{self.code}] {self.file} @ {self.location}{suffix}"


# --------------------------------------------------------------------------
# Internal block model
# --------------------------------------------------------------------------
@dataclass
class Piece:
    """One fragment of a block's text.

    ``kind``:
      * ``"text"``  ordinary text (normalized before joining)
      * ``"label"`` injected context such as a table header ``"Name"``
      * ``"sep"``   a separator such as ``" | "`` or ``": "`` (kept verbatim)

    ``col`` marks the piece as (part of) a table cell value, ``bbox``/``conf``
    mark it as a positioned word (OCR or PDF text layer).
    """

    text: str
    kind: str = "text"
    col: int | None = None
    bbox: BBox | None = None
    conf: float | None = None


@dataclass
class RawBlock:
    """A block as produced by a format extractor, before assembly."""

    kind: str
    location: str
    pieces: list[Piece]
    source: str = "native"          # "native" | "ocr" | "xml"
    page: int | None = None         # 1-based page or slide number
    hidden: bool = False
    bbox: BBox | None = None
    bbox_unit: str | None = None    # "pt" | "px" | "emu"
    ocr_confidence: float | None = None
    table_id: int | None = None
    row_index: int | None = None

    @classmethod
    def simple(cls, kind: str, location: str, text: str, **kwargs) -> "RawBlock":
        return cls(kind=kind, location=location, pieces=[Piece(text)], **kwargs)


# --------------------------------------------------------------------------
# Public result types
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BlockMeta:
    """Positional metadata for one ``TextBlock``. Holds no document text.

    ``cells``: ``(column, start, end)`` spans of table cell values inside the
    block text. ``words``: ``(start, end, bbox, confidence)`` for positioned
    words (confidence is None for text-layer words). All offsets refer to the
    final ``TextBlock.text`` (end exclusive).
    """

    index: int
    kind: str
    source: str
    page: int | None = None
    hidden: bool = False
    bbox: BBox | None = None
    bbox_unit: str | None = None
    table_id: int | None = None
    row_index: int | None = None
    cells: tuple[tuple[int, int, int], ...] = ()
    words: tuple[tuple[int, int, BBox, float | None], ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
    """Everything extracted from one file."""

    file: str
    blocks: tuple[TextBlock, ...]
    meta: tuple[BlockMeta, ...]
    warnings: tuple[ExtractionWarning, ...] = ()

    def __iter__(self) -> Iterator[TextBlock]:
        return iter(self.blocks)

    def __len__(self) -> int:
        return len(self.blocks)

    def __repr__(self) -> str:
        return (
            f"ExtractionResult(file={self.file!r}, blocks={len(self.blocks)}, "
            f"warnings={len(self.warnings)})"
        )


# --------------------------------------------------------------------------
# Extraction context
# --------------------------------------------------------------------------
@dataclass
class Context:
    """Per-file state shared by all extractors."""

    file: str
    warnings: list[ExtractionWarning] = field(default_factory=list)
    # Aggregated skipped-image reasons, reported as one warning per file.
    skipped_images: dict[str, int] = field(default_factory=dict)
    _table_counter: int = 0

    def next_table_id(self) -> int:
        """File-wide unique table id (1, 2, 3, ...)."""
        self._table_counter += 1
        return self._table_counter

    def warn(self, code: str, location: str, detail: str = "") -> None:
        self.warnings.append(ExtractionWarning(code, self.file, location, detail))

    def skip_image(self, reason: str) -> None:
        self.skipped_images[reason] = self.skipped_images.get(reason, 0) + 1
