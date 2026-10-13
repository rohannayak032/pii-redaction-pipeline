"""Redaction and traceability module of the PII Redaction Pipeline.

Typical use::

    from pii_pipeline.redaction import redact_document, build_report

    redacted_blocks, records = redact_document(blocks, entities)
    report = build_report(records)   # safe: never contains raw values
"""

from .placeholder_manager import PlaceholderManager
from .redactor import MergedSpan, redact_block, redact_document, resolve_overlaps
from .traceability import TraceRecord, build_report, report_to_json
from .validators import (
    InvalidBlockError,
    InvalidEntityError,
    RedactionError,
    RedactionVerificationError,
    ValidationResult,
    verify_redaction,
)

__all__ = [
    "InvalidBlockError",
    "InvalidEntityError",
    "MergedSpan",
    "PlaceholderManager",
    "RedactionError",
    "RedactionVerificationError",
    "TraceRecord",
    "ValidationResult",
    "build_report",
    "redact_block",
    "redact_document",
    "report_to_json",
    "resolve_overlaps",
    "verify_redaction",
]
