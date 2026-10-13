"""Tests for the combined PII detection pipeline."""

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
