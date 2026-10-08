"""PDF content outside the page's text flow: annotations, form fields, links."""

from __future__ import annotations

import pymupdf

from ..base import Piece, RawBlock
from ..normalize import clean

_TEXT_FIELDS = {
    pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX,
}


def annotation_blocks(page: pymupdf.Page, pno: int) -> list[RawBlock]:
    """Comments, sticky notes, free-text boxes (with their author)."""
    blocks = []
    for annot in page.annots() or []:
        if annot.type[1] == "Popup":   # mirrors its parent annotation
            continue
        info = annot.info or {}
        content, author = info.get("content", ""), info.get("title", "")
        if not clean(content) and not clean(author):
            continue
        pieces = []
        if clean(author):
            pieces += [Piece("Comment by", kind="label"), Piece(" ", kind="sep"), Piece(author),
                       Piece(": ", kind="sep")]
        pieces.append(Piece(content))
        blocks.append(RawBlock(
            kind="annotation", location=f"page {pno}, annotation {len(blocks) + 1}",
            pieces=pieces, page=pno, bbox=tuple(annot.rect), bbox_unit="pt",
        ))
    return blocks


def form_field_blocks(page: pymupdf.Page, pno: int) -> list[RawBlock]:
    """Filled-in values of text-like form fields."""
    blocks = []
    for number, widget in enumerate(page.widgets() or [], start=1):
        if widget.field_type not in _TEXT_FIELDS:
            continue
        value = widget.field_value
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        if not clean(str(value or "")):
            continue
        label = widget.field_label or widget.field_name or ""
        pieces = [Piece(label, kind="label"), Piece(": ", kind="sep")] if clean(label) else []
        pieces.append(Piece(str(value), col=0))
        blocks.append(RawBlock(
            kind="form_field", location=f"page {pno}, form field {number}",
            pieces=pieces, page=pno, bbox=tuple(widget.rect), bbox_unit="pt",
        ))
    return blocks


def link_blocks(page: pymupdf.Page, pno: int, visible_text: str) -> list[RawBlock]:
    """Link targets (e.g. ``mailto:``) whose address is not visible on the page."""
    blocks = []
    visible = visible_text.lower()
    for link in page.get_links():
        uri = clean(link.get("uri") or "")
        if not uri:
            continue
        target = uri.split(":", 1)[1] if uri.lower().startswith(("mailto:", "tel:")) else uri
        if target.lower() in visible:
            continue
        blocks.append(RawBlock(
            kind="link", location=f"page {pno}, link {len(blocks) + 1}",
            pieces=[Piece("Link target", kind="label"), Piece(": ", kind="sep"), Piece(uri)],
            page=pno, bbox=tuple(link["from"]), bbox_unit="pt",
        ))
    return blocks
