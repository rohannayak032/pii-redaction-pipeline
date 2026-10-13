"""Everything inside a paragraph's drawings: text boxes, images (OCR + alt
text), charts and SmartArt. Embedded OLE objects are flagged."""

from __future__ import annotations

from lxml import etree

from ..base import Context, Piece, RawBlock
from ..normalize import clean
from ..ocr import ocr_blob
from ..ooxml import Consumed, NS, chart_text, part_name, related, smartart_text, xp
from ..validation import UNSUPPORTED_OBJECT
from .text import collect

# Outermost drawing containers of a paragraph, in document order.
_CONTAINERS = xp(
    ".//*[self::w:drawing or self::w:pict or self::w:object]"
    "[not(ancestor::mc:Fallback)]"
    "[not(ancestor::w:drawing or ancestor::w:pict or ancestor::w:object)]"
)
_TEXTBOXES = xp(".//w:txbxContent[not(ancestor::mc:Fallback)][not(ancestor::w:txbxContent)]")
_IMAGES = xp(".//a:blip[not(ancestor::mc:Fallback)] | .//v:imagedata[not(ancestor::mc:Fallback)]")
_CHARTS = xp(".//c:chart[not(ancestor::mc:Fallback)]")
_DIAGRAMS = xp(".//dgm:relIds[not(ancestor::mc:Fallback)]")
_DOC_PR = xp(".//wp:docPr | .//v:shape")
_R = f"{{{NS['r']}}}"


class Counters:
    """File-wide numbering, so every image/text box has a unique location."""

    def __init__(self) -> None:
        self.textbox = self.image = self.chart = self.diagram = self.alt = 0


def drawing_blocks(
    paragraph: etree._Element, owner, prefix: str, ctx: Context, consumed: Consumed, counters: Counters,
) -> list[RawBlock]:
    """Blocks for all drawings inside ``paragraph`` (``owner`` is its OPC part)."""
    name = part_name(owner)
    blocks: list[RawBlock] = []
    for container in _CONTAINERS(paragraph):
        for box in _TEXTBOXES(container):
            text = collect(box, name, consumed)
            if clean(text):
                counters.textbox += 1
                blocks.append(RawBlock.simple("text_box", f"{prefix}, text box {counters.textbox}", text, source="xml"))

        for node in _IMAGES(container):
            rid = node.get(f"{_R}embed") or node.get(f"{_R}id")
            if not rid:
                if node.get(f"{_R}link"):
                    ctx.skip_image("linked (external) image")
                continue
            image_part = related(owner, rid)
            if image_part is None:
                continue
            counters.image += 1
            blocks += ocr_blob(image_part.blob, ctx, f"{prefix}, image {counters.image}")

        for node in _CHARTS(container):
            rid = node.get(f"{_R}id")
            chart_part = related(owner, rid)
            if chart_part is not None:
                text = chart_text(chart_part, consumed)
                if text:
                    counters.chart += 1
                    blocks.append(RawBlock.simple("chart", f"{prefix}, chart {counters.chart}", text, source="xml"))

        for node in _DIAGRAMS(container):
            rid = node.get(f"{_R}dm")
            if rid:
                text = smartart_text(owner, rid, consumed)
                if text:
                    counters.diagram += 1
                    blocks.append(RawBlock.simple("smartart", f"{prefix}, diagram {counters.diagram}", text, source="xml"))

        for node in _DOC_PR(container):
            alt = " ".join(v for v in (node.get("title"), node.get("descr"), node.get("alt")) if clean(v))
            if alt:
                counters.alt += 1
                blocks.append(RawBlock(
                    kind="alt_text", location=f"{prefix}, alt text {counters.alt}", source="xml",
                    pieces=[Piece("Alt text", kind="label"), Piece(": ", kind="sep"), Piece(alt)],
                ))

        if container.tag == f"{{{NS['w']}}}object":
            ctx.warn(UNSUPPORTED_OBJECT, prefix, "embedded object (OLE) content not extracted; preview image OCR'd if present")
    return blocks
