"""WordprocessingML text collection.

``paragraph.text`` from python-docx misses text inside insertions, content
controls, fields and some hyperlinks. We walk the XML ourselves instead:

* included: ``w:t`` anywhere in the subtree (runs, ``w:ins``, ``w:hyperlink``,
  ``w:sdt``, ``w:smartTag``, ``w:fldSimple``, ...), tabs/breaks as spaces
* excluded: deleted text (``w:del``, ``w:moveFrom``) and ``mc:Fallback``
  copies (the ``mc:Choice`` branch holds the same content)
* optionally pruned: subtrees handled elsewhere (text boxes, drawings,
  nested tables), so they are not read twice
"""

from __future__ import annotations

from lxml import etree

from ..ooxml import Consumed, q

W_T = q("w", "t")
W_P = q("w", "p")
_SPACE = {q("w", "tab"), q("w", "br"), q("w", "cr"), q("w", "ptab")}
_HYPHEN = q("w", "noBreakHyphen")
ALWAYS_PRUNE = frozenset({q("mc", "Fallback"), q("w", "del"), q("w", "moveFrom"), q("w", "delText")})
DRAWINGS = frozenset({q("w", "drawing"), q("w", "pict"), q("w", "object"), q("w", "txbxContent")})
NESTED_TABLES = frozenset({q("w", "tbl")})


def collect(
    element: etree._Element, part: str, consumed: Consumed, prune: frozenset[str] = frozenset()
) -> str:
    """Text of ``element``'s subtree (paragraphs separated by spaces)."""
    out: list[str] = []
    skip = ALWAYS_PRUNE | prune

    def visit(node: etree._Element) -> None:
        for child in node:
            tag = child.tag
            if not isinstance(tag, str) or tag in skip:
                continue
            if tag == W_T:
                out.append(child.text or "")
                consumed.add(part, child)
            elif tag in _SPACE:
                out.append(" ")
            elif tag == _HYPHEN:
                out.append("-")
            else:
                if tag == W_P and out:
                    out.append(" ")
                visit(child)

    visit(element)
    return "".join(out)
