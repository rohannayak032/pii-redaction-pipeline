"""Checks run before blocks are returned.

* Contract violations are bugs: they RAISE (fail closed, nothing is returned).
* Suspicious extraction (empty, low confidence, skipped content) produces a
  coded ``ExtractionWarning``. Messages never contain document text.
"""

from __future__ import annotations

import math
from typing import Sequence

from pii_pipeline.schemas import TextBlock

from .base import BlockMeta, Context, ExtractionError

LOW_OCR_CONFIDENCE = 0.6

# Warning codes (documented in README.md).
NO_TEXT_EXTRACTED = "NO_TEXT_EXTRACTED"
EMPTY_FILE = "EMPTY_FILE"
PAGE_NO_TEXT = "PAGE_NO_TEXT"
LOW_CONFIDENCE = "LOW_OCR_CONFIDENCE"
LOW_COVERAGE = "LOW_COVERAGE"
SKIPPED_IMAGE = "SKIPPED_IMAGE"
UNCLAIMED_TEXT = "UNCLAIMED_TEXT"
UNSUPPORTED_OBJECT = "UNSUPPORTED_OBJECT"
EXTENSION_MISMATCH = "EXTENSION_MISMATCH"


def check_contract(blocks: Sequence[TextBlock], meta: Sequence[BlockMeta]) -> None:
    """Raise ExtractionError if the output breaks the TextBlock contract."""
    if len(blocks) != len(meta):
        raise ExtractionError("Internal error: blocks and metadata are misaligned.")
    for expected, (block, info) in enumerate(zip(blocks, meta)):
        where = f"block {expected}"
        if block.index != expected or info.index != expected:
            raise ExtractionError(f"Internal error: {where} has a non-sequential index.")
        if not isinstance(block.text, str) or not block.text.strip():
            raise ExtractionError(f"Internal error: {where} has empty text.")
        if not isinstance(block.location, str) or not block.location.strip():
            raise ExtractionError(f"Internal error: {where} has no location.")
        conf = block.ocr_confidence
        if conf is not None and (not math.isfinite(conf) or not 0.0 <= conf <= 1.0):
            raise ExtractionError(f"Internal error: {where} has an invalid OCR confidence.")
        n = len(block.text)
        for _, start, end in info.cells:
            if not 0 <= start < end <= n:
                raise ExtractionError(f"Internal error: {where} has an invalid cell span.")
        for start, end, _, _ in info.words:
            if not 0 <= start < end <= n:
                raise ExtractionError(f"Internal error: {where} has an invalid word span.")


def report_skipped_images(ctx: Context) -> None:
    if ctx.skipped_images:
        detail = ", ".join(f"{n} {reason}" for reason, n in sorted(ctx.skipped_images.items()))
        ctx.warn(SKIPPED_IMAGE, "document", f"images not OCR'd: {detail}")


def check_not_empty(ctx: Context, blocks: Sequence[TextBlock], file_size: int) -> None:
    if not blocks and file_size > 0:
        ctx.warn(
            NO_TEXT_EXTRACTED, "document",
            "the file is not empty but no text was extracted; check it by hand",
        )
