
"""Tests for the GLiNER-based supplementary PII detector."""

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector_b import detect_with_gliner


def make(text):
    """Create a TextBlock for testing."""
    return TextBlock("test.txt", "paragraph 1", 0, text)


# =========================================================
# PERSON-NAME DETECTION
# =========================================================

def test_gliner_detects_person_name():
    """Verify that GLiNER identifies a person name in context."""
    block = make("Employee Priyanka Raghavan joined the company.")

    entities = detect_with_gliner([block])
    persons = [e for e in entities if e.pii_type == "PERSON"]

    assert any(e.value == "Priyanka Raghavan" for e in persons)


# =========================================================
# ADDRESS DETECTION
# =========================================================

def test_gliner_detects_address_component():
    """Verify that GLiNER identifies a street-address component."""
    address = "1180 Ashwood Lane"
    block = make(f"Home address: {address}, Jersey City, NJ 07302")

    entities = detect_with_gliner([block])
    addresses = [e for e in entities if e.pii_type == "ADDRESS"]

    assert any(e.value == address for e in addresses)


# =========================================================
# CHARACTER-OFFSET VALIDATION
# =========================================================

def test_gliner_preserves_exact_offsets():
    """Verify that a person's offsets select the exact original text."""
    text = "Contact Priyanka Raghavan today."
    block = make(text)

    entities = detect_with_gliner([block])
    persons = [
        e for e in entities
        if e.pii_type == "PERSON"
        and e.value == "Priyanka Raghavan"
    ]

    assert persons
    entity = persons[0]
    assert text[entity.start:entity.end] == entity.value


# =========================================================
# ENTITY METADATA
# =========================================================

def test_gliner_entity_metadata():
    """Verify source metadata is preserved."""
    block = make("Employee Priyanka Raghavan joined the company.")

    entities = detect_with_gliner([block])
    persons = [e for e in entities if e.pii_type == "PERSON"]

    assert persons
    assert persons[0].detector == "gliner"
    assert persons[0].file == "test.txt"
    assert persons[0].block_index == 0


# =========================================================
# FILTER REGRESSION TESTS
# =========================================================

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

    block = make("The approver reviews the request.")
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

    block = make("Mail the letter to 221 Baker Street.")
    entities = detector_b.detect_with_gliner([block])

    assert any(e.pii_type == "ADDRESS" for e in entities)


def test_gliner_filters_email_address_phrase_as_address(monkeypatch):
    """Do not classify 'email address' as a physical address."""
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


# =========================================================
# LONG-TEXT CHUNKING
# =========================================================

def test_gliner_chunks_long_text_and_preserves_offsets(monkeypatch):
    """Long blocks preserve offsets and deduplicate overlapping results."""
    from pii_pipeline.detection import detector_b

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            predictions = []
            value = "Priyanka Raghavan"
            start = 0

            while True:
                start = text.find(value, start)
                if start == -1:
                    break

                predictions.append({
                    "text": value,
                    "start": start,
                    "end": start + len(value),
                    "label": "person",
                    "score": 0.95,
                })
                start += len(value)

            return predictions

    monkeypatch.setattr(detector_b, "_get_model", lambda: FakeModel())

    text = (
        "word " * 88
        + "Priyanka Raghavan "
        + "word " * 120
    )
    block = make(text)

    entities = detector_b.detect_with_gliner([block])
    persons = [
        e for e in entities
        if e.pii_type == "PERSON"
        and e.value == "Priyanka Raghavan"
    ]

    assert len(persons) == 1

    entity = persons[0]
    assert text[entity.start:entity.end] == entity.value
