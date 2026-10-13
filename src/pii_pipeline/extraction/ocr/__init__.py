"""Shared OCR helper used for scanned PDF pages and for images in any format.

``ocr_image`` runs the whole chain:

1. grayscale, skip blank images
2. orientation (Tesseract OSD) and small-angle deskew
3. upscale small text, contrast normalization and denoising
4. ruled tables -> per-cell OCR, then the table areas are masked out
5. full OCR of the rest; if confidence is low, retry with other thresholds
   and keep the best pass (low-confidence words are kept, never dropped)
6. paragraphs and tables ordered by geometry -> RawBlocks
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from ..base import Context, Piece, RawBlock
from ..ordering import union, xy_cut
from ..tables import Cell, table_blocks
from ..validation import LOW_COVERAGE, LOW_OCR_CONFIDENCE
from . import engine, preprocessing
from .engine import ocr_available, tesseract_cmd
from .image_tables import find_tables

__all__ = ["OcrOutput", "load_image", "ocr_available", "ocr_blob", "ocr_image", "tesseract_cmd"]

BLANK_INK_RATIO = 0.001
MIN_IMAGE_PX = 50
MAX_PIXELS = 40_000_000   # upscaling never grows an image past this


@dataclass
class OcrOutput:
    blocks: list[RawBlock] = field(default_factory=list)
    ink: float = 0.0
    chars: int = 0
    rotation: int = 0
    skew: float = 0.0

    @property
    def geometry_exact(self) -> bool:
        """True if bboxes map 1:1 onto the input image (no rotation/deskew)."""
        return self.rotation == 0 and self.skew == 0.0


def _paragraphs(words: list[engine.Word]) -> list[list[engine.Word]]:
    groups: dict[tuple[int, int], list[engine.Word]] = {}
    for word in words:
        groups.setdefault((word.block, word.par), []).append(word)
    return list(groups.values())


def _word_pieces(words: list[engine.Word], scale: float, col: int | None = None) -> list[Piece]:
    pieces: list[Piece] = []
    for word in words:
        if pieces:
            pieces.append(Piece(" ", kind="sep"))
        x0, y0, x1, y1 = word.bbox
        pieces.append(Piece(word.text, col=col, bbox=(x0 / scale, y0 / scale, x1 / scale, y1 / scale), conf=word.conf))
    return pieces


def _with_border(image: np.ndarray, pad: int = 10) -> np.ndarray:
    return cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def _best_pass(gray: np.ndarray) -> list[engine.Word]:
    words = engine.ocr_words(preprocessing.binarize(gray))
    conf = engine.mean_conf(words)
    if conf is not None and conf >= LOW_OCR_CONFIDENCE:
        return words
    for variant in (preprocessing.binarize_adaptive(gray), gray):
        retry = engine.ocr_words(variant)
        if engine.score(retry) > engine.score(words):
            words = retry
    return words


def ocr_image(
    image,
    ctx: Context,
    location: str,
    *,
    page: int | None = None,
    hidden: bool = False,
    check_coverage: bool = False,
) -> OcrOutput:
    """OCR one image into RawBlocks located under ``location``.

    Bounding boxes are in pixels of the input image (after undoing any
    upscaling). If the image had to be rotated or deskewed, boxes refer to the
    corrected image; ``OcrOutput.geometry_exact`` tells which.
    """
    engine.tesseract_cmd()  # raise early and clearly if OCR is unavailable
    gray = preprocessing.to_gray(image)
    out = OcrOutput(ink=preprocessing.ink_ratio(gray))
    if out.ink < BLANK_INK_RATIO:
        return out

    out.rotation = engine.detect_orientation(gray)
    gray = preprocessing.rotate_quadrant(gray, out.rotation)
    out.skew = preprocessing.skew_angle(gray)
    gray = preprocessing.deskew(gray, out.skew)
    scale = min(preprocessing.upscale_factor(gray), max(1.0, (MAX_PIXELS / gray.size) ** 0.5))
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = preprocessing.enhance(gray)

    # Tables first, then mask them so the page pass does not read them twice.
    items: list[tuple[tuple[float, float, float, float], str, list]] = []
    masked = gray.copy()
    for grid in find_tables(gray):
        rows: list[list[Cell]] = []
        for grid_row in grid.rows:
            row: list[Cell] = []
            for cell in grid_row:
                x0, y0, x1, y1 = (int(v) for v in cell.bbox)
                crop = gray[y0:y1, x0:x1]
                if crop.size == 0 or preprocessing.ink_ratio(crop) < BLANK_INK_RATIO:
                    row.append(Cell(col=cell.col))
                    continue
                words = engine.ocr_words(_with_border(preprocessing.binarize(crop)), psm=6)
                for w in words:   # back to page coordinates (undo border and crop)
                    bx0, by0, bx1, by1 = w.bbox
                    w.bbox = (bx0 - 10 + x0, by0 - 10 + y0, bx1 - 10 + x0, by1 - 10 + y0)
                row.append(Cell(
                    col=cell.col,
                    text=" ".join(w.text for w in words),
                    words=_word_pieces(words, scale, col=cell.col),
                    bbox=tuple(v / scale for v in cell.bbox),
                    conf=engine.mean_conf(words),
                ))
            rows.append(row)
        gx0, gy0, gx1, gy1 = (int(v) for v in grid.bbox)
        masked[gy0:gy1, gx0:gx1] = 255
        items.append((tuple(v / scale for v in grid.bbox), "table", rows))

    for words in _paragraphs(_best_pass(masked)):
        pieces = _word_pieces(words, scale)
        bbox = union([p.bbox for p in pieces if p.bbox is not None])
        items.append((bbox, "paragraph", pieces))

    paragraph_no = table_no = 0
    for i in xy_cut([bbox for bbox, _, _ in items]):
        bbox, what, content = items[i]
        common = dict(source="ocr", page=page, hidden=hidden, bbox_unit="px")
        if what == "table":
            table_no += 1
            rows_blocks = table_blocks(
                content, location=f"{location}, table {table_no} (OCR)",
                table_id=ctx.next_table_id(), **common,
            )
            out.blocks.extend(rows_blocks)
        else:
            paragraph_no += 1
            out.blocks.append(RawBlock(
                kind="ocr_paragraph", location=f"{location}, paragraph {paragraph_no} (OCR)",
                pieces=content, bbox=bbox, **common,
            ))

    out.chars = sum(len(p.text) for b in out.blocks for p in b.pieces if p.kind != "sep")
    if check_coverage and out.ink > 0.02 and out.chars < 20:
        ctx.warn(LOW_COVERAGE, location, f"visible content ({out.ink:.1%} ink) but only {out.chars} characters read")
    return out


def load_image(blob: bytes, ctx: Context):
    """Decode an image blob, or record why it was skipped."""
    try:
        image = Image.open(io.BytesIO(blob))
        image.load()
    except Image.DecompressionBombError:
        ctx.skip_image("image too large to decode safely")
        return None
    except (UnidentifiedImageError, OSError, ValueError):
        ctx.skip_image("unsupported or unreadable image format (e.g. EMF/WMF)")
        return None
    if image.format in {"WMF", "EMF"}:
        ctx.skip_image("unsupported or unreadable image format (e.g. EMF/WMF)")
        return None
    if min(image.size) < MIN_IMAGE_PX:
        ctx.skip_image("smaller than 50x50 px")
        return None
    if image.mode not in ("L", "RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() or image.mode == "P" else "RGB")
    return image


def ocr_blob(blob: bytes, ctx: Context, location: str, hidden: bool = False) -> list[RawBlock]:
    image = load_image(blob, ctx)
    if image is None:
        return []
    return ocr_image(image, ctx, location, hidden=hidden).blocks
