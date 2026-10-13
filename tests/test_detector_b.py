"""Tests for the GLiNER-based supplementary PII detector."""

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector_b import _windows, detect_with_gliner


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


# =========================================================
# LONG BLOCKS, LABELS AND PRONOUNS
# =========================================================

def test_windows_cover_every_word_with_exact_offsets():
    """Long text is split into overlapping windows whose offsets match."""

    text = " ".join(f"w{i}" for i in range(500))
    windows = _windows(text)

    assert len(windows) > 1
    for offset, chunk in windows:
        assert text[offset:offset + len(chunk)] == chunk
    covered = {w for _, chunk in windows for w in chunk.split()}
    assert covered == set(text.split())


def test_gliner_finds_name_after_model_input_limit():
    """A name past GLiNER's ~384-token limit must still be found."""

    filler = "The committee reviewed the quarterly risk report in detail. " * 60
    block = make(filler + "Approved by Priya Nair.")

    persons = [e for e in detect_with_gliner([block]) if e.pii_type == "PERSON"]

    assert [block.text[e.start:e.end] for e in persons] == ["Priya Nair"]


def test_gliner_keeps_city_in_address():
    """A city inside an address must not be lost as an unused 'location' label."""

    block = make("She lives in Andheri East, Mumbai 400069.")

    values = [e.value for e in detect_with_gliner([block]) if e.pii_type == "ADDRESS"]

    assert any("Mumbai" in v for v in values)


def test_gliner_ignores_pronouns():
    """Pronouns are not names."""

    entities = detect_with_gliner([make("She lives in Andheri East, Mumbai 400069.")])

    assert [e for e in entities if e.pii_type == "PERSON"] == []
