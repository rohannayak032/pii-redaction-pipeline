# Redaction and Traceability module

Part of the **PII Redaction Pipeline**. This module is the security boundary
between detection and the application/LLM: it takes text blocks and the PII
entities found in them, and returns redacted blocks plus a safe report.

## 1. What it does

* Replaces every detected PII span with a placeholder such as `[PERSON_1]`.
* Gives the same value the same placeholder within a file.
* Resolves overlapping detections without corrupting the text.
* Produces a traceability report (file, location, offsets, type, confidence,
  detector, placeholder) that **never contains the raw value**.
* Verifies every redaction after it is built and fails closed if anything is off.

It does **not** detect PII, extract text, evaluate accuracy, or call any
external service. Everything is local and uses only the standard library.

## 2. Where it fits

```
PDF/DOCX/PPTX -> extraction -> TextBlock -> detection -> Entity
                                                           |
                                          redaction + traceability  (this module)
                                                           |
                                    RedactedBlock + TraceRecord report -> app / LLM
```

## 3. Input / output contract

Uses the shared classes from `pii_pipeline/schemas.py` unchanged
(`TextBlock`, `Entity`, `RedactedBlock`). Nothing in `schemas.py` is modified.

* `Entity.start` / `Entity.end` are offsets into the **original**
  `TextBlock.text`, `end` exclusive (`text[start:end]`). Offsets are Python
  string (code point) indexes, not bytes.
* `Entity.value` must equal `text[start:end]` and is treated as secret.
* `entity.file` / `entity.block_index` must match the block's `file` / `index`.

## 4. Public API

```python
from pii_pipeline.redaction import (
    redact_block, redact_document, PlaceholderManager,
    build_report, report_to_json, TraceRecord,
    verify_redaction, resolve_overlaps,
    RedactionError, InvalidEntityError, InvalidBlockError, RedactionVerificationError,
)

redact_document(blocks: Sequence[TextBlock], entities: Sequence[Entity],
                placeholder_manager: PlaceholderManager | None = None
                ) -> tuple[list[RedactedBlock], list[TraceRecord]]

redact_block(block: TextBlock, entities: Sequence[Entity],
             placeholder_manager: PlaceholderManager | None = None
             ) -> tuple[RedactedBlock, list[TraceRecord]]

build_report(records) -> dict          # {"findings": [...], "summary": {...}}
report_to_json(records, indent=2) -> str
```

`redact_document` is the normal entry point for the application layer. Pass all
blocks (any number of files) and all entities. Use `redact_block` with a shared
`PlaceholderManager` if you process blocks one at a time.

## 5. Placeholder behavior

* Format: `[<PII_TYPE>_<n>]`, numbered from 1 **separately per PII type**
  (`[PERSON_1]`, `[PERSON_2]`, `[EMAIL_1]`).
* Same file + same `pii_type` + exactly the same string -> same placeholder.
* Each file has its own numbering (`file_a.pdf` and `file_b.pdf` can both have a
  `[PERSON_1]`).
* Matching is **exact** (case- and whitespace-sensitive). The single hook to
  change this later is `PlaceholderManager._normalize`.
* Numbers are assigned in the order blocks are passed and, inside a block, left
  to right by position.
* The manager stores only a salted hash of each value, never the value itself.
* `pii_type` must match `[A-Z][A-Z0-9_]*` (max 64 chars) because it becomes part
  of the placeholder. Any other type is rejected.

## 6. Overlap resolution

Spans that share at least one character are grouped. Touching spans
(`end == next start`) are **not** overlapping.

For each group:

1. The **winner** gives the label (type, confidence, detector). Order:
   higher confidence (rounded to 6 decimals, so "effectively equal" ties) ->
   longer span -> earlier start -> `pii_type` then `detector` alphabetically ->
   input position.
2. The replaced span is the **union** of the group. If a lower-confidence entity
   sticks out past the winner, using only the winner's span would leave part of
   a detected value in the output, so the union is replaced instead.
   When the losers are fully inside the winner (the usual case) the union is the
   winner's span.

The result does not depend on the order of the entity list. The report shows one
record per replacement, with `merged_entities` telling you how many detections it
covers.

## 7. Offset handling

All offsets refer to the original text. The redacted text is built left to right
from slices of the original plus placeholders (`redactor._apply_replacements`).
The text is never mutated and `str.replace` is not used.

## 8. Post-redaction safety check

The output length differs from the input, so original offsets are never applied
to the redacted string. `verify_redaction` walks the original and the output in
parallel and checks that (a) text between replacements is identical to the
original, (b) each placeholder is present exactly where expected, and (c) every
detected entity span is fully inside a replacement. If anything fails,
`redact_block` raises `RedactionVerificationError` and returns nothing.

## 9. Traceability

Each applied replacement produces a `TraceRecord` (frozen dataclass):

```python
{"file": "demo.pdf", "block_index": 0, "location": "page 1", "start": 8, "end": 19,
 "pii_type": "PERSON", "confidence": 0.93, "detector": "ner",
 "placeholder": "[PERSON_1]", "merged_entities": 1}
```

There is no `value` field at all. Note that `file` and `location` are copied as
given, so avoid file names that themselves contain personal data.

## 10. Error handling

Invalid detector output **raises** instead of being skipped (a skipped entity is
PII that would reach the LLM). Raised as `InvalidEntityError`:

negative start/end, `start > end`, empty span, `end > len(text)`, entity from a
different file or block, `value != text[start:end]`, confidence that is not a
finite number in `[0, 1]` (booleans rejected), malformed `pii_type`, wrong field
types, objects that are not `Entity`. Entities pointing at a block that was not
supplied to `redact_document` also raise. Duplicate `(file, index)` blocks raise
`InvalidBlockError`. Validation runs before any placeholder is assigned, so a
failed call does not change the manager.

Messages contain only `file`, `block_index`, `start`, `end`, `pii_type` and a
reason, for example:
`Invalid entity: Entity span does not match the supplied text. (file='demo.pdf', block_index=0, start=8, end=19, pii_type=PERSON)`

## 11. Security considerations

* `Entity.value` is never printed, logged, written to a file, put in an
  exception or in a report. The module has no `logging`, `print`, file or
  network code (checked by tests).
* Our own dataclasses (`TraceRecord`, `MergedSpan`, `ValidationResult`) hold no
  raw values, so their `repr` is safe.
* Caution: the shared `Entity` dataclass's default `repr()` **does** include
  `value`. Never print or log `Entity` objects anywhere in the pipeline; use
  `entity.public_info()`.
* Redaction only covers what detection found. Undetected PII is not removed.
* A literal `[PERSON_1]` already present in the source text is not escaped.

## 12. Running the tests

Only `pytest` is needed (not added to `requirements.txt`). From the repository
root, with `src` on the path:

```bash
pip install pytest
PYTHONPATH=src python -m pytest src/pii_pipeline/redaction/tests -v
```

Tests use only synthetic data (fake names, `*.example.test` emails).

## 13. Example (fake data)

```python
from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.redaction import redact_document, report_to_json

block = TextBlock(file="demo.pdf", location="page 1", index=0,
                  text="Contact Alex Morgan at alex@example.test")
entities = [
    Entity("demo.pdf", 0, 8, 19, "PERSON", 0.93, "ner", "Alex Morgan"),
    Entity("demo.pdf", 0, 23, 40, "EMAIL", 0.99, "regex", "alex@example.test"),
]
redacted, records = redact_document([block], entities)

redacted[0]
# RedactedBlock(file='demo.pdf', block_index=0, location='page 1',
#               text='Contact [PERSON_1] at [EMAIL_1]')
records[1].to_dict()
# {'file': 'demo.pdf', 'block_index': 0, 'location': 'page 1', 'start': 23,
#  'end': 40, 'pii_type': 'EMAIL', 'confidence': 0.99, 'detector': 'regex',
#  'placeholder': '[EMAIL_1]', 'merged_entities': 1}
print(report_to_json(records))   # findings + counts by type and file
```

## 14. Files

| File | Purpose |
| --- | --- |
| `redactor.py` | `redact_block`, `redact_document`, overlap resolution, text rebuilding |
| `placeholder_manager.py` | per-file, per-type placeholder numbering |
| `traceability.py` | `TraceRecord`, `build_report`, `report_to_json` |
| `validators.py` | entity/block validation, exceptions, `verify_redaction` |
| `tests/` | pytest suite (`helpers.py` builds synthetic blocks/entities) |

## 15. Future improvements

* Optional normalized matching (case/whitespace) via `_normalize`, behind a flag.
* Option to also redact undetected repeats of a detected value elsewhere in a file.
* Optional "skip and report" mode for invalid entities instead of raising.
* Placeholder escaping if source text may contain `[TYPE_n]` lookalikes.
* Integrate with the evaluation module (e.g. residual-PII leakage scoring).
