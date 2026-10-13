"""DOCX extraction.

Output order: body (paragraphs, tables, text boxes, images, charts, SmartArt
in document order), then headers/footers per section, footnotes, endnotes,
comments, any text the safety-net sweep found, and document properties.
"""

from __future__ import annotations

from pathlib import Path

import docx

from ..base import Context, RawBlock
from ..metadata import ooxml_properties
from ..ooxml import Consumed, count_embedded, link_sweep, sweep
from ..validation import UNSUPPORTED_OBJECT
from .body import BodyWalker, page_map
from .drawings import Counters
from .parts import comment_blocks, header_footer_blocks, note_blocks

def _style_names(document) -> dict[str, str]:
    names = {}
    for style in document.styles:
        try:
            names[style.style_id] = style.name or style.style_id
        except Exception:  # malformed style entries must not stop extraction
            continue
    return names


def extract_docx(path: Path, ctx: Context) -> list[RawBlock]:
    document = docx.Document(str(path))
    consumed = Consumed()
    counters = Counters()
    walker = BodyWalker(ctx, consumed, _style_names(document), counters)
    walker.pages = page_map(document.element.body)

    blocks = walker.container(document.element.body, document.part)
    blocks += header_footer_blocks(document, walker)
    blocks += note_blocks(document, ctx, consumed, counters)
    blocks += comment_blocks(document, ctx, consumed, counters)

    package = document.part.package
    embedded = count_embedded(package)
    if embedded:
        ctx.warn(UNSUPPORTED_OBJECT, "document", f"{embedded} embedded object(s)/file(s) not extracted")

    blocks += sweep(package.iter_parts(), consumed, ctx, prefixes=("word/",))
    blocks += link_sweep(package.iter_parts(), blocks, prefixes=("word/",))
    properties = ooxml_properties(package)
    if properties is not None:
        blocks.append(properties)
    return blocks
