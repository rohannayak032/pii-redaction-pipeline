"""Safe traceability records and report helpers.

A :class:`TraceRecord` answers "which file and location caused this redaction?"
without ever containing the redacted value. There is deliberately NO ``value``
field on the record, so a raw value cannot end up in a report by accident.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class TraceRecord:
    """One redaction that was applied to one block.

    ``start`` / ``end`` are offsets into the ORIGINAL block text (end is
    exclusive). If several overlapping detections were merged into one
    replacement, the span is the union of them and ``merged_entities`` says how
    many detections it covers.
    """

    file: str
    block_index: int
    location: str
    start: int
    end: int
    pii_type: str
    confidence: float
    detector: str
    placeholder: str
    merged_entities: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Plain dictionary, safe to show, log or serialize."""
        return {
            "file": self.file,
            "block_index": self.block_index,
            "location": self.location,
            "start": self.start,
            "end": self.end,
            "pii_type": self.pii_type,
            "confidence": self.confidence,
            "detector": self.detector,
            "placeholder": self.placeholder,
            "merged_entities": self.merged_entities,
        }


def build_report(records: Iterable[TraceRecord]) -> dict[str, Any]:
    """Build a JSON-friendly report: every finding plus simple counts."""
    findings = list(records)
    return {
        "findings": [record.to_dict() for record in findings],
        "summary": {
            "total_findings": len(findings),
            "by_pii_type": dict(sorted(Counter(r.pii_type for r in findings).items())),
            "by_file": dict(sorted(Counter(r.file for r in findings).items())),
        },
    }


def report_to_json(records: Iterable[TraceRecord], indent: int | None = 2) -> str:
    """Serialize :func:`build_report` output to a JSON string."""
    return json.dumps(build_report(records), indent=indent, ensure_ascii=False)
