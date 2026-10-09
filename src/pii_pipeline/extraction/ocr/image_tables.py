"""Ruled-table detection in images.

Long horizontal and vertical strokes are isolated with morphological opening.
Where they form a grid of at least 2x2 cells we have a table; each cell is
then OCR'd on its own so that row/column relationships survive. Cells whose
separating line is missing in a row are merged (horizontally merged cells).

Borderless tables are not detected here; their text is still read by the
full-page OCR pass, just without cell structure.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..base import BBox


@dataclass
class GridCell:
    row: int
    col: int
    bbox: BBox   # px, inner area without the ruling lines


@dataclass
class TableGrid:
    bbox: BBox
    rows: list[list[GridCell]]


def _line_positions(profile: np.ndarray, threshold: float) -> list[int]:
    """Centers of runs where ``profile`` >= threshold."""
    positions: list[int] = []
    start = None
    for i, value in enumerate(profile):
        if value >= threshold and start is None:
            start = i
        elif value < threshold and start is not None:
            positions.append((start + i - 1) // 2)
            start = None
    if start is not None:
        positions.append((start + len(profile) - 1) // 2)
    return positions


def _dedupe(positions: list[int], min_distance: int) -> list[int]:
    out: list[int] = []
    for p in positions:
        if out and p - out[-1] < min_distance:
            continue
        out.append(p)
    return out


def find_tables(gray: np.ndarray) -> list[TableGrid]:
    h, w = gray.shape
    _, inverted = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 40)))
    horizontal = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, h_kernel)
    vertical = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, v_kernel)
    grid = cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables: list[TableGrid] = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < 60 or ch < 30:
            continue
        hor = horizontal[y:y + ch, x:x + cw] > 0
        ver = vertical[y:y + ch, x:x + cw] > 0
        ys = _dedupe(_line_positions(hor.sum(axis=1), 0.5 * cw), 8)
        xs = _dedupe(_line_positions(ver.sum(axis=0), 0.3 * ch), 8)
        if len(ys) < 3 or len(xs) < 3:      # fewer than 2x2 cells
            continue
        rows: list[list[GridCell]] = []
        for r in range(len(ys) - 1):
            y0, y1 = ys[r], ys[r + 1]
            if y1 - y0 < 8:
                continue
            row: list[GridCell] = []
            c = 0
            while c < len(xs) - 1:
                start = c
                # Merge across internal boundaries that have no line in this row.
                while c + 1 < len(xs) - 1 and not _has_vertical(ver, xs[c + 1], y0, y1):
                    c += 1
                x0, x1 = xs[start], xs[c + 1]
                pad = 3
                row.append(GridCell(
                    row=len(rows), col=start,
                    bbox=(x + x0 + pad, y + y0 + pad, x + x1 - pad, y + y1 - pad),
                ))
                c += 1
            rows.append(row)
        if len(rows) >= 2:
            tables.append(TableGrid(bbox=(x, y, x + cw, y + ch), rows=rows))
    tables.sort(key=lambda t: (t.bbox[1], t.bbox[0]))
    return tables


def _has_vertical(ver: np.ndarray, x: int, y0: int, y1: int) -> bool:
    lo, hi = max(0, x - 3), min(ver.shape[1], x + 4)
    segment = ver[y0 + 2:max(y0 + 3, y1 - 1), lo:hi].any(axis=1)
    return segment.size > 0 and segment.mean() >= 0.6
