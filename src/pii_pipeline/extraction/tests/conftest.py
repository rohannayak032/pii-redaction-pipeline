"""Shared fixtures. Every file is synthetic and built at test time in a temp dir."""

from __future__ import annotations

import pytest

from pii_pipeline.extraction import extract_document_detailed
from pii_pipeline.extraction.ocr import ocr_available

from .fixtures import docx_builder, pdf_builder, pptx_builder

requires_ocr = pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")


@pytest.fixture(scope="session")
def files(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    return {
        "docx": docx_builder.build_docx(root / "synthetic.docx"),
        "pptx": pptx_builder.build_pptx(root / "synthetic.pptx"),
        "pdf_digital": pdf_builder.build_digital(root / "digital.pdf"),
        "pdf_mixed": pdf_builder.build_mixed(root / "mixed.pdf"),
        "pdf_rotated": pdf_builder.build_rotated_and_skewed(root / "rotated.pdf"),
        "pdf_blank": pdf_builder.build_blank(root / "blank.pdf"),
        "pdf_encrypted": pdf_builder.build_encrypted(root / "encrypted.pdf"),
    }


@pytest.fixture(scope="session")
def extracted(files):
    """Lazily extract each file once per session."""
    cache = {}

    def get(name):
        if name not in cache:
            cache[name] = extract_document_detailed(files[name])
        return cache[name]

    return get


def find(result, value: str):
    """Blocks whose text contains ``value``."""
    return [b for b in result.blocks if value in b.text]


def assert_found(result, value: str, location: str | None = None):
    """``value`` is in some block; if ``location`` is given, in one at that location."""
    hits = find(result, value)
    assert hits, f"{value!r} not extracted"
    if location is not None:
        assert any(location in b.location for b in hits), (value, [b.location for b in hits])
    return hits


def check_invariants(result):
    """The TextBlock contract and metadata spans hold for every block."""
    assert len(result.blocks) == len(result.meta)
    for i, (block, meta) in enumerate(zip(result.blocks, result.meta)):
        assert block.index == meta.index == i
        assert block.file == result.file
        assert block.text and block.text == block.text.strip()
        assert block.location
        if block.ocr_confidence is not None:
            assert 0.0 <= block.ocr_confidence <= 1.0
        for _, start, end in meta.cells:
            assert 0 <= start < end <= len(block.text)
            assert block.text[start:end].strip() == block.text[start:end]
        for start, end, bbox, conf in meta.words:
            assert 0 <= start < end <= len(block.text)
            assert " " not in block.text[start:end].strip() or meta.source != "ocr"
            assert len(bbox) == 4
            assert conf is None or 0.0 <= conf <= 1.0
