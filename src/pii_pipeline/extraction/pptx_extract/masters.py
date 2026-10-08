"""Text on slide masters, layouts, the notes master and the handout master.

Footer / date / header placeholders and ordinary (non-placeholder) text
shapes are visible on every slide that uses the template, so they are
extracted. Other placeholders only hold prompt text ("Click to edit Master
title style"); that text is marked as seen and not emitted. Identical
template text is emitted once.
"""

from __future__ import annotations

from ..base import RawBlock
from ..ooxml import Consumed, drawingml_text, part_name, part_root, rels, xp

RT_NOTES_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster"
RT_HANDOUT_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/handoutMaster"
_SHAPES = xp("//p:sp")
_PLACEHOLDER = xp("./p:nvSpPr/p:nvPr/p:ph")
_CNVPR = xp("./p:nvSpPr/p:cNvPr")
_VISIBLE_PLACEHOLDERS = {"ftr", "dt", "hdr"}
_ROLE = {"ftr": "footer", "dt": "date", "hdr": "header"}


def _template_parts(prs):
    for m, master in enumerate(prs.slide_masters, start=1):
        yield master.part, f"slide master {m}"
        for l, layout in enumerate(master.slide_layouts, start=1):
            yield layout.part, f"layout {l} (master {m})"
    for rel in rels(prs.part).values():
        if rel.is_external:
            continue
        if rel.reltype == RT_NOTES_MASTER:
            yield rel.target_part, "notes master"
        elif rel.reltype == RT_HANDOUT_MASTER:
            yield rel.target_part, "handout master"


def template_blocks(prs, consumed: Consumed) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    seen: set[str] = set()
    for part, label in _template_parts(prs):
        root = part_root(part)
        if root is None:
            continue
        name = part_name(part)
        for sp in _SHAPES(root):
            ph = next(iter(_PLACEHOLDER(sp)), None)
            text = drawingml_text(sp, name, consumed)
            if ph is not None and ph.get("type", "body") not in _VISIBLE_PLACEHOLDERS:
                continue   # prompt text only; already marked consumed above
            if not text or text in seen:
                continue
            seen.add(text)
            if ph is not None:
                where = _ROLE[ph.get("type")]
            else:
                cnvpr = next(iter(_CNVPR(sp)), None)
                where = f"shape {cnvpr.get('id') if cnvpr is not None else '?'}"
            blocks.append(RawBlock.simple("template", f"{label}, {where}", text, source="xml"))
    return blocks
