import math

import pytest
from presidio_analyzer import RecognizerResult

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection import detector
from pii_pipeline.detection.detector import (
    SUPPORTED_ENTITIES,
    TYPE_MAP,
    detect,
    filter_overlapping_results,
)


def make(text, index=0, file="a.txt"):
    return TextBlock(file, "para 1", index, text)


def of_type(entities, pii_type):
    return [e for e in entities if e.pii_type == pii_type]


def test_email_offsets_exact():
    block = make("Contact alice@example.com today")
    found = of_type(detect([block]), "EMAIL")
    assert len(found) == 1
    e = found[0]
    assert block.text[e.start:e.end] == "alice@example.com"
    assert e.value == "alice@example.com"
    assert e.placeholder is None


def test_ssn_found():
    block = make("SSN 123-45-6789 is on file")
    found = of_type(detect([block]), "SSN")
    assert len(found) == 1
    assert block.text[found[0].start:found[0].end] == "123-45-6789"


def test_employee_id_found():
    block = make("Employee EMP-38104 joined in spring")
    found = of_type(detect([block]), "EMPLOYEE_ID")
    assert len(found) == 1
    assert block.text[found[0].start:found[0].end] == "EMP-38104"


def test_vendor_id_found():
    # Guards against the missing-comma bug in the reference code.
    block = make("Vendor MER-IN-4471 was paid")
    found = of_type(detect([block]), "VENDOR_ID")
    assert len(found) == 1


def test_every_entity_offset_matches_its_value():
    blocks = [
        make("Mail bob@example.org or call EMP-12345", index=4, file="mail.txt"),
        make("SSN 123-45-6789", index=9, file="id.txt"),
    ]
    blocks_by_source = {(block.file, block.index): block for block in blocks}
    for e in detect(blocks):
        block = blocks_by_source[(e.file, e.block_index)]
        assert 0 <= e.start < e.end <= len(block.text)
        assert block.text[e.start:e.end] == e.value
        assert 0.0 <= e.confidence <= 1.0


def test_offsets_reference_original_text_after_normalization():
    block = make("🙂 Contact\u200b\u00a0alice@example.org", index=5, file="source.txt")

    email = next(e for e in detect([block]) if e.pii_type == "EMAIL")

    assert (email.file, email.block_index) == ("source.txt", 5)
    assert block.text[email.start:email.end] == email.value
    assert email.start == block.text.index("alice@example.org")


def test_type_map_covers_supported_entities_with_optiv_labels():
    assert set(TYPE_MAP) == set(SUPPORTED_ENTITIES)
    assert TYPE_MAP == {
        "EMAIL_ADDRESS": "EMAIL",
        "PHONE_NUMBER": "PHONE",
        "US_SSN": "SSN",
        "DATE_TIME": "DATE",
        "STREET_ADDRESS": "LOCATION",
        "CREDIT_CARD": "CREDIT_CARD",
        "PERSON": "PERSON",
        "LOCATION": "LOCATION",
        "IP_ADDRESS": "IP_ADDRESS",
        "URL": "URL",
        "IN_PAN": "IN_PAN",
        "PASSPORT": "PASSPORT",
        "EMPLOYEE_ID": "EMPLOYEE_ID",
        "DIRECTOR_ID": "DIRECTOR_ID",
        "VENDOR_ID": "VENDOR_ID",
    }


SUPPORTED_TYPE_CASES = [
    (
        "EMAIL_ADDRESS",
        "EMAIL",
        "Contact alice@example.invalid today",
        "alice@example.invalid",
        "Contact alice@example today",
    ),
    (
        "PHONE_NUMBER",
        "PHONE",
        "Call +1 (415) 555-1212",
        "+1 (415) 555-1212",
        "Call 12345",
    ),
    (
        "CREDIT_CARD",
        "CREDIT_CARD",
        "Card 4111 1111 1111 1111",
        "4111 1111 1111 1111",
        "Card 4111 1111 1111 1112",
    ),
    (
        "PERSON",
        "PERSON",
        "Contact Dr. Jane Smith today",
        "Dr. Jane Smith",
        "The policy document contains no named individual.",
    ),
    (
        "LOCATION",
        "LOCATION",
        "They live in Paris.",
        "Paris",
        "This sentence has no named geographic entity.",
    ),
    (
        "IP_ADDRESS",
        "IP_ADDRESS",
        "Server 192.0.2.10 responded",
        "192.0.2.10",
        "Server 999.999.999.999 responded",
    ),
    (
        "DATE_TIME",
        "DATE",
        "Meeting on January 14, 2024",
        "January 14, 2024",
        "quarterly review in 2022",
    ),
    (
        "URL",
        "URL",
        "Profile linkedin.com/in/janedoe",
        "linkedin.com/in/janedoe",
        "This is not a web address",
    ),
    (
        "US_SSN",
        "SSN",
        "SSN 123-45-6789",
        "123-45-6789",
        "SSN 123456789",
    ),
    (
        "IN_PAN",
        "IN_PAN",
        "PAN AQBPR7741L",
        "AQBPR7741L",
        "PAN AQBPR774L",
    ),
    (
        "PASSPORT",
        "PASSPORT",
        "Passport number X1234567",
        "X1234567",
        "Reference X1234567 was recorded",
    ),
    (
        "EMPLOYEE_ID",
        "EMPLOYEE_ID",
        "Employee EMP-38104",
        "EMP-38104",
        "Employee employee-38104",
    ),
    (
        "DIRECTOR_ID",
        "DIRECTOR_ID",
        "Director DIR-0042",
        "DIR-0042",
        "Director DIR-42",
    ),
    (
        "VENDOR_ID",
        "VENDOR_ID",
        "Vendor MER-IN-4471",
        "MER-IN-4471",
        "Vendor MER-AB-12",
    ),
    (
        "STREET_ADDRESS",
        "LOCATION",
        "Ship to 88 Willowbank Court, Hoboken, NJ 07030",
        "88 Willowbank Court, Hoboken, NJ 07030",
        "Ship to 88 Unknown Building",
    ),
]


@pytest.mark.parametrize(
    ("recognizer_type", "expected_label", "positive_text", "anchor", "negative_text"),
    SUPPORTED_TYPE_CASES,
    ids=[case[0] for case in SUPPORTED_TYPE_CASES],
)
def test_supported_type_has_synthetic_positive_with_source_metadata(
    recognizer_type, expected_label, positive_text, anchor, negative_text
):
    assert recognizer_type in detector.analyzer.get_supported_entities()
    assert TYPE_MAP[recognizer_type] == expected_label
    block = make(positive_text, index=17, file="synthetic-positive.txt")

    found = detect((block,))
    start = positive_text.index(anchor)
    end = start + len(anchor)
    matches = [
        entity
        for entity in found
        if entity.pii_type == expected_label
        and entity.start == start
        and entity.end == end
    ]

    assert matches
    for entity in matches:
        assert (entity.file, entity.block_index) == (block.file, block.index)
        assert 0 <= entity.start < entity.end <= len(block.text)
        assert block.text[entity.start:entity.end] == entity.value
        assert math.isfinite(entity.confidence)
        assert 0.0 <= entity.confidence <= 1.0


@pytest.mark.parametrize(
    ("recognizer_type", "expected_label", "positive_text", "anchor", "negative_text"),
    SUPPORTED_TYPE_CASES,
    ids=[case[0] for case in SUPPORTED_TYPE_CASES],
)
def test_supported_type_has_synthetic_negative(
    recognizer_type, expected_label, positive_text, anchor, negative_text
):
    assert recognizer_type in detector.analyzer.get_supported_entities()
    found = detect([make(negative_text, index=18, file="synthetic-negative.txt")])

    assert not any(entity.pii_type == expected_label for entity in found)


def test_overlapping_types_are_preserved_and_exact_duplicates_are_collapsed():
    results = [
        RecognizerResult("PERSON", 0, 10, 0.8),
        RecognizerResult("PERSON", 0, 10, 0.95),
        RecognizerResult("EMAIL_ADDRESS", 5, 20, 0.9),
        RecognizerResult("CREDIT_CARD", 5, 20, 0.85),
    ]

    kept = filter_overlapping_results(results)

    assert [(r.entity_type, r.start, r.end) for r in kept] == [
        ("PERSON", 0, 10),
        ("CREDIT_CARD", 5, 20),
        ("EMAIL_ADDRESS", 5, 20),
    ]
    assert kept[0].score == 0.95


def test_email_hint_finds_name_in_another_block(monkeypatch):
    monkeypatch.setattr(detector.analyzer, "analyze", lambda **kwargs: [])
    blocks = [
        make("p.raghunathan@corp.example", index=3, file="directory.txt"),
        make("Priyanka Raghunathan", index=8, file="directory.txt"),
    ]

    found = detect(blocks)

    hinted_name = next(
        e for e in found
        if e.block_index == 8 and e.pii_type == "PERSON"
    )
    assert (hinted_name.start, hinted_name.end) == (0, len(blocks[1].text))
    assert blocks[1].text[hinted_name.start:hinted_name.end] == hinted_name.value
    assert hinted_name.detector == "presidio.email-hint"


def test_name_consistency_finds_repeated_name(monkeypatch):
    name = "Priyanka Raghunathan"
    text = f"{name} spoke; {name} left."
    first_start = text.index(name)

    def analyze(*, text, **kwargs):
        if text == text_fixture:
            return [
                RecognizerResult(
                    "PERSON", first_start, first_start + len(name), 0.9
                )
            ]
        return []

    text_fixture = text
    monkeypatch.setattr(detector.analyzer, "analyze", analyze)

    found = [e for e in detect([make(text)]) if e.pii_type == "PERSON"]

    assert [(e.start, e.end) for e in found] == [
        (first_start, first_start + len(name)),
        (text.rindex(name), text.rindex(name) + len(name)),
    ]


def test_name_consistency_finds_repeated_name_in_another_block(monkeypatch):
    name = "Priyanka Raghunathan"
    first_text = f"{name} is listed."
    second_text = f"Contact {name} soon."

    def analyze(*, text, **kwargs):
        if text == first_text:
            start = text.index(name)
            return [RecognizerResult("PERSON", start, start + len(name), 0.9)]
        return []

    monkeypatch.setattr(detector.analyzer, "analyze", analyze)
    blocks = [
        make(first_text, index=3, file="directory.txt"),
        make(second_text, index=8, file="directory.txt"),
    ]

    found = detect(blocks)
    second_entity = next(
        entity
        for entity in found
        if entity.block_index == 8 and entity.pii_type == "PERSON"
    )

    assert second_entity.detector == "presidio.name-consistency"
    assert (second_entity.start, second_entity.end) == (
        second_text.index(name),
        second_text.index(name) + len(name),
    )
    assert second_text[second_entity.start:second_entity.end] == second_entity.value


def test_address_and_phone_are_detected_with_original_offsets():
    text = "Call +1 (415) 555-1212; visit 88 Willowbank Court, Hoboken, NJ 07030."
    block = make(text, index=12, file="contact.txt")

    found = detect([block])

    phone = next(e for e in found if e.pii_type == "PHONE")
    address = next(
        e for e in found
        if e.pii_type == "LOCATION" and text[e.start:e.end].startswith("88")
    )
    assert text[phone.start:phone.end] == "+1 (415) 555-1212"
    assert text[address.start:address.end] == "88 Willowbank Court, Hoboken, NJ 07030"
    assert (phone.file, phone.block_index) == ("contact.txt", 12)
    assert (address.file, address.block_index) == ("contact.txt", 12)


@pytest.mark.parametrize(
    ("text", "expected_phone"),
    [
        ("Call +91 98765 43210 today", "+91 98765 43210"),
        ("Call 98765 43210 today", "98765 43210"),
    ],
)
def test_indian_phone_formats_are_detected_exactly(text, expected_phone):
    block = make(text, index=13, file="phone.txt")

    phone = next(
        entity
        for entity in detect([block])
        if entity.pii_type == "PHONE"
        and block.text[entity.start:entity.end] == expected_phone
    )

    assert (phone.file, phone.block_index) == (block.file, block.index)
    assert block.text[phone.start:phone.end] == phone.value
    assert math.isfinite(phone.confidence)
    assert 0.0 <= phone.confidence <= 1.0


def test_repeated_identical_values_keep_both_source_spans():
    text = "Email alice@example.invalid, then email alice@example.invalid again."
    block = make(text, index=14, file="repeated.txt")

    emails = [
        entity
        for entity in detect([block])
        if entity.pii_type == "EMAIL"
    ]

    assert [(entity.start, entity.end) for entity in emails] == [
        (text.index("alice@example.invalid"), text.index("alice@example.invalid") + len("alice@example.invalid")),
        (text.rindex("alice@example.invalid"), text.rindex("alice@example.invalid") + len("alice@example.invalid")),
    ]
    for entity in emails:
        assert (entity.file, entity.block_index) == (block.file, block.index)
        assert block.text[entity.start:entity.end] == entity.value


def test_multiple_pii_types_in_one_block_keep_their_own_offsets():
    text = "Email alice@example.invalid; employee EMP-38104."
    block = make(text, index=16, file="multiple.txt")

    found = detect([block])

    assert {entity.pii_type for entity in found} >= {"EMAIL", "EMPLOYEE_ID"}
    for entity in found:
        assert (entity.file, entity.block_index) == (block.file, block.index)
        assert 0 <= entity.start < entity.end <= len(block.text)
        assert block.text[entity.start:entity.end] == entity.value
        assert entity.pii_type in set(TYPE_MAP.values())


def test_empty_sequences_and_whitespace_blocks_return_no_entities():
    assert detect([]) == []
    assert detect(()) == []
    assert detect((make("", index=15),)) == []
    assert detect((make(" \t\n", index=15),)) == []


def test_value_is_hidden_from_repr():
    e = detect([make("Mail bob@example.org")])[0]
    assert "bob@example.org" not in repr(e)


def test_text_without_pii_gives_nothing_important():
    found = detect([make("Nothing to see here")])
    assert of_type(found, "EMAIL") == []
    assert of_type(found, "SSN") == []
