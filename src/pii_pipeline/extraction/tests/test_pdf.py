import pytest

from pii_pipeline.extraction import UnsupportedFileError, extract_document_detailed

from .conftest import assert_found, check_invariants, find, requires_ocr
from .fixtures import fake as f
from .fixtures import pdf_builder as b


# ---------------------------------------------------------------- digital
def test_digital_invariants(extracted):
    check_invariants(extracted("pdf_digital"))


def test_digital_text_layer_is_used_directly(extracted):
    r = extracted("pdf_digital")
    [block] = [x for x in assert_found(r, f.EMAIL_BODY) if x.location == "page 1, paragraph 2"]
    meta = r.meta[block.index]
    assert meta.source == "native" and block.ocr_confidence is None
    assert meta.page == 1 and meta.bbox_unit == "pt" and meta.words
    assert_found(r, f.PERSON_LIST, "page 2, paragraph 1")


def test_digital_table_rows(extracted):
    r = extracted("pdf_digital")
    [row] = assert_found(r, f.EMP_1, "page 1, table 1, row 2")
    assert row.text == f"Employee ID: {f.EMP_1} | Name: {f.PERSON_BODY} | Email: {f.EMAIL_BODY}"
    assert len(find(r, f.EMP_1)) == 1      # table text is not repeated as a paragraph


@requires_ocr
def test_image_on_digital_page_is_ocrd(extracted):
    r = extracted("pdf_digital")
    [block] = assert_found(r, f.PERSON_IMAGE, "page 1, image 1")
    assert r.meta[block.index].source == "ocr" and r.meta[block.index].bbox_unit == "pt"


def test_annotations_forms_links_metadata(extracted):
    r = extracted("pdf_digital")
    [note] = assert_found(r, f.SSN, "page 1, annotation 1")
    assert note.text.startswith(f"Comment by {b.PERSON_ANNOT_AUTHOR}: ")
    assert_found(r, b.PERSON_FORM, "page 1, form field 1")
    assert_found(r, b.EMAIL_LINK, "page 1, link 1")
    assert r.blocks[-1].location == "document properties" and f.PERSON_AUTHOR in r.blocks[-1].text


# ---------------------------------------------------------------- scanned / mixed
@requires_ocr
def test_mixed_pdf_page_by_page(extracted):
    r = extracted("pdf_mixed")
    check_invariants(r)
    sources = {}
    for block, meta in zip(r.blocks, r.meta):
        sources.setdefault(meta.page, set()).add(meta.source)
    assert sources[1] == {"native"} and sources[3] == {"native"}
    assert sources[2] == {"ocr"} and sources[4] == {"ocr"}
    [scan] = assert_found(r, b.PERSON_SCAN_1, "page 2, paragraph")
    assert f.EMP_1 in " ".join(x.text for x in r.blocks if x.location.startswith("page 2"))
    assert 0.6 < scan.ocr_confidence <= 1.0


@requires_ocr
def test_scanned_ruled_table(extracted):
    r = extracted("pdf_mixed")
    [row] = assert_found(r, b.PERSON_SCAN_2, "page 4, table 1 (OCR), row 2")
    assert row.text == f"Employee ID: {f.EMP_2} | Name: {b.PERSON_SCAN_2}"
    meta = r.meta[row.index]
    assert [row.text[s:e] for _, s, e in meta.cells] == [f.EMP_2, b.PERSON_SCAN_2]
    assert meta.words and all(conf is not None for *_, conf in meta.words)


@requires_ocr
def test_rotated_and_skewed_scans(extracted):
    r = extracted("pdf_rotated")
    assert_found(r, b.PERSON_ROTATED, "page 1")
    assert_found(r, f.EMP_1, "page 1")
    assert_found(r, f.EMP_2, "page 2")
    assert "Lane" in " ".join(x.text for x in r.blocks if x.location.startswith("page 2"))


# ---------------------------------------------------------------- edge cases
@requires_ocr
def test_blank_page_warns(extracted):
    r = extracted("pdf_blank")
    assert r.blocks == ()
    codes = {w.code for w in r.warnings}
    assert {"PAGE_NO_TEXT", "NO_TEXT_EXTRACTED"} <= codes


def test_encrypted_pdf_is_refused_without_leaking(files):
    with pytest.raises(UnsupportedFileError) as info:
        extract_document_detailed(files["pdf_encrypted"])
    assert "password" in str(info.value) and f.PERSON_HEADING not in str(info.value)
