from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBlock:
    """One chunk of text pulled out of a file (produced by extraction)."""
    file: str                  # source file name, e.g. "policy.pdf"
    location: str              # e.g. "page 3" or "slide 8"
    index: int                 # position in reading order: 0, 1, 2...
    text: str                  # the text itself
    ocr_confidence: float | None = None   # None if the text wasn't scanned


@dataclass
class Entity:
    """One piece of PII that was found (produced by detection)."""
    file: str
    block_index: int           # the `index` of the TextBlock it was found in
    # start and end count characters from the start of THAT block's text.
    # start is included, end is not (same as Python slicing: text[start:end]).
    # They refer to the ORIGINAL text, not the redacted text.
    start: int
    end: int
    pii_type: str              # e.g. "EMAIL", "PERSON", "PHONE"
    confidence: float          # 0.0 to 1.0
    detector: str              # which method found it, e.g. "regex", "spacy"
    value: str = field(repr=False)   # the actual PII text. SECRET: never show or log it
    placeholder: str | None = None   # filled in by redaction, e.g. "[EMAIL_2]"

    def public_info(self) -> dict:
        """Safe to show on screen or in a report: everything except `value`."""
        return {
            "file": self.file,
            "block_index": self.block_index,
            "start": self.start,
            "end": self.end,
            "pii_type": self.pii_type,
            "confidence": self.confidence,
            "detector": self.detector,
            "placeholder": self.placeholder,
        }


@dataclass
class RedactedBlock:
    """A block of text with PII replaced by placeholders (produced by redaction)."""
    file: str
    block_index: int
    location: str
    text: str                  # e.g. "Contact [PERSON_1] at [EMAIL_1]"