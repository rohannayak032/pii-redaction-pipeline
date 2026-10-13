"""Duplicate handling based on geometry and source location.

Two blocks are never treated as duplicates just because their text is equal:
the same name legitimately appears in many places. Duplicates are content
that was captured twice from the SAME place, e.g. a PDF text layer and an OCR
pass over the same region, or the same XML part reached through two paths.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .base import BBox, RawBlock


def area(box: BBox) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection(a: BBox, b: BBox) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a: BBox, b: BBox) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def covered_fraction(inner: BBox, outers: Iterable[BBox]) -> float:
    """Approximate fraction of ``inner`` covered by ``outers`` (capped at 1)."""
    a = area(inner)
    if a <= 0:
        return 0.0
    return min(1.0, sum(intersection(inner, o) for o in outers) / a)


def center_inside(box: BBox, region: BBox) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def drop_overlapping(
    candidates: Sequence[RawBlock], keep: Sequence[RawBlock], threshold: float = 0.5
) -> list[RawBlock]:
    """Drop ``candidates`` whose box overlaps a ``keep`` box with IoU >= threshold.

    Used for OCR output over a region that also has a text layer: the text
    layer is exact, so it wins.
    """
    kept_boxes = [b.bbox for b in keep if b.bbox is not None]
    out = []
    for block in candidates:
        if block.bbox is not None and any(iou(block.bbox, k) >= threshold for k in kept_boxes):
            continue
        out.append(block)
    return out


def final_pass(blocks: list[RawBlock], texts: list[str]) -> list[int]:
    """Indexes of blocks to keep after removing same-place duplicates.

    A block is a duplicate when an earlier block has the same text AND either
    the same location, or the same page with overlapping boxes (IoU >= 0.5).
    """
    keep: list[int] = []
    seen: dict[str, list[int]] = {}
    for i, (block, text) in enumerate(zip(blocks, texts)):
        duplicate = False
        for j in seen.get(text, ()):
            other = blocks[j]
            if other.location == block.location:
                duplicate = True
            elif (
                block.bbox is not None and other.bbox is not None
                and block.page == other.page and block.bbox_unit == other.bbox_unit
                and iou(block.bbox, other.bbox) >= 0.5
            ):
                duplicate = True
            if duplicate:
                break
        if not duplicate:
            keep.append(i)
            seen.setdefault(text, []).append(i)
    return keep
