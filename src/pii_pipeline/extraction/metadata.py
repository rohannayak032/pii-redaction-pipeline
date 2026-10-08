"""Document properties (author, last modified by, company, ...).

They are emitted as one ``document properties`` block, kept out of the
reading order (appended at the end), because they often name people.
"""

from __future__ import annotations

from .base import Piece, RawBlock
from .normalize import clean
from .ooxml import part_root, rels, xp

_CORE_FIELDS = [
    ("Title", "dc:title"), ("Subject", "dc:subject"), ("Author", "dc:creator"),
    ("Keywords", "cp:keywords"), ("Comments", "dc:description"),
    ("Last Modified By", "cp:lastModifiedBy"), ("Category", "cp:category"),
    ("Content Status", "cp:contentStatus"),
]
_APP_FIELDS = [("Company", "ep:Company"), ("Manager", "ep:Manager")]
_PDF_FIELDS = [
    ("Title", "title"), ("Author", "author"), ("Subject", "subject"),
    ("Keywords", "keywords"), ("Creator", "creator"), ("Producer", "producer"),
]

RT_CORE = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
RT_APP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"


def properties_block(pairs: list[tuple[str, str]], source: str = "xml") -> RawBlock | None:
    """``"Author: … | Title: …"`` from (label, value) pairs; None if all empty."""
    pieces: list[Piece] = []
    for col, (label, value) in enumerate(pairs):
        if not clean(value):
            continue
        if pieces:
            pieces.append(Piece(" | ", kind="sep"))
        pieces += [Piece(label, kind="label"), Piece(": ", kind="sep"), Piece(value, col=col)]
    if not pieces:
        return None
    return RawBlock(kind="metadata", location="document properties", pieces=pieces, source=source)


def ooxml_properties(package) -> RawBlock | None:
    """Core and extended (app) properties of a python-docx/pptx package."""
    pairs: list[tuple[str, str]] = []
    for rel in rels(package).values():
        if rel.is_external or rel.reltype not in (RT_CORE, RT_APP):
            continue
        root = part_root(rel.target_part)
        if root is None:
            continue
        fields = _CORE_FIELDS if rel.reltype == RT_CORE else _APP_FIELDS
        for label, path in fields:
            for node in xp(path)(root):
                pairs.append((label, node.text or ""))
    return properties_block(pairs)


def pdf_properties(doc) -> RawBlock | None:
    """The PDF info dictionary of a PyMuPDF document."""
    meta = doc.metadata or {}
    return properties_block([(label, meta.get(key) or "") for label, key in _PDF_FIELDS], source="native")
