"""Test helpers. All data in the tests is synthetic (fake names, *.test emails)."""

from __future__ import annotations

from collections.abc import Iterable

from pii_pipeline.schemas import Entity, TextBlock


def make_block(text: str, file: str = "doc.pdf", index: int = 0, location: str = "page 1") -> TextBlock:
    return TextBlock(file=file, location=location, index=index, text=text)


def span_entity(
    block: TextBlock,
    start: int,
    end: int,
    pii_type: str = "PERSON",
    confidence: float = 0.9,
    detector: str = "fake",
) -> Entity:
    """Entity for ``block.text[start:end]`` (value taken from the text)."""
    return Entity(
        file=block.file,
        block_index=block.index,
        start=start,
        end=end,
        pii_type=pii_type,
        confidence=confidence,
        detector=detector,
        value=block.text[start:end],
    )


def make_entity(
    block: TextBlock,
    needle: str,
    pii_type: str = "PERSON",
    confidence: float = 0.9,
    detector: str = "fake",
    occurrence: int = 0,
) -> Entity:
    """Entity for the ``occurrence``-th (0-based) appearance of ``needle``."""
    start = -1
    for _ in range(occurrence + 1):
        start = block.text.index(needle, start + 1)
    return span_entity(block, start, start + len(needle), pii_type, confidence, detector)


def leaked(haystack: str, secrets: Iterable[str]) -> bool:
    """True if any secret occurs in haystack. Returns a bool so that a failing
    assertion never prints the secrets or the haystack."""
    return any(secret in haystack for secret in secrets)
