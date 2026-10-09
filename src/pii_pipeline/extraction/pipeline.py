"""Assembly: RawBlocks -> normalized, deduplicated, validated TextBlocks."""

from __future__ import annotations

from typing import Sequence

from pii_pipeline.schemas import TextBlock

from . import deduplication, validation
from .base import BBox, BlockMeta, Context, Piece, RawBlock
from .normalize import clean


def render(pieces: Sequence[Piece]) -> tuple[str, list[tuple[int, int, int]], list]:
    """Join pieces into one string and compute spans on that final string.

    Text and label pieces are cleaned individually; separators are kept as is.
    Empty pieces are dropped together with a separator they would leave
    dangling, so the text never starts or ends with a separator.
    """
    kept: list[tuple[Piece, str]] = []
    for piece in pieces:
        text = piece.text if piece.kind == "sep" else clean(piece.text)
        if not text:
            continue
        if piece.kind == "sep" and (not kept or kept[-1][0].kind == "sep"):
            continue
        kept.append((piece, text))
    while kept and kept[-1][0].kind == "sep":
        kept.pop()

    parts: list[str] = []
    cell_spans: dict[int, list[int]] = {}
    words: list[tuple[int, int, BBox, float | None]] = []
    pos = 0
    for piece, text in kept:
        start, end = pos, pos + len(text)
        parts.append(text)
        pos = end
        if piece.kind == "sep":
            continue
        if piece.col is not None and piece.kind != "label":
            span = cell_spans.setdefault(piece.col, [start, end])
            span[1] = end
        if piece.bbox is not None:
            words.append((start, end, piece.bbox, piece.conf))
    text = "".join(parts)
    cells = sorted((col, s, e) for col, (s, e) in cell_spans.items())
    return text, cells, words


def assemble(file: str, raw_blocks: Sequence[RawBlock], ctx: Context) -> tuple[list[TextBlock], list[BlockMeta]]:
    rendered = [render(b.pieces) for b in raw_blocks]
    candidates = [(b, r) for b, r in zip(raw_blocks, rendered) if r[0]]
    keep = deduplication.final_pass([b for b, _ in candidates], [r[0] for _, r in candidates])

    blocks: list[TextBlock] = []
    meta: list[BlockMeta] = []
    for index, k in enumerate(keep):
        raw, (text, cells, words) = candidates[k]
        conf = raw.ocr_confidence
        if conf is None and raw.source == "ocr":
            confs = [w[3] for w in words if w[3] is not None]
            conf = sum(confs) / len(confs) if confs else None
        if conf is not None:
            conf = min(1.0, max(0.0, round(conf, 4)))
        blocks.append(
            TextBlock(file=file, location=raw.location, index=index, text=text, ocr_confidence=conf)
        )
        meta.append(
            BlockMeta(
                index=index, kind=raw.kind, source=raw.source, page=raw.page,
                hidden=raw.hidden, bbox=raw.bbox, bbox_unit=raw.bbox_unit,
                table_id=raw.table_id, row_index=raw.row_index,
                cells=tuple(cells), words=tuple(words),
            )
        )
        if conf is not None and conf < validation.LOW_OCR_CONFIDENCE:
            ctx.warn(validation.LOW_CONFIDENCE, raw.location, f"mean OCR confidence {conf:.2f}")
    return blocks, meta
