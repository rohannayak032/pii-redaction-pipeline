"""Turn table rows into blocks: one logical row per block, with header context.

A row is rendered as ``"Employee ID: EMP-00001 | Name: Jane Roe | Email: …"``
so that detection sees which column every value belongs to. Without a
detected header the row is ``"EMP-00001 | Jane Roe | …"``.

The header row itself is not emitted separately: its text appears as labels in
every data row. If header detection is wrong, that text is still extracted
(repeated in each row), so recall is never lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .base import BBox, Piece, RawBlock
from .normalize import clean

CELL_SEPARATOR = " | "
LABEL_SEPARATOR = ": "
MAX_HEADER_CELL_LENGTH = 40
_NOT_A_HEADER = re.compile(r"[\d@]")


@dataclass
class Cell:
    """One (deduplicated) cell. ``col`` is its first grid column."""

    col: int
    text: str = ""
    words: list[Piece] = field(default_factory=list)   # positioned words, if any
    bbox: BBox | None = None
    conf: float | None = None


def looks_like_header(row: list[Cell]) -> bool:
    """Heuristic: short, distinct, non-numeric, no ``@``, at least 2 values."""
    values = [clean(c.text) for c in row if clean(c.text)]
    if len(values) < 2 or len(set(values)) != len(values):
        return False
    return all(len(v) <= MAX_HEADER_CELL_LENGTH and not _NOT_A_HEADER.search(v) for v in values)


def choose_header_rows(rows: list[list[Cell]], flagged: int = 0) -> int:
    """How many leading rows are the header.

    ``flagged`` is the number of leading rows the file itself marks as header
    (DOCX ``w:tblHeader``, PPTX ``firstRow``). A flagged row is still rejected
    if it contains an ``@`` (it is then almost certainly data). Tables with a
    single row never get a header, so their text is emitted as data.
    """
    if len(rows) < 2:
        return 0
    if flagged:
        flagged = min(flagged, len(rows) - 1)
        if all(not any("@" in c.text for c in row) for row in rows[:flagged]):
            return flagged
    return 1 if looks_like_header(rows[0]) else 0


def header_labels(header_rows: list[list[Cell]]) -> dict[int, str]:
    """Column -> label. Several header rows are combined with ``" / "``."""
    labels: dict[int, list[str]] = {}
    for row in header_rows:
        for cell in row:
            text = clean(cell.text).rstrip(":").strip()
            if text and text not in labels.setdefault(cell.col, []):
                labels[cell.col].append(text)
    return {col: " / ".join(parts) for col, parts in labels.items() if parts}


def row_pieces(row: list[Cell], labels: dict[int, str]) -> list[Piece]:
    """Pieces for one data row (empty cells are omitted)."""
    pieces: list[Piece] = []
    for cell in row:
        if cell.words:
            words = [w for w in cell.words if clean(w.text)]
            if not words:
                continue
        elif not clean(cell.text):
            continue
        if pieces:
            pieces.append(Piece(CELL_SEPARATOR, kind="sep"))
        label = labels.get(cell.col)
        if label:
            pieces.append(Piece(label, kind="label"))
            pieces.append(Piece(LABEL_SEPARATOR, kind="sep"))
        if cell.words:
            for n, word in enumerate(words):
                if n:
                    pieces.append(Piece(" ", kind="sep"))
                pieces.append(Piece(word.text, col=cell.col, bbox=word.bbox, conf=word.conf))
        else:
            pieces.append(Piece(cell.text, col=cell.col))
    return pieces


def table_blocks(
    rows: list[list[Cell]],
    *,
    location: str,
    table_id: int,
    flagged_header_rows: int = 0,
    external_labels: dict[int, str] | None = None,
    **common,
) -> list[RawBlock]:
    """One RawBlock per data row. ``location`` is the table's location prefix.

    ``external_labels`` are used when the header lives outside the table body
    (e.g. a PyMuPDF header found above the table); all rows are then data.
    """
    if external_labels:
        n_header, labels = 0, external_labels
    else:
        n_header = choose_header_rows(rows, flagged_header_rows)
        labels = header_labels(rows[:n_header])
    blocks: list[RawBlock] = []
    for r, row in enumerate(rows[n_header:], start=n_header + 1):
        pieces = row_pieces(row, labels)
        if not pieces:
            continue
        boxes = [c.bbox for c in row if c.bbox is not None]
        confs = [c.conf for c in row if c.conf is not None]
        kwargs = dict(common)
        if boxes and "bbox" not in kwargs:
            kwargs["bbox"] = (
                min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes),
            )
        if confs and "ocr_confidence" not in kwargs:
            kwargs["ocr_confidence"] = sum(confs) / len(confs)
        blocks.append(
            RawBlock(
                kind="table_row",
                location=f"{location}, row {r}",
                pieces=pieces,
                table_id=table_id,
                row_index=r,
                **kwargs,
            )
        )
    return blocks
