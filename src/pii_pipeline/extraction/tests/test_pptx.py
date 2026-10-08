from pii_pipeline.extraction import extract_document_detailed

from .conftest import assert_found, check_invariants, find, requires_ocr
from .fixtures import fake as f
from .fixtures import pptx_builder as p


def test_invariants(extracted):
    check_invariants(extracted("pptx"))


def test_title_first_then_groups_in_visual_order(extracted):
    r = extracted("pptx")
    slide1 = [b for b in r.blocks if b.location.startswith("slide 1,")]
    assert slide1[0].location == "slide 1, title" and f.PERSON_HEADING in slide1[0].text
    texts = [b.text for b in slide1]
    left = next(i for i, t in enumerate(texts) if p.PERSON_GROUP_LEFT in t)
    right = next(i for i, t in enumerate(texts) if p.PERSON_GROUP_RIGHT in t)
    nested = next(i for i, t in enumerate(texts) if p.PERSON_NESTED_GROUP in t)
    assert left < right < nested          # added right-first, read left-first


def test_footer_notes_and_comments(extracted):
    r = extracted("pptx")
    assert_found(r, p.PERSON_FOOTER, "slide 1, footer")
    [notes] = assert_found(r, p.PERSON_NOTES, "slide 1, speaker notes")
    assert f.SSN in notes.text
    [legacy] = assert_found(r, p.PERSON_LEGACY_COMMENT, "slide 1, comment 1")
    assert legacy.text.startswith(f"Comment by {p.PERSON_LEGACY_AUTHOR}: ")
    [modern] = assert_found(r, p.PERSON_MODERN_COMMENT, "slide 2, comment 1")
    assert modern.text.startswith(f"Comment by {p.PERSON_MODERN_AUTHOR}: ")


def test_table_rows_with_header(extracted):
    r = extracted("pptx")
    [row] = assert_found(r, p.PERSON_TABLE, "slide 2, table 1, row 2")
    assert row.text == f"Employee ID: {f.EMP_1} | Name: {p.PERSON_TABLE} | Email: {f.EMAIL_BODY}"
    assert_found(r, f.PERSON_MERGED, "slide 2, table 1, row 3")


@requires_ocr
def test_picture_ocr_and_alt_text(extracted):
    r = extracted("pptx")
    [block] = assert_found(r, f.PERSON_IMAGE, "slide 2, image 1")
    assert r.meta[block.index].source == "ocr" and r.meta[block.index].page == 2
    assert_found(r, f.PERSON_ALT, "alt text")


def test_chart_labels(extracted):
    assert_found(extracted("pptx"), p.PERSON_CHART, "slide 2, chart 1")


def test_hidden_slide_is_extracted_and_flagged(extracted):
    r = extracted("pptx")
    [block] = assert_found(r, p.PERSON_HIDDEN, "slide 3 (hidden)")
    assert r.meta[block.index].hidden


def test_master_text_and_sweep(extracted):
    r = extracted("pptx")
    assert_found(r, p.PERSON_MASTER, "slide master 1")
    assert_found(r, p.PERSON_UNCLAIMED, "other text (ppt/slides/slide3.xml)")
    assert not find(r, "Click to edit")              # template prompts are not content


def test_metadata(extracted):
    last = extracted("pptx").blocks[-1]
    assert last.location == "document properties" and f.PERSON_AUTHOR in last.text


def test_no_false_embedded_object_warning_for_charts(extracted):
    assert not any(w.code == "UNSUPPORTED_OBJECT" for w in extracted("pptx").warnings)


def test_deterministic(files, extracted):
    again = extract_document_detailed(files["pptx"])
    assert [(b.location, b.text) for b in again.blocks] == [(b.location, b.text) for b in extracted("pptx").blocks]
