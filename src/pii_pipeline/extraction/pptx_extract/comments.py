"""Slide comments: legacy (``commentN.xml``) and modern (``modernComment_*.xml``).

python-pptx has no comments API, so the parts are read directly. Each comment
(and each modern reply) becomes a block ``"Comment by <author>: <text>"``.
"""

from __future__ import annotations

from ..base import Piece, RawBlock
from ..normalize import clean
from ..ooxml import Consumed, drawingml_text, part_name, part_root, rels, xp

RT_LEGACY = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
RT_LEGACY_AUTHORS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/commentAuthors"
RT_MODERN = "http://schemas.microsoft.com/office/2018/10/relationships/comments"
RT_MODERN_AUTHORS = "http://schemas.microsoft.com/office/2018/10/relationships/authors"

_LEGACY_AUTHORS = xp("//p:cmAuthor")
_MODERN_AUTHORS = xp("//p188:author")
_LEGACY = xp("//p:cm")
_LEGACY_TEXT = xp("./p:text")
_MODERN = xp("//p188:cm | //p188:reply")
_MODERN_BODY = xp("./p188:txBody")


def author_names(presentation_part) -> dict[str, str]:
    names: dict[str, str] = {}
    for rel in rels(presentation_part).values():
        if rel.is_external or rel.reltype not in (RT_LEGACY_AUTHORS, RT_MODERN_AUTHORS):
            continue
        root = part_root(rel.target_part)
        if root is None:
            continue
        for node in _LEGACY_AUTHORS(root) + _MODERN_AUTHORS(root):
            names[node.get("id", "")] = node.get("name", "")
    return names


def _block(author: str, text: str, location: str, page: int, hidden: bool) -> RawBlock:
    pieces = []
    if clean(author):
        pieces += [Piece("Comment by", kind="label"), Piece(" ", kind="sep"), Piece(author), Piece(": ", kind="sep")]
    pieces.append(Piece(text))
    return RawBlock(kind="comment", location=location, pieces=pieces, source="xml", page=page, hidden=hidden)


def comment_blocks(slide_part, authors: dict[str, str], consumed: Consumed,
                   prefix: str, page: int, hidden: bool) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    for rel in rels(slide_part).values():
        if rel.is_external or rel.reltype not in (RT_LEGACY, RT_MODERN):
            continue
        part = rel.target_part
        root = part_root(part)
        if root is None:
            continue
        name = part_name(part)
        if rel.reltype == RT_LEGACY:
            entries = [(cm.get("authorId", ""), " ".join(t.text or "" for t in _LEGACY_TEXT(cm))) for cm in _LEGACY(root)]
        else:
            entries = []
            for cm in _MODERN(root):
                body = next(iter(_MODERN_BODY(cm)), None)
                entries.append((cm.get("authorId", ""), drawingml_text(body, name, consumed) if body is not None else ""))
        for author_id, text in entries:
            author = authors.get(author_id, "")
            if clean(text) or clean(author):
                blocks.append(_block(author, text, f"{prefix}, comment {len(blocks) + 1}", page, hidden))
    return blocks
