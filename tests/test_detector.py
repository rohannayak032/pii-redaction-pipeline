"""Tests for the combined PII detection pipeline."""

import pytest

# Import the data structures used by the detection pipeline.
from pii_pipeline.schemas import Entity, TextBlock

# Import the main detection function that we're testing.
from pii_pipeline.detection.detector import detect


def make_entity(pii_type, start, end, value):
    """Create a sample Entity for testing.

    This helper avoids repeating the same Entity setup
    in every test.
    """
    return Entity(
        file="a.txt",           # Name of the file containing the PII.
        block_index=0,           # Index of the TextBlock containing it.
        start=start,             # Start offset (inclusive).
        end=end,                 # End offset (exclusive).
        pii_type=pii_type,       # Classification, such as EMAIL or PERSON.
        confidence=0.95,         # Example confidence score.
        detector="test",         # Identifies this as a test-generated entity.
        value=value,             # The detected text itself.
    )


def make_block(text, index=0):
    """Create a sample TextBlock for testing.

    The index parameter lets us simulate text from
    different blocks in the same document.
    """
    return TextBlock(
        file="a.txt",                  # Source file name.
        location=f"para {index + 1}",  # Human-readable block location.
        index=index,                   # Position of this block.
        text=text,                     # Text that the detector receives.
    )


def test_exact_duplicate_entities_are_removed(monkeypatch):
    """Verify that identical detections are reduced to one result."""

    # Disable GLiNER so this test focuses only on deduplication.
    # This keeps the test independent of the ML model's predictions.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.detect_with_gliner",
        lambda blocks: [],
    )

    # Create one sample email entity.
    entity = make_entity("EMAIL", 0, 13, "alice@example.com")

    # Replace find_patterns() with a fake function that returns
    # the exact same entity twice.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.find_patterns",
        lambda block: [entity, entity],
    )

    # Run detection on one text block.
    result = detect([make_block("alice@example.com")])

    # Only one entity should remain after deduplication.
    assert len(result) == 1

    # Confirm that the remaining entity is the original object.
    assert result[0] is entity


def test_different_pii_types_at_same_span_are_preserved(monkeypatch):
    """Verify that different classifications at identical offsets survive."""

    # Disable GLiNER so only the controlled test entities are considered.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.detect_with_gliner",
        lambda blocks: [],
    )

    # Both entities refer to the same text and character positions,
    # but their PII classifications are different.
    email = make_entity("EMAIL", 0, 13, "alice@example.com")
    other = make_entity("OTHER", 0, 13, "alice@example.com")

    # Simulate a detector returning both classifications.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.find_patterns",
        lambda block: [email, other],
    )

    # Run the detection pipeline.
    result = detect([make_block("alice@example.com")])

    # Both entities should survive because their PII types differ.
    assert result == [email, other]


def test_same_email_in_different_blocks_is_preserved(monkeypatch):
    """Verify that identical text in separate blocks isn't deduplicated."""

    # Disable GLiNER to isolate the block-handling behavior.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.detect_with_gliner",
        lambda blocks: [],
    )

    # Define a fake detector that creates an email entity
    # using the metadata of whichever block it receives.
    def fake_find_patterns(block):
        return [
            Entity(
                file=block.file,           # Use the current block's file.
                block_index=block.index,   # Preserve the current block index.
                start=0,                   # Email begins at character 0.
                end=13,                    # Email ends at character 13.
                pii_type="EMAIL",          # Classification of the entity.
                confidence=0.95,           # Example confidence score.
                detector="test",           # Mark it as a test detection.
                value="alice@example.com", # Sample email value.
            )
        ]

    # Replace the real pattern detector with our controlled fake.
    monkeypatch.setattr(
        "pii_pipeline.detection.detector.find_patterns",
        fake_find_patterns,
    )

    # Create two blocks containing the same email.
    # Their block indices distinguish their locations in the document.
    blocks = [
        make_block("alice@example.com", index=0),
        make_block("alice@example.com", index=1),
    ]

    # Run detection across both blocks.
    result = detect(blocks)

    # Both entities should remain because they occur in different blocks.
    assert len(result) == 2

    # Verify that each entity retains its correct block index.
    assert [entity.block_index for entity in result] == [0, 1]


# =========================================================
# CLEANUP OF MODEL SPANS
# =========================================================

def span(block, value, pii_type="PERSON", detector="presidio"):
    """Entity for the first occurrence of `value` in `block`."""
    start = block.text.index(value)
    return Entity(block.file, block.index, start, start + len(value),
                  pii_type, 0.85, detector, value)


def run(monkeypatch, blocks, fake_patterns, fake_gliner=lambda blocks: []):
    """Run detect() with fake detectors so only the cleanup rules are tested."""
    monkeypatch.setattr("pii_pipeline.detection.detector.find_patterns", fake_patterns)
    monkeypatch.setattr("pii_pipeline.detection.detector.detect_with_gliner", fake_gliner)
    monkeypatch.setattr("pii_pipeline.detection.detector.detect_indian_addresses", lambda blocks: [])
    return detect(blocks)


def test_name_span_is_cut_where_it_runs_into_an_id(monkeypatch):
    block = make_block("Naomi K. Osadebe EMP-41077 IAM Engineer II")
    result = run(monkeypatch, [block], lambda b: [
        span(b, b.text), span(b, "EMP-41077", "EMPLOYEE_ID", "regex.employee_id")])
    assert [e.value for e in result if e.pii_type == "PERSON"] == ["Naomi K. Osadebe"]


def test_model_address_across_an_id_is_dropped(monkeypatch):
    block = make_block("Arvind K. Pillai MER-IN-4502 Chennai")
    result = run(monkeypatch, [block], lambda b: [
        span(b, b.text, "ADDRESS", "address_ner"),
        span(b, "MER-IN-4502", "VENDOR_ID", "regex.vendor_id")])
    assert [e.pii_type for e in result] == ["VENDOR_ID"]


@pytest.mark.parametrize("text, names", [
    ("D. R. Okonjo A. V. Chatterjee", ["D. R. Okonjo", "A. V. Chatterjee"]),
    ("Naomi K. Osadebe M. T. Achebe", ["Naomi K. Osadebe", "M. T. Achebe"]),
    ("C | E. Bertucci", ["E. Bertucci"]),
    ("A. Okonkwo-Bell", ["A. Okonkwo-Bell"]),
    ("KC Burney", ["KC Burney"]),
    ("R. Quintanilla Dir", ["R. Quintanilla"]),
    ("High Grazyna Wieczorek", ["Grazyna Wieczorek"]),
    ("Ananya V. Chatterjee Divisional RC 15/08/2026", ["Ananya V. Chatterjee"]),
    ("PRIYA NAIR", ["PRIYA NAIR"]),
    ("Siddharth Gaikwad, Srinivas Teppa", ["Siddharth Gaikwad", "Srinivas Teppa"]),
    ("Setup CD_Onboarding - Workflow - Siddharth Gaikwad", ["Siddharth Gaikwad"]),
    ("Chris Ott Melisa Cardozo DK Koran Erik Hansen",
     ["Chris Ott", "Melisa Cardozo", "DK Koran", "Erik Hansen"]),
    ("Lars Erik Brannstrom", ["Lars Erik Brannstrom"]),
    ("MEASURE TARGET MEASURE OWNER", []),
    ("Business Owner", []),
    ("Contains Any Response", []),
    ("The General Counsel", []),
    ("CHIEF RISK OFFICER", []),
    ("internal user", []),
    ("WR", []),
])
def test_name_spans_are_split_trimmed_or_dropped(monkeypatch, text, names):
    block = make_block(text)
    result = run(monkeypatch, [block], lambda b: [span(b, b.text)])
    assert [e.value for e in result] == names


def test_finer_name_split_wins(monkeypatch):
    block = make_block("USERS: KC Burney Jyoti Karwal")
    result = run(monkeypatch, [block], lambda b: [span(b, "Burney Jyoti Karwal")],
                 lambda blocks: [span(blocks[0], "KC Burney", detector="gliner"),
                                 span(blocks[0], "Jyoti Karwal", detector="gliner")])
    assert sorted(e.value for e in result) == ["Jyoti Karwal", "KC Burney"]


def test_model_address_holding_a_date_is_dropped(monkeypatch):
    block = make_block("Gap raised 15/08/2026 applied, Mumbai")
    result = run(monkeypatch, [block],
                 lambda b: [span(b, "15/08/2026 applied, Mumbai", "ADDRESS", "address_ner")])
    assert result == []


def test_names_in_unreliable_ocr_are_ignored(monkeypatch):
    block = TextBlock("a.txt", "image 1 (OCR)", 0, "Pee Leder Fobesligy", ocr_confidence=0.45)
    assert run(monkeypatch, [block], lambda b: [span(b, b.text)]) == []


def test_one_word_name_needs_two_detectors(monkeypatch):
    block = make_block("Ask Priya today")
    alone = run(monkeypatch, [block], lambda b: [span(b, "Priya")])
    both = run(monkeypatch, [block], lambda b: [span(b, "Priya")],
               lambda blocks: [span(blocks[0], "Priya", detector="gliner")])
    assert alone == [] and [e.value for e in both] == ["Priya"]


def test_repeats_of_a_found_name_are_redacted(monkeypatch):
    blocks = [make_block("Owner: Tobias Lindqvist", 0), make_block("Ask Tobias Lindqvist.", 1)]
    result = run(monkeypatch, blocks,
                 lambda b: [span(b, "Tobias Lindqvist")] if b.index == 0 else [])
    assert [(e.block_index, e.value, e.detector) for e in result] == [
        (0, "Tobias Lindqvist", "presidio"), (1, "Tobias Lindqvist", "propagated")]


def test_repeats_of_any_found_value_are_redacted(monkeypatch):
    blocks = [make_block("Mail ops@acme.io now", 0), make_block("cc ops@acme.io", 1)]
    result = run(monkeypatch, blocks,
                 lambda b: [span(b, "ops@acme.io", "EMAIL")] if b.index == 0 else [])
    assert [(e.block_index, e.pii_type, e.detector) for e in result] == [
        (0, "EMAIL", "presidio"), (1, "EMAIL", "propagated")]

def test_detectors_lists_every_detector_name():
    """Every detector name written in the detection code is in DETECTORS."""
    import re
    from pathlib import Path

    from pii_pipeline.detection import detector as detector_module

    source = "".join(p.read_text(encoding="utf-8")
                     for p in Path(detector_module.__file__).parent.glob("*.py"))
    named = set(re.findall(r'detector="([^"]+)"', source))
    named |= {name for *_, name in detector_module.PATTERNS}
    assert named <= set(detector_module.DETECTORS)
    assert any(d.startswith("address_ner:") for d in detector_module.DETECTORS)
