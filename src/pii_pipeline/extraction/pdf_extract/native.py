"""Pages that have a usable text layer: words, tables and text inside images."""

from __future__ import annotations

import math

import pymupdf

from ..base import BBox, Context, Piece, RawBlock
from ..deduplication import center_inside
from ..ocr import ocr_image
from ..ordering import union, xy_cut
from ..tables import Cell, table_blocks

# Words outside the page's visible box are kept too: text hidden off-page is
# still in the file and may contain PII.
TEXT_FLAGS = pymupdf.TEXTFLAGS_WORDS & ~pymupdf.TEXT_MEDIABOX_CLIP
MIN_IMAGE_PX = 50
OCR_DPI = 300
MAX_PIXELS = 40_000_000

Word = tuple  # (x0, y0, x1, y1, text, block_no, line_no, word_no)


def capped_dpi(rect: pymupdf.Rect, dpi: int) -> int:
    """``dpi``, lowered so that rendering ``rect`` stays under MAX_PIXELS."""
    area = (rect.width / 72.0) * (rect.height / 72.0)
    return dpi if area <= 0 else int(min(dpi, math.sqrt(MAX_PIXELS / area)))


def page_words(page: pymupdf.Page) -> list[Word]:
    return page.get_text("words", flags=TEXT_FLAGS)


def has_text_layer(words: list[Word]) -> bool:
    """At least a few real characters and not mostly undecodable glyphs."""
    text = "".join(w[4] for w in words)
    alnum = sum(ch.isalnum() for ch in text)
    bad = text.count("�") + text.count("(cid:")
    return alnum >= 3 and bad <= 0.3 * max(len(text), 1)


def _tables(page: pymupdf.Page, pno: int, ctx: Context) -> list[tuple[BBox, list[RawBlock]]]:
    try:
        found = page.find_tables().tables
    except Exception:  # table finder is best-effort; text is still read as paragraphs
        return []
    out = []
    for k, table in enumerate(found, start=1):
        values = table.extract()
        rows: list[list[Cell]] = []
        for r, row in enumerate(table.rows):
            cells = []
            for c, bbox in enumerate(row.cells):
                if bbox is None:   # covered by a merged cell
                    continue
                text = values[r][c] if r < len(values) and c < len(values[r]) else None
                cells.append(Cell(col=c, text=text or "", bbox=tuple(bbox)))
            rows.append(cells)
        labels = None
        header = getattr(table, "header", None)
        if header is not None and header.external:
            labels = {c: name for c, name in enumerate(header.names) if name}
        blocks = table_blocks(
            rows, location=f"page {pno}, table {k}", table_id=ctx.next_table_id(),
            external_labels=labels, source="native", page=pno, bbox_unit="pt",
        )
        out.append((tuple(table.bbox), blocks))
    return out


def _paragraphs(words: list[Word], pno: int) -> list[tuple[BBox, RawBlock]]:
    groups: dict[int, list[Word]] = {}
    for w in words:
        groups.setdefault(w[5], []).append(w)
    out = []
    for block_words in groups.values():
        block_words.sort(key=lambda w: (w[6], w[7]))
        pieces: list[Piece] = []
        for w in block_words:
            if pieces:
                pieces.append(Piece(" ", kind="sep"))
            pieces.append(Piece(w[4], bbox=tuple(w[:4])))
        bbox = union([tuple(w[:4]) for w in block_words])
        out.append((bbox, RawBlock(
            kind="paragraph", location="", pieces=pieces, page=pno, bbox=bbox, bbox_unit="pt",
        )))
    return out


def _image_ocr(
    page: pymupdf.Page, pno: int, ctx: Context, words: list[Word]
) -> list[tuple[BBox, list[RawBlock]]]:
    out = []
    seen: set[tuple] = set()
    word_boxes = [tuple(w[:4]) for w in words]
    images = sorted(page.get_image_info(xrefs=True), key=lambda i: (i["bbox"][1], i["bbox"][0]))
    for info in images:
        rect = pymupdf.Rect(info["bbox"]) & page.rect
        key = (info.get("xref"), tuple(round(v, 1) for v in rect))
        if rect.is_empty or key in seen:
            continue
        seen.add(key)
        if min(info.get("width", 0), info.get("height", 0)) < MIN_IMAGE_PX:
            ctx.skip_image("smaller than 50x50 px")
            continue
        number = len(out) + 1
        location = f"page {pno}, image {number}"
        dpi = capped_dpi(rect, OCR_DPI)
        pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY)
        result = ocr_image(pixmap_array(pix), ctx, location, page=pno)
        blocks = result.blocks
        if result.geometry_exact and page.rotation == 0:
            blocks = [_to_points(b, rect, dpi) for b in blocks]
            blocks = [b for b in blocks if not _mostly_duplicate(b, word_boxes)]
        if blocks:
            out.append((tuple(rect), blocks))
    return out


def pixmap_array(pix: pymupdf.Pixmap):
    import numpy as np
    array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    return array[:, : pix.width * pix.n].reshape(pix.height, pix.width, pix.n).squeeze()


def _to_points(block: RawBlock, clip: pymupdf.Rect, dpi: int) -> RawBlock:
    """Map OCR pixel boxes (of a clip rendered at ``dpi``) to page points."""
    factor = 72.0 / dpi

    def convert(b: BBox | None) -> BBox | None:
        if b is None:
            return None
        return (clip.x0 + b[0] * factor, clip.y0 + b[1] * factor,
                clip.x0 + b[2] * factor, clip.y0 + b[3] * factor)

    for piece in block.pieces:
        piece.bbox = convert(piece.bbox)
    block.bbox = convert(block.bbox)
    block.bbox_unit = "pt"
    return block


def _mostly_duplicate(block: RawBlock, word_boxes: list[BBox]) -> bool:
    """True if most OCR words sit on text-layer words (text drawn over the image)."""
    words = [p for p in block.pieces if p.bbox is not None]
    if not words:
        return False
    dup = sum(any(center_inside(p.bbox, w) for w in word_boxes) for p in words)
    return dup / len(words) >= 0.5


def native_page(page: pymupdf.Page, pno: int, ctx: Context, words: list[Word]) -> list[RawBlock]:
    tables = _tables(page, pno, ctx)
    table_boxes = [bbox for bbox, _ in tables]
    free_words = [w for w in words if not any(center_inside(tuple(w[:4]), t) for t in table_boxes)]
    paragraphs = _paragraphs(free_words, pno)
    images = _image_ocr(page, pno, ctx, words)

    items: list[tuple[BBox, list[RawBlock]]] = [(bbox, [block]) for bbox, block in paragraphs]
    items += tables + images
    blocks: list[RawBlock] = []
    paragraph_no = 0
    for i in xy_cut([bbox for bbox, _ in items]):
        for block in items[i][1]:
            if block.kind == "paragraph":
                paragraph_no += 1
                block.location = f"page {pno}, paragraph {paragraph_no}"
            blocks.append(block)
    return blocks
