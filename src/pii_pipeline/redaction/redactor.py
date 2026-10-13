"""Core redaction engine: blocks + entities -> RedactedBlocks + trace records.

Public API
----------
``redact_block(block, entities, placeholder_manager=None)``
``redact_document(blocks, entities, placeholder_manager=None)``
``resolve_overlaps(entities)``

Overlap resolution
------------------
Entities whose spans overlap (share at least one character; merely touching
spans do NOT overlap) are grouped into a cluster. For each cluster:

1. The WINNER decides the label (pii_type, confidence, detector). Winner order:
   a. higher confidence (compared after rounding to 6 decimals, so values that
      are "effectively equal" tie),
   b. longer span,
   c. earlier start,
   d. pii_type, then detector (alphabetical),
   e. position in the input list.
2. The replaced span is the UNION of all spans in the cluster. A loser that
   sticks out past the winner would otherwise leave part of a detected value in
   the output, so the replacement always covers every detected character.
   When losers are fully inside the winner (the common case) the union equals
   the winner's span.

Offsets
-------
All offsets refer to the ORIGINAL text and are code-point indexes (Python
``str`` slicing), not bytes. The output is built left to right from slices of
the original text, never by mutating the text or by ``str.replace``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pii_pipeline.schemas import Entity, RedactedBlock, TextBlock

from .placeholder_manager import PlaceholderManager
from .traceability import TraceRecord
from .validators import (
    InvalidBlockError,
    InvalidEntityError,
    RedactionVerificationError,
    check_entity_fields,
    validate_block,
    validate_entities,
    verify_redaction,
)

#: Confidences are rounded to this many decimals before being compared.
CONFIDENCE_PRECISION = 6


@dataclass(frozen=True)
class MergedSpan:
    """One span to replace: a cluster of overlapping entities (no raw value)."""

    start: int
    end: int
    pii_type: str
    confidence: float
    detector: str
    merged_entities: int


def _priority(item: tuple[int, Entity]) -> tuple:
    index, entity = item
    return (
        -round(entity.confidence, CONFIDENCE_PRECISION),
        -(entity.end - entity.start),
        entity.start,
        entity.pii_type,
        entity.detector,
        index,
    )


def resolve_overlaps(entities: Sequence[Entity]) -> list[MergedSpan]:
    """Collapse validated entities into non-overlapping spans, sorted by start.

    Expects entities that already passed validation (valid, non-empty spans).
    The result does not depend on the order of ``entities`` except for the
    final tie-break, which only matters for otherwise identical entities.
    """
    indexed = sorted(enumerate(entities), key=lambda p: (p[1].start, p[1].end, p[0]))
    clusters: list[list[tuple[int, Entity]]] = []
    cluster_end = -1
    for item in indexed:
        entity = item[1]
        if clusters and entity.start < cluster_end:
            clusters[-1].append(item)
            cluster_end = max(cluster_end, entity.end)
        else:
            clusters.append([item])
            cluster_end = entity.end

    spans: list[MergedSpan] = []
    for cluster in clusters:
        winner = min(cluster, key=_priority)[1]
        spans.append(
            MergedSpan(
                start=min(e.start for _, e in cluster),
                end=max(e.end for _, e in cluster),
                pii_type=winner.pii_type,
                confidence=winner.confidence,
                detector=winner.detector,
                merged_entities=len(cluster),
            )
        )
    return spans


def _apply_replacements(text: str, records: Sequence[TraceRecord]) -> str:
    """Build the redacted text from the ORIGINAL text (records sorted by start)."""
    parts: list[str] = []
    cursor = 0
    for record in records:
        parts.append(text[cursor:record.start])
        parts.append(record.placeholder)
        cursor = record.end
    parts.append(text[cursor:])
    return "".join(parts)


def redact_block(
    block: TextBlock,
    entities: Sequence[Entity],
    placeholder_manager: PlaceholderManager | None = None,
) -> tuple[RedactedBlock, list[TraceRecord]]:
    """Redact one block.

    Pass the same ``placeholder_manager`` for every block of a document so that
    repeated values keep the same placeholder. Raises a ``RedactionError``
    subclass on invalid input or if the post-redaction check fails; in that
    case nothing is returned (fail closed).
    """
    manager = placeholder_manager if placeholder_manager is not None else PlaceholderManager()
    validated = validate_entities(block, entities)  # raises before any state changes
    spans = resolve_overlaps(validated)

    records: list[TraceRecord] = []
    for span in spans:
        value = block.text[span.start:span.end]
        placeholder = manager.get_placeholder(block.file, span.pii_type, value)
        records.append(
            TraceRecord(
                file=block.file,
                block_index=block.index,
                location=block.location,
                start=span.start,
                end=span.end,
                pii_type=span.pii_type,
                confidence=span.confidence,
                detector=span.detector,
                placeholder=placeholder,
                merged_entities=span.merged_entities,
            )
        )

    redacted_text = _apply_replacements(block.text, records)
    result = verify_redaction(block, redacted_text, records, validated)
    if not result.passed:
        raise RedactionVerificationError(
            f"Post-redaction verification failed for file={block.file!r}, "
            f"block_index={block.index}: " + " ".join(result.failures)
        )

    # schemas.Entity.placeholder is "filled in by redaction"; set only once verification passed.
    for entity in validated:
        entity.placeholder = next(
            r.placeholder for r in records if r.start <= entity.start and entity.end <= r.end
        )

    redacted = RedactedBlock(
        file=block.file,
        block_index=block.index,
        location=block.location,
        text=redacted_text,
    )
    return redacted, records


def redact_document(
    blocks: Sequence[TextBlock],
    entities: Sequence[Entity],
    placeholder_manager: PlaceholderManager | None = None,
) -> tuple[list[RedactedBlock], list[TraceRecord]]:
    """Redact many blocks (possibly from several files) in one call.

    Blocks are processed in the order given, so placeholder numbers follow that
    order. Output blocks and trace records follow the same order. Every entity
    must belong to one of the supplied blocks, otherwise InvalidEntityError.
    Placeholders are scoped per file by the PlaceholderManager.
    """
    manager = placeholder_manager if placeholder_manager is not None else PlaceholderManager()

    grouped: dict[tuple[str, int], list[Entity]] = {}
    for block in blocks:
        validate_block(block)
        key = (block.file, block.index)
        if key in grouped:
            raise InvalidBlockError(
                f"Duplicate block: file={block.file!r}, block_index={block.index}."
            )
        grouped[key] = []

    for entity in entities:
        check_entity_fields(entity)
        key = (entity.file, entity.block_index)
        if key not in grouped:
            raise InvalidEntityError("entity refers to a file/block that was not supplied", entity)
        grouped[key].append(entity)

    redacted_blocks: list[RedactedBlock] = []
    all_records: list[TraceRecord] = []
    for block in blocks:
        redacted, records = redact_block(block, grouped[(block.file, block.index)], manager)
        redacted_blocks.append(redacted)
        all_records.extend(records)
    return redacted_blocks, all_records
