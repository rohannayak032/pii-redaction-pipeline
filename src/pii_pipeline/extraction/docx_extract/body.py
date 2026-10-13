"""Block-level walk of a WordprocessingML container (body, header, footer).

Children are visited in document order: paragraphs and tables keep their
sequence, content controls (``w:sdt``) and custom XML are entered, and every
paragraph's drawings follow that paragraph.
"""

from __future__ import annotations

import re

from lxml import etree

from ..base import Context, Piece, RawBlock
from ..normalize import clean
from ..ooxml import Consumed, NS, link_address, part_name, q, rels, xp
from ..tables import Cell, table_blocks
from .drawings import Counters, drawing_blocks
from .text import DRAWINGS, NESTED_TABLES, collect

W_P, W_TBL, W_SDT, W_CUSTOM = q("w", "p"), q("w", "tbl"), q("w", "sdt"), q("w", "customXml")
W_SDT_CONTENT, W_TR, W_TC = q("w", "sdtContent"), q("w", "tr"), q("w", "tc")
_W = f"{{{NS['w']}}}"
_R = f"{{{NS['r']}}}"

_STYLE = xp("./w:pPr/w:pStyle/@w:val")
_NUMBERED = xp("./w:pPr/w:numPr")
_HYPERLINKS = xp(".//w:hyperlink[@r:id][not(ancestor::mc:Fallback)]")
_INSTR = xp(".//w:instrText[not(ancestor::mc:Fallback)]")
_FIELD_URL = re.compile(r'HYPERLINK\s+"([^"]+)"', re.IGNORECASE)
_GRID_SPAN = xp("./w:tcPr/w:gridSpan/@w:val")
_V_MERGE = xp("./w:tcPr/w:vMerge")
_GRID_BEFORE = xp("./w:trPr/w:gridBefore/@w:val")
_TBL_HEADER = xp("./w:trPr/w:tblHeader")
_PARAGRAPHS = xp(".//w:p[not(ancestor::mc:Fallback)][not(ancestor::w:txbxContent)]")


def _children(element: etree._Element, wanted: str):
    """Direct ``wanted`` children, looking through ``w:sdt``/``w:customXml`` wrappers."""
    for child in element:
        if child.tag == wanted:
            yield child
        elif child.tag in (W_SDT, W_CUSTOM):
            inner = child.find(W_SDT_CONTENT) if child.tag == W_SDT else child
            if inner is not None:
                yield from _children(inner, wanted)


def _on(value) -> bool:
    return value is not None and value.get(f"{_W}val", "true") not in ("false", "0", "off")


W_T, W_BR, W_PAGE_BEFORE = q("w", "t"), q("w", "br"), q("w", "pageBreakBefore")
W_RENDERED_BREAK, W_TXBX, MC_FALLBACK = q("w", "lastRenderedPageBreak"), q("w", "txbxContent"), q("mc", "Fallback")
W_SECT, W_SECT_TYPE, W_PPR = q("w", "sectPr"), q("w", "type"), q("w", "pPr")
W_PG_SIZE, W_PG_MAR = q("w", "pgSz"), q("w", "pgMar")


def page_map(body: etree._Element) -> dict[etree._Element, int]:
    """1-based start page of every body paragraph and table row.

    DOCX stores no pages. Word saves where its last layout broke pages
    (``w:lastRenderedPageBreak``); without those, only explicit breaks count.
    Word writes no marker where a section starts on a new page, so those are
    added from the section properties. Table cells advance in parallel: Word
    marks a row starting a page in its first cell only, a row split across
    pages in each overflowing cell.
    """
    rendered = next(body.iter(W_RENDERED_BREAK), None) is not None
    pages: dict[etree._Element, int] = {}
    # A paragraph-level sectPr ends its section; the *next* sectPr's type says how the following one starts.
    sections = [s for s in body.iter(W_SECT) if s.getparent() is body or s.getparent().tag == W_PPR]
    section_ends = {s.getparent().getparent() for s, nxt in zip(sections, sections[1:]) if _new_page(s, nxt)}

    def is_break(n: etree._Element) -> bool:
        if rendered:
            return n.tag == W_RENDERED_BREAK
        return (n.tag == W_BR and n.get(f"{_W}type") == "page") or (n.tag == W_PAGE_BEFORE and _on(n))

    # Each walker returns (page where its first text sits or None, page after it).
    def paragraph(p, page):
        first = None
        for n in p.iter(W_T, W_BR, W_PAGE_BEFORE, W_RENDERED_BREAK):
            if _in_other_layer(n, p):
                continue
            if n.tag == W_T:
                first = page if first is None else first
            elif is_break(n):
                page += 1
        pages[p] = page if first is None else first
        return first, page + (p in section_ends)

    def container(el, page):
        first = None
        for child in _block_children(el):
            start, page = (paragraph if child.tag == W_P else table)(child, page)
            first = start if first is None else first
        return first, page

    def table(tbl, page):
        first, split = None, False
        for tr in _children(tbl, W_TR):
            spans = [container(tc, page) for tc in _children(tr, W_TC)] or [(None, page)]
            lead = (spans[0][0] or page) - page  # markers before the first cell's text
            # After a split row Word repeats that same break at the next row's start.
            start = page if split else page + lead
            end = start + max(e - (s or page) for s, e in spans)
            pages[tr], split, page = start, end > start, end
            first = start if first is None else first
        return first, page

    container(body, 1)
    return pages


def _new_page(ending: etree._Element, following: etree._Element) -> bool:
    """Does the ``following`` section start on a new page? nextPage is the default type."""
    kind = following.find(W_SECT_TYPE)
    if kind is None or kind.get(f"{_W}val") != "continuous":
        return True
    # Word also starts a new page when a continuous break changes the page size or margins.
    setup = lambda s: [dict(e.attrib) if e is not None else None for e in (s.find(W_PG_SIZE), s.find(W_PG_MAR))]
    return setup(ending) != setup(following)


def _in_other_layer(node: etree._Element, stop: etree._Element) -> bool:
    """True inside a text box or ``mc:Fallback`` copy, which don't advance the page flow."""
    parent = node.getparent()
    while parent is not None and parent is not stop:
        if parent.tag in (W_TXBX, MC_FALLBACK):
            return True
        parent = parent.getparent()
    return False


class BodyWalker:
    def __init__(self, ctx: Context, consumed: Consumed, styles: dict[str, str], counters: Counters):
        self.ctx = ctx
        self.consumed = consumed
        self.styles = styles
        self.counters = counters
        self.pages: dict[etree._Element, int] = {}  # body only; headers/footers repeat on every page

    # ------------------------------------------------------------------ paragraphs
    def _label(self, p: etree._Element) -> str:
        style_id = next(iter(_STYLE(p)), None)
        style = self.styles.get(style_id, style_id or "")
        if style.lower().startswith(("heading", "title", "subtitle")):
            return f" ({style})"
        if _NUMBERED(p) or "list" in style.lower():
            return " (list item)"
        return ""

    def _links(self, p: etree._Element, owner, text: str, location: str) -> list[RawBlock]:
        targets: list[str] = []
        for link in _HYPERLINKS(p):
            rel = rels(owner).get(link.get(f"{_R}id"))
            if rel is not None and rel.is_external:
                targets.append(rel.target_ref)
        for instr in _INSTR(p):
            targets += _FIELD_URL.findall(instr.text or "")
        blocks, visible = [], text.lower()
        for target in dict.fromkeys(clean(t) for t in targets):
            bare = link_address(target)
            if bare and bare.lower() not in visible:
                blocks.append(RawBlock(
                    kind="link", location=f"{location}, link {len(blocks) + 1}", source="xml",
                    pieces=[Piece("Link target", kind="label"), Piece(": ", kind="sep"), Piece(target)],
                ))
        return blocks

    def paragraph(self, p: etree._Element, owner, location: str) -> list[RawBlock]:
        name = part_name(owner)
        text = collect(p, name, self.consumed, prune=DRAWINGS)
        blocks: list[RawBlock] = []
        if clean(text):
            label = self._label(p)
            kind = "paragraph" if label in ("", " (list item)") else "heading"
            blocks.append(RawBlock.simple(kind, location + label, text, source="xml"))
        blocks += self._links(p, owner, text, location)
        blocks += drawing_blocks(p, owner, location, self.ctx, self.consumed, self.counters)
        for b in blocks:
            b.page = self.pages.get(p)
        return blocks

    # ------------------------------------------------------------------ tables
    def table(self, tbl: etree._Element, owner, location: str) -> list[RawBlock]:
        name = part_name(owner)
        rows: list[list[Cell]] = []
        row_pages: list[int | None] = []
        extras: dict[int, list[RawBlock]] = {}
        flagged = 0
        counting_header = True
        for r, tr in enumerate(_children(tbl, W_TR), start=1):
            if counting_header and _on(next(iter(_TBL_HEADER(tr)), None)):
                flagged += 1
            else:
                counting_header = False
            col = int(next(iter(_GRID_BEFORE(tr)), 0) or 0)
            cells: list[Cell] = []
            row_location = f"{location}, row {r}"
            nested = 0
            for tc in _children(tr, W_TC):
                span = int(next(iter(_GRID_SPAN(tc)), 1) or 1)
                v_merge = next(iter(_V_MERGE(tc)), None)
                continuation = v_merge is not None and v_merge.get(f"{_W}val", "continue") != "restart"
                if not continuation:
                    cells.append(Cell(col=col, text=collect(tc, name, self.consumed, prune=DRAWINGS | NESTED_TABLES)))
                # Nested tables and drawings inside the cell become their own blocks.
                for inner in tc.iter(W_TBL):
                    if _outer_table(inner, tc):
                        nested += 1
                        extras.setdefault(r, []).extend(
                            self.table(inner, owner, f"{row_location}, nested table {nested}")
                        )
                for p in _PARAGRAPHS(tc):
                    if _outer_table(p, tc):
                        extras.setdefault(r, []).extend(
                            drawing_blocks(p, owner, row_location, self.ctx, self.consumed, self.counters)
                        )
                col += span
            rows.append(cells)
            row_pages.append(self.pages.get(tr))

        row_blocks = table_blocks(
            rows, location=location, table_id=self.ctx.next_table_id(),
            flagged_header_rows=flagged, source="xml",
        )
        by_row = {b.row_index: b for b in row_blocks}
        out: list[RawBlock] = []
        for r in range(1, len(rows) + 1):
            if r in by_row:
                by_row[r].page = row_pages[r - 1]
                out.append(by_row[r])
            for b in extras.get(r, []):
                b.page = b.page or row_pages[r - 1]  # nested tables already carry their own row pages
                out.append(b)
        return out

    # ------------------------------------------------------------------ containers
    def container(self, root: etree._Element, owner, prefix: str = "") -> list[RawBlock]:
        """Walk a body/header/footer element; ``prefix`` e.g. ``"section 1, header"``."""
        blocks: list[RawBlock] = []
        paragraphs = tables = 0
        lead = f"{prefix}, " if prefix else ""
        for child in _block_children(root):
            if child.tag == W_P:
                paragraphs += 1
                blocks += self.paragraph(child, owner, f"{lead}paragraph {paragraphs}")
            elif child.tag == W_TBL:
                tables += 1
                blocks += self.table(child, owner, f"{lead}table {tables}")
        return blocks


def _block_children(element: etree._Element):
    for child in element:
        if child.tag in (W_P, W_TBL):
            yield child
        elif child.tag in (W_SDT, W_CUSTOM):
            inner = child.find(W_SDT_CONTENT) if child.tag == W_SDT else child
            if inner is not None:
                yield from _block_children(inner)


def _outer_table(node: etree._Element, cell: etree._Element) -> bool:
    """True if no other table cell lies between ``node`` and ``cell``."""
    parent = node.getparent()
    while parent is not None and parent is not cell:
        if parent.tag == W_TC:
            return False
        parent = parent.getparent()
    return parent is cell
