"""Geometry-based reading order (recursive XY-cut).

Library output order is not trusted. Items with bounding boxes are ordered by:

1. Recursively splitting the region at the widest empty gap. A vertical split
   (columns) is taken only when it is wider than the best horizontal gap AND
   the two sides are not simply the two halves of the same rows (a
   "Label    Value" form must be read row by row, not all labels first).
2. When no split exists, falling back to row bands: items whose vertical
   extents overlap form a row, rows go top to bottom, items left to right.

Ties are broken by input position, so the result is deterministic.
"""

from __future__ import annotations

from typing import Sequence

from .base import BBox


def xy_cut(boxes: Sequence[BBox]) -> list[int]:
    """Return the indexes of ``boxes`` in reading order."""
    return _cut(list(range(len(boxes))), boxes)


def _cut(idx: list[int], boxes: Sequence[BBox]) -> list[int]:
    if len(idx) <= 1:
        return idx
    rows, y_gap = _split(idx, boxes, axis=1)
    cols, x_gap = _split(idx, boxes, axis=0)

    if len(cols) > 1 and x_gap > y_gap and not _row_aligned(cols, boxes):
        groups = cols
    elif len(rows) > 1:
        groups = rows
    elif len(cols) > 1 and not _row_aligned(cols, boxes):
        groups = cols
    else:
        return row_bands(idx, boxes)
    out: list[int] = []
    for group in groups:
        out.extend(_cut(group, boxes))
    return out


def _split(idx: list[int], boxes: Sequence[BBox], axis: int) -> tuple[list[list[int]], float]:
    """Split ``idx`` in two at the widest gap of the projection on ``axis``.

    Returns the groups (in increasing coordinate order; one group if there is
    no gap) and the width of that gap. Cutting only at the widest gap keeps
    e.g. a title gap from being treated like the small gaps inside columns.
    """
    lo, hi = (0, 2) if axis == 0 else (1, 3)
    ordered = sorted(idx, key=lambda i: (boxes[i][lo], boxes[i][hi], i))
    reach = boxes[ordered[0]][hi]
    best_at, widest = 0, 0.0
    for n, i in enumerate(ordered[1:], start=1):
        gap = boxes[i][lo] - reach
        if gap > widest:
            best_at, widest = n, gap
        reach = max(reach, boxes[i][hi])
    if not best_at:
        return [sorted(idx)], 0.0
    return [sorted(ordered[:best_at]), sorted(ordered[best_at:])], widest


def _row_aligned(cols: list[list[int]], boxes: Sequence[BBox]) -> bool:
    """True if neighbouring column groups are mostly the same rows side by side."""
    paired = total = 0
    for left, right in zip(cols, cols[1:]):
        small, big = (left, right) if len(left) <= len(right) else (right, left)
        for i in small:
            total += 1
            if any(_same_row(boxes[i], boxes[j]) for j in big):
                paired += 1
    return total > 0 and paired / total >= 0.6


def _same_row(a: BBox, b: BBox) -> bool:
    ha, hb = a[3] - a[1], b[3] - b[1]
    if ha <= 0 or hb <= 0:
        return False
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap >= 0.5 * min(ha, hb) and 0.5 <= ha / hb <= 2.0


def row_bands(idx: Sequence[int], boxes: Sequence[BBox]) -> list[int]:
    """Top-to-bottom rows of vertically overlapping items, each left to right."""
    ordered = sorted(idx, key=lambda i: (boxes[i][1], boxes[i][0], i))
    rows: list[list[int]] = []
    row_top = row_bottom = 0.0
    for i in ordered:
        x0, y0, x1, y1 = boxes[i]
        height = max(y1 - y0, 1e-9)
        if rows:
            overlap = min(row_bottom, y1) - max(row_top, y0)
            if overlap >= 0.5 * min(height, max(row_bottom - row_top, 1e-9)):
                rows[-1].append(i)
                row_bottom = max(row_bottom, y1)
                continue
        rows.append([i])
        row_top, row_bottom = y0, y1
    out: list[int] = []
    for row in rows:
        out.extend(sorted(row, key=lambda i: (boxes[i][0], boxes[i][1], i)))
    return out


def union(boxes: Sequence[BBox]) -> BBox:
    """Smallest box containing all ``boxes`` (which must not be empty)."""
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
