"""Validation for blocks, entities and finished redactions.

Security rule for this whole module: error messages and results may mention
file, block_index, start, end and pii_type, but NEVER ``Entity.value`` or any
slice of the block text.

Policy: invalid detector output raises (fail closed). We never silently skip an
entity, because a skipped entity is PII that would reach the LLM.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

from pii_pipeline.schemas import Entity, TextBlock

from .traceability import TraceRecord

#: Allowed PII type names. They become part of a placeholder such as
#: ``[PERSON_1]``, so they must not contain brackets, spaces, newlines, etc.
PII_TYPE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
MAX_PII_TYPE_LENGTH = 64


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------
class RedactionError(Exception):
    """Base class for all errors raised by the redaction module."""


class InvalidBlockError(RedactionError):
    """A TextBlock (or the set of blocks) is malformed."""


class InvalidEntityError(RedactionError):
    """An Entity is malformed or inconsistent with its block.

    Attributes hold only safe metadata (never the raw value).
    """

    def __init__(self, reason: str, entity: Any) -> None:
        self.reason = reason
        self.fields = safe_entity_fields(entity)
        details = ", ".join(f"{k}={v}" for k, v in self.fields.items())
        super().__init__(f"Invalid entity: {reason} ({details})")


class RedactionVerificationError(RedactionError):
    """The post-redaction safety check failed; no output is released."""


# --------------------------------------------------------------------------
# Safe description helpers
# --------------------------------------------------------------------------
def is_valid_pii_type(pii_type: Any) -> bool:
    """True if ``pii_type`` is a string like ``PERSON`` or ``EMPLOYEE_ID``."""
    return (
        isinstance(pii_type, str)
        and len(pii_type) <= MAX_PII_TYPE_LENGTH
        and PII_TYPE_PATTERN.fullmatch(pii_type) is not None
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def safe_entity_fields(entity: Any) -> dict[str, str]:
    """Describe an entity using ONLY non-secret fields, tolerating bad types."""
    file = getattr(entity, "file", None)
    block_index = getattr(entity, "block_index", None)
    start = getattr(entity, "start", None)
    end = getattr(entity, "end", None)
    pii_type = getattr(entity, "pii_type", None)
    return {
        "file": repr(file) if isinstance(file, str) else "?",
        "block_index": str(block_index) if _is_int(block_index) else "?",
        "start": str(start) if _is_int(start) else "?",
        "end": str(end) if _is_int(end) else "?",
        "pii_type": pii_type if is_valid_pii_type(pii_type) else "<invalid>",
    }


# --------------------------------------------------------------------------
# Block / entity validation
# --------------------------------------------------------------------------
def validate_block(block: Any) -> None:
    """Raise InvalidBlockError unless ``block`` is a well-formed TextBlock."""
    if not isinstance(block, TextBlock):
        raise InvalidBlockError("Block is not a TextBlock.")
    if not isinstance(block.file, str):
        raise InvalidBlockError("Block file must be a string.")
    if not _is_int(block.index):
        raise InvalidBlockError("Block index must be an integer.")
    if not isinstance(block.location, str):
        raise InvalidBlockError("Block location must be a string.")
    if not isinstance(block.text, str):
        raise InvalidBlockError("Block text must be a string.")


def check_entity_fields(entity: Any) -> None:
    """Check that every Entity field has a sane type/value (no block needed)."""
    if not isinstance(entity, Entity):
        raise InvalidEntityError("object is not an Entity", entity)
    if not isinstance(entity.file, str):
        raise InvalidEntityError("file must be a string", entity)
    if not _is_int(entity.block_index):
        raise InvalidEntityError("block_index must be an integer", entity)
    if not _is_int(entity.start) or not _is_int(entity.end):
        raise InvalidEntityError("start and end must be integers", entity)
    if not is_valid_pii_type(entity.pii_type):
        raise InvalidEntityError(
            "pii_type must be upper-case letters, digits and underscores", entity
        )
    confidence = entity.confidence
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
    ):
        raise InvalidEntityError("confidence must be a number between 0 and 1", entity)
    if not isinstance(entity.detector, str):
        raise InvalidEntityError("detector must be a string", entity)
    if not isinstance(entity.value, str):
        raise InvalidEntityError("value must be a string", entity)


def validate_entity(block: TextBlock, entity: Entity) -> None:
    """Raise InvalidEntityError unless ``entity`` is valid for ``block``.

    The value/span consistency check compares ``entity.value`` with
    ``block.text[start:end]`` but never reveals either one in the error.
    """
    check_entity_fields(entity)
    if entity.file != block.file:
        raise InvalidEntityError("entity belongs to a different file", entity)
    if entity.block_index != block.index:
        raise InvalidEntityError("entity belongs to a different block", entity)
    if entity.start < 0:
        raise InvalidEntityError("start is negative", entity)
    if entity.end < 0:
        raise InvalidEntityError("end is negative", entity)
    if entity.start > entity.end:
        raise InvalidEntityError("start is greater than end", entity)
    if entity.start == entity.end:
        raise InvalidEntityError("span is empty", entity)
    if entity.end > len(block.text):
        raise InvalidEntityError("end is beyond the end of the text", entity)
    if entity.value != block.text[entity.start:entity.end]:
        raise InvalidEntityError("Entity span does not match the supplied text.", entity)


def validate_entities(block: TextBlock, entities: Sequence[Entity]) -> list[Entity]:
    """Validate the block and every entity; return the entities as a list."""
    validate_block(block)
    checked = list(entities)
    for entity in checked:
        validate_entity(block, entity)
    return checked


# --------------------------------------------------------------------------
# Post-redaction verification
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ValidationResult:
    """Outcome of :func:`verify_redaction`. ``failures`` are safe messages."""

    file: str
    block_index: int
    passed: bool
    failures: tuple[str, ...] = ()


def verify_redaction(
    block: TextBlock,
    redacted_text: str,
    records: Sequence[TraceRecord],
    entities: Sequence[Entity],
) -> ValidationResult:
    """Check a finished redaction without trusting how it was produced.

    The redacted string has a different length than the original, so original
    offsets can NOT be used on it directly. Instead we walk the original text
    and the redacted text in parallel, translating positions as we go:

    1. Every piece of text between replacements must be byte-for-byte equal to
       the same piece of the original (nothing else was changed).
    2. Each replacement must appear in the output exactly as its placeholder.
    3. Every detected entity span must lie fully inside one replacement span,
       i.e. none of it can be left in the output.
    """
    failures: list[str] = []
    original = block.text
    ordered = sorted(records, key=lambda r: (r.start, r.end))

    cursor_in = 0   # position in the original text
    cursor_out = 0  # position in the redacted text
    structure_ok = True
    for record in ordered:
        if not (cursor_in <= record.start < record.end <= len(original)):
            failures.append(
                f"Replacement span [{record.start}:{record.end}] is invalid or overlaps."
            )
            structure_ok = False
            break
        gap = original[cursor_in:record.start]
        if redacted_text[cursor_out:cursor_out + len(gap)] != gap:
            failures.append(f"Text before original offset {record.start} was altered.")
            structure_ok = False
            break
        cursor_out += len(gap)
        placeholder = record.placeholder
        if not placeholder or redacted_text[cursor_out:cursor_out + len(placeholder)] != placeholder:
            failures.append(
                f"Placeholder for [{record.start}:{record.end}] is missing from the output."
            )
            structure_ok = False
            break
        cursor_out += len(placeholder)
        cursor_in = record.end
    if structure_ok and redacted_text[cursor_out:] != original[cursor_in:]:
        failures.append("Text after the last replacement was altered.")

    for entity in entities:
        covered = any(r.start <= entity.start and entity.end <= r.end for r in ordered)
        if not covered:
            fields = safe_entity_fields(entity)
            failures.append(
                "Detected entity is not covered by any replacement "
                f"(start={fields['start']}, end={fields['end']}, pii_type={fields['pii_type']})."
            )

    return ValidationResult(
        file=block.file,
        block_index=block.index,
        passed=not failures,
        failures=tuple(failures),
    )
