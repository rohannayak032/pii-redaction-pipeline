from pii_pipeline.redaction import redact_block, resolve_overlaps

from .helpers import make_block, span_entity


def test_contained_lower_confidence_entity_is_absorbed():
    block = make_block("John Smith")
    a = span_entity(block, 0, 10, "PERSON", 0.97)
    b = span_entity(block, 5, 10, "PERSON", 0.82)
    redacted, records = redact_block(block, [a, b])
    assert redacted.text == "[PERSON_1]"
    assert len(records) == 1
    assert records[0].confidence == 0.97
    assert records[0].merged_entities == 2


def test_higher_confidence_wins_the_label():
    block = make_block("Alex Morgan Street")
    long_low = span_entity(block, 0, 18, "ADDRESS", 0.60)
    short_high = span_entity(block, 0, 11, "PERSON", 0.95)
    redacted, records = redact_block(block, [long_low, short_high])
    assert redacted.text == "[PERSON_1]"
    assert (records[0].start, records[0].end) == (0, 18)
    assert records[0].pii_type == "PERSON"


def test_equal_confidence_prefers_longer_span():
    block = make_block("John Smith")
    short = span_entity(block, 0, 4, "ORGANIZATION", 0.9)
    long = span_entity(block, 0, 10, "PERSON", 0.9)
    _, records = redact_block(block, [short, long])
    assert records[0].pii_type == "PERSON"


def test_effectively_equal_confidence_counts_as_equal():
    block = make_block("John Smith")
    short = span_entity(block, 0, 4, "ORGANIZATION", 0.9000000001)
    long = span_entity(block, 0, 10, "PERSON", 0.9)
    _, records = redact_block(block, [short, long])
    assert records[0].pii_type == "PERSON"


def test_full_tie_is_deterministic_regardless_of_input_order():
    block = make_block("John Smith")
    a = span_entity(block, 0, 10, "PERSON", 0.9, "regex")
    b = span_entity(block, 0, 10, "ADDRESS", 0.9, "ner")
    first = redact_block(block, [a, b])
    second = redact_block(block, [b, a])
    assert first == second
    assert first[1][0].pii_type == "ADDRESS"  # alphabetical tie-break


def test_partial_overlap_is_covered_by_union_so_nothing_leaks():
    block = make_block("Alex Morgan Lee")
    left = span_entity(block, 0, 11, "PERSON", 0.80)
    right = span_entity(block, 5, 15, "PERSON", 0.90)
    redacted, records = redact_block(block, [left, right])
    assert redacted.text == "[PERSON_1]"
    assert (records[0].start, records[0].end) == (0, 15)
    assert records[0].confidence == 0.90


def test_chain_of_overlaps_becomes_one_span():
    block = make_block("abcdefghijkl")
    entities = [
        span_entity(block, 0, 5),
        span_entity(block, 3, 8),
        span_entity(block, 7, 12),
    ]
    spans = resolve_overlaps(entities)
    assert [(s.start, s.end, s.merged_entities) for s in spans] == [(0, 12, 3)]


def test_touching_spans_are_not_overlapping():
    block = make_block("AliceBob")
    spans = resolve_overlaps([span_entity(block, 0, 5), span_entity(block, 5, 8)])
    assert [(s.start, s.end) for s in spans] == [(0, 5), (5, 8)]


def test_identical_duplicate_entities_produce_one_replacement():
    block = make_block("Hi Alex")
    entity = span_entity(block, 3, 7)
    redacted, records = redact_block(block, [entity, entity])
    assert redacted.text == "Hi [PERSON_1]"
    assert len(records) == 1


def test_overlap_clusters_with_same_text_share_placeholder():
    block = make_block("John Smith and John Smith")
    entities = [
        span_entity(block, 0, 10, "PERSON", 0.9),
        span_entity(block, 0, 4, "PERSON", 0.5),
        span_entity(block, 15, 25, "PERSON", 0.9),
        span_entity(block, 21, 25, "PERSON", 0.5),
    ]
    redacted, _ = redact_block(block, entities)
    assert redacted.text == "[PERSON_1] and [PERSON_1]"


def test_resolve_overlaps_output_is_sorted_by_start():
    block = make_block("aaaa bbbb cccc")
    spans = resolve_overlaps([span_entity(block, 10, 14), span_entity(block, 0, 4), span_entity(block, 5, 9)])
    assert [s.start for s in spans] == [0, 5, 10]
