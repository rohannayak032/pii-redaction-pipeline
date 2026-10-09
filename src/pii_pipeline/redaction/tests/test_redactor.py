import copy

import pytest

from pii_pipeline.redaction import (
    InvalidBlockError,
    InvalidEntityError,
    PlaceholderManager,
    redact_block,
    redact_document,
)
from pii_pipeline.schemas import RedactedBlock

from .helpers import make_block, make_entity, span_entity


def test_no_entities_returns_text_unchanged():
    block = make_block("Nothing sensitive here.")
    redacted, records = redact_block(block, [])
    assert redacted.text == "Nothing sensitive here."
    assert records == []


def test_empty_text_and_empty_entity_list():
    redacted, records = redact_block(make_block(""), [])
    assert redacted.text == ""
    assert records == []


def test_output_is_a_redacted_block_with_block_metadata():
    block = make_block("Hi Alex Morgan", file="a.pdf", index=4, location="page 5")
    redacted, _ = redact_block(block, [make_entity(block, "Alex Morgan")])
    assert isinstance(redacted, RedactedBlock)
    assert (redacted.file, redacted.block_index, redacted.location) == ("a.pdf", 4, "page 5")


def test_one_entity():
    block = make_block("Hi Alex Morgan, welcome.")
    redacted, _ = redact_block(block, [make_entity(block, "Alex Morgan")])
    assert redacted.text == "Hi [PERSON_1], welcome."


def test_multiple_entities_and_types():
    block = make_block("Contact John Smith at john@example.test")
    entities = [
        make_entity(block, "John Smith", "PERSON"),
        make_entity(block, "john@example.test", "EMAIL"),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "Contact [PERSON_1] at [EMAIL_1]"


def test_multiple_pii_types_with_phone():
    block = make_block("Alex Morgan, alex@example.test, 555-0100")
    entities = [
        make_entity(block, "Alex Morgan", "PERSON"),
        make_entity(block, "alex@example.test", "EMAIL"),
        make_entity(block, "555-0100", "PHONE"),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "[PERSON_1], [EMAIL_1], [PHONE_1]"


def test_offsets_refer_to_original_text_when_placeholders_change_length():
    block = make_block("AAA John BBB email@example.test CCC")
    entities = [
        make_entity(block, "John", "PERSON"),
        make_entity(block, "email@example.test", "EMAIL"),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "AAA [PERSON_1] BBB [EMAIL_1] CCC"


def test_short_values_become_longer_placeholders():
    block = make_block("Al and Bo")
    entities = [make_entity(block, "Al"), make_entity(block, "Bo")]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "[PERSON_1] and [PERSON_2]"


def test_repeated_identical_value_reuses_placeholder():
    block = make_block("John Smith met John Smith yesterday.")
    entities = [make_entity(block, "John Smith"), make_entity(block, "John Smith", occurrence=1)]
    redacted, records = redact_block(block, entities)
    assert redacted.text == "[PERSON_1] met [PERSON_1] yesterday."
    assert len(records) == 2


def test_multiple_occurrences_in_one_block():
    block = make_block("x@example.test, y@example.test, x@example.test")
    entities = [
        make_entity(block, "x@example.test", "EMAIL"),
        make_entity(block, "y@example.test", "EMAIL"),
        make_entity(block, "x@example.test", "EMAIL", occurrence=1),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "[EMAIL_1], [EMAIL_2], [EMAIL_1]"


def test_pii_at_beginning_and_end():
    block = make_block("Alex Morgan wrote to alex@example.test")
    entities = [make_entity(block, "Alex Morgan"), make_entity(block, "alex@example.test", "EMAIL")]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "[PERSON_1] wrote to [EMAIL_1]"


def test_entity_covering_entire_text():
    block = make_block("Alex Morgan")
    redacted, _ = redact_block(block, [span_entity(block, 0, 11)])
    assert redacted.text == "[PERSON_1]"


def test_punctuation_adjacent_to_pii():
    block = make_block("(Alex Morgan), alex@example.test.")
    entities = [make_entity(block, "Alex Morgan"), make_entity(block, "alex@example.test", "EMAIL")]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "([PERSON_1]), [EMAIL_1]."


def test_touching_entities_are_both_redacted():
    block = make_block("AliceBob")
    entities = [span_entity(block, 0, 5), span_entity(block, 5, 8)]
    redacted, records = redact_block(block, entities)
    assert redacted.text == "[PERSON_1][PERSON_2]"
    assert len(records) == 2


def test_unicode_text():
    block = make_block("Привет, Zoë Müller! 你好 José Núñez 😀 zoe@example.test")
    entities = [
        make_entity(block, "Zoë Müller"),
        make_entity(block, "José Núñez"),
        make_entity(block, "zoe@example.test", "EMAIL"),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "Привет, [PERSON_1]! 你好 [PERSON_2] 😀 [EMAIL_1]"


def test_inputs_are_not_mutated():
    block = make_block("Contact John Smith at john@example.test")
    entities = [make_entity(block, "John Smith"), make_entity(block, "john@example.test", "EMAIL")]
    block_copy, entities_copy = copy.deepcopy(block), copy.deepcopy(entities)
    redact_block(block, entities)
    assert block == block_copy
    assert entities == entities_copy


def test_results_are_deterministic_and_independent_of_entity_order():
    block = make_block("Contact John Smith at john@example.test or Jane Doe")
    entities = [
        make_entity(block, "John Smith"),
        make_entity(block, "john@example.test", "EMAIL"),
        make_entity(block, "Jane Doe"),
    ]
    first = redact_block(block, entities)
    second = redact_block(block, entities)
    reversed_ = redact_block(block, list(reversed(entities)))
    assert first == second
    assert first == reversed_
    assert first[0].text == "Contact [PERSON_1] at [EMAIL_1] or [PERSON_2]"


def test_document_same_value_across_blocks_keeps_placeholder():
    b0 = make_block("John Smith is an employee.", index=0, location="page 1")
    b1 = make_block("Contact John Smith at john@example.test.", index=1, location="page 2")
    entities = [
        make_entity(b0, "John Smith"),
        make_entity(b1, "John Smith"),
        make_entity(b1, "john@example.test", "EMAIL"),
    ]
    redacted, records = redact_document([b0, b1], entities)
    assert [r.text for r in redacted] == [
        "[PERSON_1] is an employee.",
        "Contact [PERSON_1] at [EMAIL_1].",
    ]
    assert [(r.file, r.block_index, r.location) for r in redacted] == [
        ("doc.pdf", 0, "page 1"),
        ("doc.pdf", 1, "page 2"),
    ]
    assert [r.block_index for r in records] == [0, 1, 1]


def test_document_placeholders_are_scoped_per_file():
    a = make_block("Alice met Alice.", file="file_a.pdf")
    b = make_block("Bob met Alice.", file="file_b.pdf")
    entities = [
        make_entity(a, "Alice"),
        make_entity(a, "Alice", occurrence=1),
        make_entity(b, "Bob"),
        make_entity(b, "Alice"),
    ]
    redacted, _ = redact_document([a, b], entities)
    assert redacted[0].text == "[PERSON_1] met [PERSON_1]."
    assert redacted[1].text == "[PERSON_1] met [PERSON_2]."


def test_document_output_follows_block_order_and_handles_blocks_without_entities():
    b0 = make_block("plain", index=0)
    b1 = make_block("Hi Alex Morgan", index=1)
    redacted, _ = redact_document([b0, b1], [make_entity(b1, "Alex Morgan")])
    assert [r.text for r in redacted] == ["plain", "Hi [PERSON_1]"]


def test_document_entity_for_unknown_block_raises():
    block = make_block("Alex Morgan", index=0)
    stray = make_block("Alex Morgan", index=7)
    with pytest.raises(InvalidEntityError):
        redact_document([block], [make_entity(stray, "Alex Morgan")])


def test_document_duplicate_block_raises():
    block = make_block("text")
    with pytest.raises(InvalidBlockError):
        redact_document([block, make_block("other")], [])


def test_document_with_no_blocks():
    assert redact_document([], []) == ([], [])


def test_redact_document_accepts_external_manager_for_batches():
    manager = PlaceholderManager()
    b0 = make_block("Alex Morgan", index=0)
    b1 = make_block("Alex Morgan", index=1)
    first, _ = redact_document([b0], [make_entity(b0, "Alex Morgan")], manager)
    second, _ = redact_document([b1], [make_entity(b1, "Alex Morgan")], manager)
    assert first[0].text == second[0].text == "[PERSON_1]"
