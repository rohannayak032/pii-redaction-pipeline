"""Helpers shared by the DOCX and PPTX extractors (both are OOXML packages).

* Namespaces and compiled XPath expressions.
* A safe XML parser (no entity expansion, no network).
* ``Consumed``: remembers which text nodes the structured extractors used, so
  the final sweep can emit anything they missed (``UNCLAIMED_TEXT``).
* Charts, SmartArt and document properties, which look the same in both formats.
"""

from __future__ import annotations

from typing import Iterable

from lxml import etree

from .base import Context, Piece, RawBlock
from .normalize import clean
from .validation import UNCLAIMED_TEXT

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "p188": "http://schemas.microsoft.com/office/powerpoint/2018/8/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}

DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
CHART_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"
RT_DIAGRAM_DRAWING = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def q(prefix: str, local: str) -> str:
    """Clark notation tag, e.g. ``q("w", "t")`` -> ``{...main}t``."""
    return f"{{{NS[prefix]}}}{local}"


def xp(expr: str) -> etree.XPath:
    return etree.XPath(expr, namespaces=NS)


def parse_xml(blob: bytes) -> etree._Element:
    """Parse untrusted package XML safely."""
    return etree.fromstring(blob, parser=_PARSER)


def part_name(part) -> str:
    return str(part.partname).lstrip("/")


def part_root(part) -> etree._Element | None:
    """The XML root of an OPC part (python-docx/pptx object), or None if binary."""
    element = getattr(part, "_element", None)
    if element is not None:
        return element
    blob = getattr(part, "blob", b"")
    if not blob or not str(part.content_type).endswith("xml"):
        return None
    try:
        return parse_xml(blob)
    except etree.XMLSyntaxError:
        return None


def rels(owner) -> dict:
    """Relationships of a part or package (python-docx: ``rels``, python-pptx: ``_rels``)."""
    found = getattr(owner, "rels", None)
    return found if found is not None else owner._rels


def related(owner, rel_id: str | None):
    """Target part of relationship ``rel_id``, or None if missing/external."""
    rel = rels(owner).get(rel_id) if rel_id else None
    if rel is None or rel.is_external:
        return None
    return rel.target_part


# --------------------------------------------------------------------------
# Consumed-text tracking and the safety-net sweep
# --------------------------------------------------------------------------
class Consumed:
    """Set of (part name, element path) for every text node already extracted."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def add(self, part: str, element: etree._Element) -> None:
        self._seen.add((part, element.getroottree().getpath(element)))

    def add_all(self, part: str, elements: Iterable[etree._Element]) -> None:
        for element in elements:
            self.add(part, element)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._seen


TEXT_NODES = xp(
    "//w:t[not(ancestor::mc:Fallback) and not(ancestor::w:moveFrom) and not(ancestor::w:del)]"
    " | //a:t[not(ancestor::mc:Fallback)]"
)


def sweep(parts: Iterable, consumed: Consumed, ctx: Context, prefixes: tuple[str, ...]) -> list[RawBlock]:
    """Emit text nodes no structured extractor consumed, one block per part."""
    blocks: list[RawBlock] = []
    for part in parts:
        name = part_name(part)
        if not name.startswith(prefixes):
            continue
        root = part_root(part)
        if root is None:
            continue
        missed = [
            node for node in TEXT_NODES(root)
            if clean(node.text) and (name, node.getroottree().getpath(node)) not in consumed
        ]
        if not missed:
            continue
        location = f"other text ({name})"
        ctx.warn(UNCLAIMED_TEXT, location, f"{len(missed)} text node(s) found outside known structures")
        pieces: list[Piece] = []
        for node in missed:
            if pieces:
                pieces.append(Piece(" ", kind="sep"))
            pieces.append(Piece(node.text))
        blocks.append(RawBlock(kind="other", location=location, pieces=pieces, source="xml"))
    return blocks


def link_address(target: str) -> str:
    """The part of a link target a reader would see (``mailto:a@b`` -> ``a@b``)."""
    return target.split(":", 1)[1] if target.lower().startswith(("mailto:", "tel:")) else target


def link_sweep(parts: Iterable, blocks: list[RawBlock], prefixes: tuple[str, ...]) -> list[RawBlock]:
    """External hyperlink targets whose address appears in no extracted block.

    Covers links the structured extractors do not read (PPTX runs and shapes,
    DOCX table cells, notes, comments, text boxes). Targets live in ``.rels``
    files, so the text sweep cannot see them.
    """
    seen = " ".join(p.text for b in blocks for p in b.pieces).lower()
    out: list[RawBlock] = []
    for part in parts:
        name = part_name(part)
        if not name.startswith(prefixes):
            continue
        for rel in list(rels(part).values()):
            if not rel.is_external or not rel.reltype.endswith("/hyperlink"):
                continue
            target = clean(rel.target_ref)
            address = link_address(target).lower()
            if address and address not in seen:
                seen += " " + address
                out.append(RawBlock(
                    kind="link", location=f"links ({name}), link {len(out) + 1}", source="xml",
                    pieces=[Piece("Link target", kind="label"), Piece(": ", kind="sep"), Piece(target)],
                ))
    return out


# --------------------------------------------------------------------------
# Paragraph-like text collection for DrawingML (a:p / a:t)
# --------------------------------------------------------------------------
def drawingml_text(container: etree._Element, part: str, consumed: Consumed) -> str:
    """Text of all ``a:p`` paragraphs under ``container``, joined with spaces."""
    paragraphs = []
    for p in xp(".//a:p[not(ancestor::mc:Fallback)]")(container):
        runs = []
        for node in p.iter(q("a", "t"), q("a", "br")):
            if node.tag == q("a", "br"):
                runs.append(" ")
            else:
                runs.append(node.text or "")
                consumed.add(part, node)
        text = clean("".join(runs))
        if text:
            paragraphs.append(text)
    return " ".join(paragraphs)


# --------------------------------------------------------------------------
# Charts and SmartArt
# --------------------------------------------------------------------------
_CHART_TITLES = xp("//c:title//a:t | //c:tx//a:t")
_CHART_VALUES = xp("//c:tx//c:v | //c:cat//c:v")


def chart_text(chart_part, consumed: Consumed) -> str:
    """Titles, axis titles, series names and category labels of a chart."""
    root = part_root(chart_part)
    if root is None:
        return ""
    name = part_name(chart_part)
    values: list[str] = []
    for node in _CHART_TITLES(root):
        consumed.add(name, node)
        values.append(node.text or "")
    for node in _CHART_VALUES(root):
        values.append(node.text or "")
    seen: list[str] = []
    for value in (clean(v) for v in values):
        if value and value not in seen:
            seen.append(value)
    return " | ".join(seen)


def smartart_text(owner_part, data_rel_id: str, consumed: Consumed) -> str:
    """Text of a SmartArt diagram (its data part). The cached drawing part has
    the same text, so it is marked consumed too."""
    data_part = related(owner_part, data_rel_id)
    if data_part is None:
        return ""
    root = part_root(data_part)
    if root is None:
        return ""
    text = drawingml_text(root, part_name(data_part), consumed)
    for rel in rels(owner_part).values():
        if rel.reltype == RT_DIAGRAM_DRAWING and not rel.is_external:
            drawing = rel.target_part
            droot = part_root(drawing)
            if droot is not None:
                consumed.add_all(part_name(drawing), xp("//a:t")(droot))
    return text


# --------------------------------------------------------------------------
# Embedded objects
# --------------------------------------------------------------------------
_EMBEDDING_RELTYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk",
}


def count_embedded(package) -> int:
    """Embedded files/OLE objects whose content is not extracted.

    Workbooks behind charts are not counted: the values a chart displays are
    extracted from its cached data.
    """
    return sum(
        1 for part in package.iter_parts() if "/charts/" not in str(part.partname)
        for rel in rels(part).values() if rel.reltype in _EMBEDDING_RELTYPES
    )
