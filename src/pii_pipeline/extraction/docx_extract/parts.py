"""DOCX content outside the main body: headers/footers, notes, comments."""

from __future__ import annotations

from ..base import Context, Piece, RawBlock
from ..normalize import clean
from ..ooxml import Consumed, part_name, part_root, q, rels, xp
from .body import BodyWalker
from .drawings import Counters, drawing_blocks
from .text import DRAWINGS, collect

RT_FOOTNOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
RT_ENDNOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
RT_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
_SEPARATOR_TYPES = {"separator", "continuationSeparator", "continuationNotice"}
_W_ID, _W_TYPE, _W_AUTHOR = q("w", "id"), q("w", "type"), q("w", "author")
_PARAGRAPHS = xp(".//w:p[not(ancestor::mc:Fallback)][not(ancestor::w:txbxContent)]")


def header_footer_blocks(document, walker: BodyWalker) -> list[RawBlock]:
    """Every section's default / first-page / even-page header and footer.

    A part shared by several sections (linked to previous) is emitted once.
    """
    blocks: list[RawBlock] = []
    seen: set[str] = set()
    for number, section in enumerate(document.sections, start=1):
        variants = [
            ("header", section.header), ("header (first page)", section.first_page_header),
            ("header (even pages)", section.even_page_header),
            ("footer", section.footer), ("footer (first page)", section.first_page_footer),
            ("footer (even pages)", section.even_page_footer),
        ]
        for label, item in variants:
            if item.is_linked_to_previous:
                continue
            part = item.part
            if part_name(part) in seen:
                continue
            seen.add(part_name(part))
            blocks += walker.container(item._element, part, f"section {number}, {label}")
    return blocks


def _note_or_comment(element, owner, location: str, ctx: Context, consumed: Consumed,
                     counters: Counters, author: str | None = None) -> list[RawBlock]:
    text = collect(element, part_name(owner), consumed, prune=DRAWINGS)
    blocks: list[RawBlock] = []
    if clean(text) or clean(author):
        pieces = []
        if clean(author):
            pieces += [Piece("Comment by", kind="label"), Piece(" ", kind="sep"), Piece(author or ""),
                       Piece(": ", kind="sep")]
        pieces.append(Piece(text))
        kind = "comment" if author is not None else location.split(" ")[0]
        blocks.append(RawBlock(kind=kind, location=location, pieces=pieces, source="xml"))
    for p in _PARAGRAPHS(element):
        blocks += drawing_blocks(p, owner, location, ctx, consumed, counters)
    return blocks


def _related(document, reltype: str):
    for rel in rels(document.part).values():
        if rel.reltype == reltype and not rel.is_external:
            yield rel.target_part


def note_blocks(document, ctx: Context, consumed: Consumed, counters: Counters) -> list[RawBlock]:
    """Footnotes and endnotes (separator entries skipped)."""
    blocks: list[RawBlock] = []
    for reltype, tag, label in ((RT_FOOTNOTES, "footnote", "footnote"), (RT_ENDNOTES, "endnote", "endnote")):
        for part in _related(document, reltype):
            root = part_root(part)
            if root is None:
                continue
            for note in root.iter(q("w", tag)):
                if note.get(_W_TYPE) in _SEPARATOR_TYPES:
                    continue
                blocks += _note_or_comment(note, part, f"{label} {note.get(_W_ID)}", ctx, consumed, counters)
    return blocks


def comment_blocks(document, ctx: Context, consumed: Consumed, counters: Counters) -> list[RawBlock]:
    """Review comments, with their author."""
    blocks: list[RawBlock] = []
    number = 0
    for part in _related(document, RT_COMMENTS):
        root = part_root(part)
        if root is None:
            continue
        for comment in root.iter(q("w", "comment")):
            number += 1
            blocks += _note_or_comment(
                comment, part, f"comment {number}", ctx, consumed, counters,
                author=comment.get(_W_AUTHOR, ""),
            )
    return blocks
