"""PDF extraction, decided page by page so mixed PDFs work.

* Page with a usable text layer -> native words, tables, OCR of embedded images.
* Page without one (scanned)    -> rendered and OCR'd as a whole.
* Every page                    -> annotations, form fields, hidden link targets.
* Document                      -> info-dictionary properties; attachments are flagged.
"""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf

from ..base import Context, RawBlock, UnsupportedFileError
from ..ocr import BLANK_INK_RATIO, ocr_image
from ..metadata import pdf_properties
from ..validation import PAGE_NO_TEXT, UNSUPPORTED_OBJECT
from .annotations import annotation_blocks, form_field_blocks, link_blocks
from .native import pixmap_array, has_text_layer, native_page, page_words

SCAN_DPI = 300
MAX_PIXELS = 40_000_000

# MuPDF messages go to stderr; keep them quiet (they are structural, but the
# module rule is that nothing about a document is printed).
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)
if hasattr(pymupdf, "no_recommend_layout"):
    pymupdf.no_recommend_layout()


def _scan_dpi(page: pymupdf.Page) -> int:
    w, h = page.rect.width / 72.0, page.rect.height / 72.0
    if w <= 0 or h <= 0:
        return SCAN_DPI
    return int(min(SCAN_DPI, math.sqrt(MAX_PIXELS / (w * h))))


def scanned_page(page: pymupdf.Page, pno: int, ctx: Context) -> tuple[list[RawBlock], float]:
    pix = page.get_pixmap(dpi=_scan_dpi(page), colorspace=pymupdf.csGRAY)
    result = ocr_image(pixmap_array(pix), ctx, f"page {pno}", page=pno, check_coverage=True)
    return result.blocks, result.ink


def extract_pdf(path: Path, ctx: Context) -> list[RawBlock]:
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise UnsupportedFileError(f"{path.name!r} is password-protected; remove the password first.")
        blocks: list[RawBlock] = []
        for pno, page in enumerate(doc, start=1):
            words = page_words(page)
            if has_text_layer(words):
                page_blocks = native_page(page, pno, ctx, words)
                ink = 1.0
            else:
                page_blocks, ink = scanned_page(page, pno, ctx)
            visible = " ".join(w[4] for w in words)
            page_blocks += annotation_blocks(page, pno)
            page_blocks += form_field_blocks(page, pno)
            page_blocks += link_blocks(page, pno, visible)
            if not page_blocks:
                detail = (
                    "page appears blank" if ink < BLANK_INK_RATIO
                    else "page has visible content but no text was found"
                )
                ctx.warn(PAGE_NO_TEXT, f"page {pno}", detail)
            blocks += page_blocks

        if doc.embfile_count():
            ctx.warn(UNSUPPORTED_OBJECT, "document", f"{doc.embfile_count()} embedded file(s) not extracted")
        properties = pdf_properties(doc)
        if properties is not None:
            blocks.append(properties)
    return blocks
