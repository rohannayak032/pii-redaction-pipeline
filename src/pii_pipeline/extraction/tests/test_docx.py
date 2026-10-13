from pii_pipeline.extraction import extract_document_detailed

from .conftest import assert_found, check_invariants, find, requires_ocr
from .fixtures import fake as f


def test_invariants(extracted):
    check_invariants(extracted("docx"))


def test_body_paragraphs_headings_lists_and_tracked_changes(extracted):
    r = extracted("docx")
    assert_found(r, f.PERSON_HEADING, "paragraph 1 (Heading 1)")
    [block] = assert_found(r, f.EMAIL_BODY, "paragraph 2")
    assert f.SSN in block.text and f.PHONE in block.text      # w:ins text included
    assert "removed words" not in " ".join(b.text for b in r.blocks)  # w:del excluded
    assert_found(r, f.PERSON_LIST, "(list item)")


def test_hidden_link_target(extracted):
    assert_found(extracted("docx"), f.EMAIL_HIDDEN_LINK, "link 1")


def test_table_rows_keep_header_context_and_merges(extracted):
    r = extracted("docx")
    [row] = assert_found(r, f.EMP_1, "table 1, row 2")
    assert row.text == f"Employee ID: {f.EMP_1} | Name: {f.PERSON_BODY} | Department: Finance"
    [row2] = [b for b in assert_found(r, f.EMP_2) if b.location == "table 1, row 3"]
    assert "Finance" not in row2.text                        # vertical merge counted once
    assert_found(r, f.PERSON_MERGED, "table 1, row 4")       # horizontal merge
    [nested] = assert_found(r, f.PERSON_NESTED, "table 1, row 3, nested table 1, row 2")
    assert nested.text == f"Backup: {f.PERSON_NESTED} | Phone: {f.PHONE}"
    assert not any(b.text.startswith("Employee ID | Name") for b in r.blocks)  # header not emitted alone


def test_cell_spans_point_at_values(extracted):
    r = extracted("docx")
    [row] = find(r, f.EMP_1)
    meta = r.meta[row.index]
    assert meta.kind == "table_row" and meta.row_index == 2
    assert [row.text[s:e] for _, s, e in meta.cells] == [f.EMP_1, f.PERSON_BODY, "Finance"]


def test_text_box_once_despite_fallback_copy(extracted):
    r = extracted("docx")
    hits = assert_found(r, f.PERSON_TEXTBOX, "text box 1")
    assert len(hits) == 1


@requires_ocr
def test_image_text_and_alt_text(extracted):
    r = extracted("docx")
    [block] = assert_found(r, f.PERSON_IMAGE, "image 1")
    assert r.meta[block.index].source == "ocr" and block.ocr_confidence > 0.6
    assert_found(r, f.PERSON_ALT, "alt text")
    assert any(w.code == "SKIPPED_IMAGE" for w in r.warnings)    # the 20x20 image


def test_headers_footers_per_section_without_duplicates(extracted):
    r = extracted("docx")
    assert_found(r, f.PERSON_HEADER_S1, ", header")
    assert_found(r, f.PERSON_HEADER_S2, ", header")
    assert_found(r, f.PERSON_FIRST_PAGE, "header (first page)")
    assert_found(r, f.PERSON_FOOTER, ", footer")
    for person in (f.PERSON_HEADER_S1, f.PERSON_HEADER_S2, f.PERSON_FOOTER):
        assert len(find(r, person)) == 1                        # linked sections not repeated


def test_notes_and_comments(extracted):
    r = extracted("docx")
    assert_found(r, f.PERSON_FOOTNOTE, "footnote 1")
    assert_found(r, f.PERSON_ENDNOTE, "endnote 1")
    [comment] = assert_found(r, f.PERSON_COMMENT_BODY, "comment 1")
    assert comment.text == f"Comment by {f.PERSON_COMMENT_AUTHOR}: Ask {f.PERSON_COMMENT_BODY}"


def test_sweep_finds_orphan_text(extracted):
    r = extracted("docx")
    assert_found(r, f.PERSON_ORPHAN, "other text (word/header99.xml)")
    assert any(w.code == "UNCLAIMED_TEXT" for w in r.warnings)


def test_metadata_is_last_and_separate(extracted):
    r = extracted("docx")
    last = r.blocks[-1]
    assert last.location == "document properties"
    for value in (f.PERSON_AUTHOR, f.PERSON_LAST_MODIFIED, f.COMPANY):
        assert value in last.text


def test_reading_order(extracted):
    r = extracted("docx")
    order = [b.location for b in r.blocks]
    assert order.index(find(r, f.PERSON_HEADING)[0].location) < order.index(find(r, f.EMP_1)[0].location)
    assert order.index(find(r, f.EMP_1)[0].location) < order.index(find(r, f.PERSON_TEXTBOX)[0].location)


def test_deterministic(files, extracted):
    again = extract_document_detailed(files["docx"])
    assert [(b.location, b.text) for b in again.blocks] == [(b.location, b.text) for b in extracted("docx").blocks]
