"""
pipeline.py - workflow layer (Application role)
===============================================
process_document(filename, data) runs the team's real modules on one uploaded file:
    validate -> extraction.extract_document_detailed -> detection.detect
             -> redaction.redact_document (verifies every block) -> residual-value check

view(result, idx) turns the outputs into the UI's view-model. The original block text never leaves
the server. Entity.value is sent only inside view()["entities"] so the UI can show each detected
value; trace records, the report, redacted text and every export stay value-free.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Optional

from pii_pipeline.detection.detector import detect
from pii_pipeline.extraction import ExtractionError, ExtractionResult, extract_document_detailed
from pii_pipeline.extraction.dispatcher import _EXTENSIONS
from pii_pipeline.extraction.validation import LOW_OCR_CONFIDENCE
from pii_pipeline.redaction import RedactionError, TraceRecord, build_report, redact_document
from pii_pipeline.schemas import Entity, RedactedBlock

# The extraction module's formats (pdf, docx, pptx); its macro/template variants are not offered.
SUPPORTED = sorted(f".{fmt}" for fmt in _EXTENSIONS)
MAX_FILE_MB = 25          # upload limit of this web app (trust boundary); extraction has none


@dataclass
class DocResult:
    filename: str
    sha256: str
    status: str = "failed"           # success | warning | failed
    error: str = ""
    failed_stage: str = ""
    extraction: Optional[ExtractionResult] = None
    entities: List[Entity] = field(default_factory=list)
    redacted: List[RedactedBlock] = field(default_factory=list)
    records: List[TraceRecord] = field(default_factory=list)
    leaks: List[str] = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)

    @property
    def llm_ready(self) -> bool:
        return self.status != "failed" and not self.leaks

    @cached_property
    def _pages(self) -> Dict[int, Optional[int]]:
        return {m.index: m.page for m in self.extraction.meta} if self.extraction else {}

    def page_of(self, block_index: int) -> Optional[int]:
        return self._pages.get(block_index)

    def redacted_text(self) -> str:
        parts, last = [], None
        for b in self.redacted:
            page = self.page_of(b.block_index)
            if page is not None and page != last:
                parts.append(f"=== Page/Slide {page} ===")
                last = page
            parts.append(b.text)
        return "\n".join(parts)


def _timed(res: DocResult, stage: str, fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    res.timings[stage] = round(time.perf_counter() - t0, 3)
    return out


def residual_leaks(entities: List[Entity], redacted: List[RedactedBlock]) -> List[str]:
    """A detected value that still appears as a whole word in any redacted block (an undetected repeat)."""
    leaks = []
    for e in {e.value: e for e in entities if len(e.value.strip()) >= 3}.values():
        # Whole-word match like detect's name propagation: "Ann" inside "Annual" is not a leak.
        word = re.compile(r"(?<!\w)" + re.escape(e.value) + r"(?!\w)")
        where = next((b.location for b in redacted if word.search(b.text)), None)
        if where is not None:
            leaks.append(f"A detected {e.pii_type} value still appears after redaction ({where}).")
    return leaks


def process_document(filename: str, data: bytes) -> DocResult:
    name = re.sub(r"[^\w.\- ]", "_", os.path.basename(filename)) or "upload"
    res = DocResult(filename=name, sha256=hashlib.sha256(data).hexdigest())
    stage = "validation"
    try:
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED:
            raise ValueError(f"Unsupported file type '{ext or 'none'}'. Supported: {', '.join(SUPPORTED)}.")
        if not data:
            raise ValueError("File is empty (0 bytes).")
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            raise ValueError(f"File exceeds the {MAX_FILE_MB} MB upload limit.")

        stage = "extraction"
        with tempfile.TemporaryDirectory(prefix="pii_") as tmp:
            path = Path(tmp) / name
            path.write_bytes(data)
            res.extraction = _timed(res, "extraction", extract_document_detailed, path)
        blocks = list(res.extraction.blocks)
        if not blocks:
            raise ValueError("No text could be extracted (see the extraction warnings).")

        stage = "detection"
        res.entities = _timed(res, "detection", detect, blocks)

        stage = "redaction"   # raises RedactionVerificationError if any block fails its check
        res.redacted, res.records = _timed(res, "redaction", redact_document, blocks, res.entities)

        stage = "verification"
        res.leaks = _timed(res, "verification", residual_leaks, res.entities, res.redacted)
        res.status = "warning" if res.extraction.warnings or res.leaks else "success"
    except (ValueError, ExtractionError, RedactionError) as e:   # these messages never quote document text
        res.error, res.failed_stage = str(e), stage
    except Exception as e:   # library errors may quote content: report the type only
        res.error, res.failed_stage = f"Unexpected {type(e).__name__} during {stage}.", stage
        print(f"[pii-shield] {name}: {type(e).__name__} during {stage}")
    return res


def view(r: DocResult, idx: int) -> Dict[str, Any]:
    """View-model for the UI: pipeline outputs without raw values or original block text."""
    ex = r.extraction
    blocks = list(ex.blocks) if ex else []
    meta = list(ex.meta) if ex else []
    location = {b.index: b.location for b in blocks}
    ocr = [b.ocr_confidence for b in blocks if b.ocr_confidence is not None]
    report = build_report(r.records)

    placeholders: Dict[str, Dict[str, Any]] = {}
    for rec in r.records:
        p = placeholders.setdefault(rec.placeholder, {"placeholder": rec.placeholder, "pii_type": rec.pii_type,
                                                      "occurrences": 0, "detections": 0, "pages": set()})
        p["occurrences"] += 1
        p["detections"] += rec.merged_entities
        p["pages"].add(r.page_of(rec.block_index))

    return {
        "index": idx,
        "filename": r.filename,
        "file_type": os.path.splitext(r.filename)[1].lstrip(".").lower(),
        "sha256": r.sha256,
        "status": r.status,
        "error": r.error,
        "failed_stage": r.failed_stage,
        "llm_ready": r.llm_ready,
        "block_count": len(blocks),
        "pages": sorted({m.page for m in meta if m.page is not None}),
        "timings": r.timings,
        "leaks": r.leaks,
        "extraction": {
            "warnings": [{"code": w.code, "location": w.location, "detail": w.detail} for w in (ex.warnings if ex else ())],
            "sources": dict(Counter(m.source for m in meta)),
            "kinds": dict(Counter(m.kind for m in meta).most_common()),
            "hidden_blocks": sum(m.hidden for m in meta),
            "table_rows": sum(m.row_index is not None for m in meta),
            "characters": sum(len(b.text) for b in blocks),
            "ocr_blocks": len(ocr),
            "low_ocr_blocks": sum(c < LOW_OCR_CONFIDENCE for c in ocr),
            "low_ocr_threshold": LOW_OCR_CONFIDENCE,
            "lowest_ocr": min(ocr) if ocr else None,
            "mean_ocr": sum(ocr) / len(ocr) if ocr else None,
        },
        "detectors": dict(Counter(e.detector for e in r.entities).most_common()),
        "detected_types": dict(Counter(e.pii_type for e in r.entities).most_common()),
        "entities": [dict(e.public_info(), value=e.value, n=i + 1, location=location.get(e.block_index, ""),
                          page=r.page_of(e.block_index)) for i, e in enumerate(r.entities)],
        "records": [dict(rec.to_dict(), page=r.page_of(rec.block_index)) for rec in r.records],
        "report": report,
        "placeholders": [dict(p, pages=sorted(x for x in p["pages"] if x is not None))
                         for p in placeholders.values()],
        "redacted": [{"block_index": b.block_index, "location": b.location, "page": r.page_of(b.block_index),
                      "text": b.text} for b in r.redacted],
    }
