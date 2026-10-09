"""Tests for the GLiNER-based supplementary PII detector."""

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector_b import detect_with_gliner


def make(text):
    """
    Create a TextBlock for testing.

    A fixed file name, location, and block index keep the tests
    focused on GLiNER's predictions and entity metadata.
    """
    return TextBlock("test.txt", "paragraph 1", 0, text)


# =========================================================
# PERSON-NAME DETECTION
# =========================================================

def test_gliner_detects_person_name():
    """Verify that GLiNER can identify a person name in context."""

    block = make("Employee Priyanka Raghavan joined the company.")

    # Run the supplementary detector on the text block.
    entities = detect_with_gliner([block])

    # Keep only entities classified as person names.
    persons = [e for e in entities if e.pii_type == "PERSON"]

    # The name should appear among the returned person entities.
    # Other predictions may also be returned for the same block.
    assert any(e.value == "Priyanka Raghavan" for e in persons)


# =========================================================
# ADDRESS DETECTION
# =========================================================

def test_gliner_detects_address_component():
    """Verify that GLiNER identifies a street-address component."""

    address = "1180 Ashwood Lane"
    block = make(f"Home address: {address}, Jersey City, NJ 07302")

    # Analyze a sample address containing street, city, and region details.
    entities = detect_with_gliner([block])

    # Keep entities mapped to the ADDRESS category.
    addresses = [e for e in entities if e.pii_type == "ADDRESS"]

    # Confirm that the street-address component is detected.
    # This test does not require the entire postal address to be one entity.
    assert any(e.value == address for e in addresses)


# =========================================================
# CHARACTER-OFFSET VALIDATION
# =========================================================

def test_gliner_preserves_exact_offsets():
    """
    Verify that a detected name's offsets select its exact text.

    Correct offsets are essential because downstream redaction uses
    these positions to locate text in the original block.
    """

    text = "Contact Priyanka Raghavan today."
    block = make(text)

    entities = detect_with_gliner([block])

    # Find the expected person-name entity.
    persons = [
        e for e in entities
        if e.pii_type == "PERSON"
        and e.value == "Priyanka Raghavan"
    ]

    # Ensure the expected entity was found before checking its offsets.
    assert persons

    entity = persons[0]

    # The half-open slice [start:end] must reproduce the entity value.
    assert text[entity.start:entity.end] == entity.value


# =========================================================
# ENTITY METADATA
# =========================================================

def test_gliner_entity_metadata():
    """Verify that GLiNER entities preserve their source metadata."""

    block = make("Employee Priyanka Raghavan joined the company.")

    entities = detect_with_gliner([block])

    persons = [e for e in entities if e.pii_type == "PERSON"]

    # At least one person entity should be returned for this example.
    assert persons

    # The detector field identifies which detection method produced it.
    assert persons[0].detector == "gliner"

    # The source file and block index must be preserved for traceability.
    assert persons[0].file == "test.txt"
    assert persons[0].block_index == 0

def test_gliner_filters_generic_person_role(monkeypatch):
    """Do not classify a generic role word as a person."""
    from pii_pipeline.detection import detector_b

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            value = "approver"
            start = text.index(value)
            return [{
                "text": value,
                "start": start,
                "end": start + len(value),
                "label": "person",
                "score": 0.95,
            }]

    monkeypatch.setattr(detector_b, "_get_model", lambda: FakeModel())

    block = TextBlock(
        file="test.txt",
        location="paragraph 1",
        index=0,
        text="The approver reviews the request.",
    )

    entities = detector_b.detect_with_gliner([block])

    assert not [e for e in entities if e.pii_type == "PERSON"]


def test_gliner_keeps_address_predictions(monkeypatch):
    """Filtering person-role words must not remove addresses."""
    from pii_pipeline.detection import detector_b

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            value = "221 Baker Street"
            start = text.index(value)
            return [{
                "text": value,
                "start": start,
                "end": start + len(value),
                "label": "address",
                "score": 0.95,
            }]

    monkeypatch.setattr(detector_b, "_get_model", lambda: FakeModel())

    block = TextBlock(
        file="test.txt",
        location="paragraph 1",
        index=0,
        text="Mail the letter to 221 Baker Street.",
    )

    entities = detector_b.detect_with_gliner([block])

    assert any(e.pii_type == "ADDRESS" for e in entities)


def test_gliner_filters_email_address_phrase_as_address(monkeypatch):
    """Do not treat the phrase 'email address' as a physical address."""
    from pii_pipeline.detection import detector_b

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            value = "email address"
            start = text.index(value)
            return [{
                "text": value,
                "start": start,
                "end": start + len(value),
                "label": "address",
                "score": 0.95,
            }]

    monkeypatch.setattr(detector_b, "_get_model", lambda: FakeModel())

    block = make("Search and add users by name or email address.")

    entities = detector_b.detect_with_gliner([block])

    assert not [
        e for e in entities
        if e.pii_type == "ADDRESS" and e.value == "email address"
    ]
