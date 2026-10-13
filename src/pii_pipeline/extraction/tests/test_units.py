"""Unit tests for the shared building blocks (no files, no OCR)."""

import pytest

from pii_pipeline.extraction.base import BlockMeta, Piece, RawBlock
from pii_pipeline.extraction.deduplication import final_pass, iou
from pii_pipeline.extraction.normalize import clean
from pii_pipeline.extraction.ordering import xy_cut
from pii_pipeline.extraction.pipeline import render
from pii_pipeline.extraction.tables import Cell, choose_header_rows, table_blocks
from pii_pipeline.extraction.validation import check_contract
from pii_pipeline.extraction.base import ExtractionError
from pii_pipeline.schemas import TextBlock


# ---------------------------------------------------------------- normalize
@pytest.mark.parametrize("raw, expected", [
    ("ava​.stone@example.test", "ava.stone@example.test"),   # zero-width space
    ("900‑12‑3456", "900-12-3456"),                       # non-breaking hyphens
    ("Ava Stone", "Ava Stone"),                                 # NBSP
    ("ﬁnance", "finance"),                                     # ligature
    ("ｊｏｅ＠ｅｘａｍｐｌｅ．ｔｅｓｔ", "joe@example.test"),           # fullwidth
    ("  a\n\tb  ", "a b"),
    ("co­operate", "cooperate"),                               # soft hyphen
    ("ava‎@example.test", "ava@example.test"),            # left-to-right mark
    ("ava⁣@example.test", "ava@example.test"),            # invisible separator
    ("900-12‬-3456", "900-12-3456"),                      # pop directional formatting
    ("900️-12-3456", "900-12-3456"),                      # variation selector
])
def test_clean(raw, expected):
    assert clean(raw) == expected


def test_clean_keeps_superscript_markers_separate():
    # NFKC would turn "¹" into "1" and corrupt the SSN; we must not.
    assert clean("900-12-3456¹") == "900-12-3456¹"


# ---------------------------------------------------------------- ordering
def test_two_columns_read_column_by_column():
    boxes = [(300, 100, 500, 140), (0, 100, 200, 140), (0, 160, 200, 300), (300, 160, 500, 200), (0, 0, 500, 40)]
    order = xy_cut(boxes)
    assert order == [4, 1, 2, 0, 3]   # title, left column, right column


def test_label_value_form_reads_row_by_row():
    boxes = [(0, 0, 80, 20), (200, 0, 400, 20), (0, 30, 80, 50), (200, 30, 400, 50)]
    assert xy_cut(boxes) == [0, 1, 2, 3]


def test_ordering_is_deterministic_for_identical_boxes():
    boxes = [(0, 0, 10, 10)] * 3
    assert xy_cut(boxes) == [0, 1, 2]


# ---------------------------------------------------------------- tables
def _row(*values):
    return [Cell(col=c, text=v) for c, v in enumerate(values)]


def test_header_detection():
    assert choose_header_rows([_row("Name", "Email"), _row("A B", "a@x.test")]) == 1
    assert choose_header_rows([_row("EMP-1", "a@x.test"), _row("EMP-2", "b@x.test")]) == 0
    assert choose_header_rows([_row("Name", "Email")]) == 0                     # single row = data
    assert choose_header_rows([_row("a@x.test", "Bob"), _row("1", "2")], flagged=1) == 0


def test_row_blocks_with_labels_and_exact_cell_spans():
    rows = [_row("Employee ID", "Name", "Email"), _row("EMP-00001", "", "a@x.test")]
    header, block = table_blocks(rows, location="table 1", table_id=1)
    assert render(header.pieces)[0] == "Name" and header.location == "table 1, header"   # column with no data
    text, cells, _ = render(block.pieces)
    assert text == "Employee ID: EMP-00001 | Email: a@x.test"
    assert [text[s:e] for _, s, e in cells] == ["EMP-00001", "a@x.test"]
    assert block.location == "table 1, row 2"


# ---------------------------------------------------------------- render
def test_render_drops_dangling_separators_and_tracks_words():
    pieces = [Piece("  "), Piece(" | ", kind="sep"), Piece("Ava", bbox=(0, 0, 1, 1), conf=0.9),
              Piece(" ", kind="sep"), Piece("Stone​", bbox=(1, 0, 2, 1), conf=0.8), Piece(" | ", kind="sep")]
    text, _, words = render(pieces)
    assert text == "Ava Stone"
    assert [text[s:e] for s, e, _, _ in words] == ["Ava", "Stone"]


# ---------------------------------------------------------------- dedup
def test_dedup_is_by_place_not_by_text():
    a = RawBlock.simple("paragraph", "page 1, paragraph 1", "Ava Stone", page=1, bbox=(0, 0, 10, 10), bbox_unit="pt")
    same_place = RawBlock.simple("ocr_paragraph", "page 1, image 1", "Ava Stone", page=1, bbox=(0, 0, 10, 11), bbox_unit="pt")
    elsewhere = RawBlock.simple("paragraph", "page 2, paragraph 1", "Ava Stone", page=2, bbox=(0, 0, 10, 10), bbox_unit="pt")
    assert final_pass([a, same_place, elsewhere], ["Ava Stone"] * 3) == [0, 2]
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


# ---------------------------------------------------------------- contract
def test_contract_violations_raise():
    good = TextBlock("f.pdf", "page 1", 0, "text")
    check_contract([good], [BlockMeta(index=0, kind="paragraph", source="native")])
    with pytest.raises(ExtractionError):
        check_contract([TextBlock("f.pdf", "page 1", 1, "text")], [BlockMeta(index=1, kind="p", source="native")])
    with pytest.raises(ExtractionError):
        check_contract([TextBlock("f.pdf", "page 1", 0, "text", 1.5)], [BlockMeta(index=0, kind="p", source="ocr")])
    with pytest.raises(ExtractionError):
        check_contract([good], [BlockMeta(index=0, kind="p", source="native", cells=((0, 2, 99),))])


def test_flagged_header_over_empty_rows_is_not_lost():
    rows = [_row("Jane Roe", "SSN 900-12-3456"), _row("", "")]
    [block] = table_blocks(rows, location="table 1", table_id=1, flagged_header_rows=1)
    assert render(block.pieces)[0] == "Jane Roe | SSN 900-12-3456"
