"""Extraction module of the PII Redaction Pipeline.

Typical use::

    from pii_pipeline.extraction import extract_document

    blocks = extract_document("policy.pdf")          # list[TextBlock]

    result = extract_document_detailed("deck.pptx")  # blocks + positions + warnings
    for block, meta in zip(result.blocks, result.meta):
        ...

Everything runs locally. No document text is ever printed, logged, or put in
an exception or warning.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from pii_pipeline.schemas import TextBlock

from . import dispatcher, pipeline, validation
from .base import (
    BlockMeta,
    Context,
    ExtractionError,
    ExtractionResult,
    ExtractionWarning,
    ExtractionWarningCategory,
    OCRUnavailableError,
    UnsupportedFileError,
)

__all__ = [
    "BlockMeta",
    "ExtractionError",
    "ExtractionResult",
    "ExtractionWarning",
    "ExtractionWarningCategory",
    "OCRUnavailableError",
    "UnsupportedFileError",
    "extract_document",
    "extract_document_detailed",
]


def _extractor(fmt: str):
    # Imported lazily so that e.g. DOCX-only use does not load PyMuPDF.
    if fmt == "pdf":
        from .pdf_extract import extract_pdf
        return extract_pdf
    if fmt == "docx":
        from .docx_extract import extract_docx
        return extract_docx
    from .pptx_extract import extract_pptx
    return extract_pptx


def extract_document_detailed(path: str | os.PathLike) -> ExtractionResult:
    """Extract one file into ordered TextBlocks plus metadata and warnings.

    Raises ``UnsupportedFileError`` for unsupported, legacy or encrypted files,
    ``OCRUnavailableError`` if OCR is needed but Tesseract is missing, and
    ``ExtractionError`` for damaged files. Messages never contain document text.
    """
    path = Path(path)
    ctx = Context(file=path.name)
    fmt = dispatcher.detect_format(path, ctx)
    if fmt is None:
        ctx.warn(validation.EMPTY_FILE, "document", "the file is empty")
        return ExtractionResult(path.name, (), (), tuple(ctx.warnings))

    try:
        raw_blocks = _extractor(fmt)(path, ctx)
    except ExtractionError:
        raise
    except Exception as exc:  # library errors may quote content: never chain them
        if os.environ.get("PII_EXTRACTION_DEBUG") == "1":   # local debugging only
            raise
        raise ExtractionError(
            f"Could not extract {path.name!r} ({fmt.upper()}): {type(exc).__name__}. "
            "The file may be damaged."
        ) from None

    blocks, meta = pipeline.assemble(path.name, raw_blocks, ctx)
    validation.check_contract(blocks, meta)
    validation.report_skipped_images(ctx)
    validation.check_not_empty(ctx, blocks, path.stat().st_size)
    return ExtractionResult(path.name, tuple(blocks), tuple(meta), tuple(ctx.warnings))


def extract_document(path: str | os.PathLike) -> list[TextBlock]:
    """Extract one file into TextBlocks in reading order.

    Suspicious results (nothing extracted, low OCR confidence, skipped images,
    text found outside known structures, ...) are reported through
    ``warnings.warn`` with category ``ExtractionWarningCategory``; use
    :func:`extract_document_detailed` to get them as data.
    """
    result = extract_document_detailed(path)
    for warning in result.warnings:
        warnings.warn(str(warning), ExtractionWarningCategory, stacklevel=2)
    return list(result.blocks)
