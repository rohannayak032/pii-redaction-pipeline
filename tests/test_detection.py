import pytest
from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector import detect


def make(text):
    return TextBlock("a.txt", "para 1", 0, text)


def test_finds_email_and_offsets_are_exact():
    block = make("Contact alice@example.com today")
    entities = detect([block])
    assert len(entities) == 1
    e = entities[0]
    assert block.text[e.start:e.end] == "alice@example.com"


def test_two_emails_in_one_block():
    entities = detect([make("a@x.com and b@y.org")])
    assert len(entities) == 2


def test_trailing_full_stop_not_included():
    block = make("Write to alice@example.com.")
    e = detect([block])[0]
    assert block.text[e.start:e.end] == "alice@example.com"


def test_no_email_no_result():
    assert detect([make("Nothing to see here, 123 at home")]) == []

@pytest.mark.parametrize("text", [
    "Code 12345 is ready",
    "Date: 2026-10-07",
    "Ref 12345678901234567890 end",
])
def test_phone_not_matched(text):
    assert detect([make(text)]) == []


@pytest.mark.parametrize("phone", [
    "+1 212-555-0198",
    "(212) 555 0198",
    "212.555.0198",
])
def test_phone_formats(phone):
    block = make(f"Call {phone} now")
    entities = detect([block])
    assert len(entities) == 1
    e = entities[0]
    assert e.pii_type == "PHONE"
    assert block.text[e.start:e.end] == phone

    def test_finds_phone():
        block = make("Call me at +1 212-555-0198")
        entities = detect([block])

        phones = [e for e in entities if e.pii_type == "PHONE"]

        assert len(phones) == 1
        assert phones[0].value == "+1 212-555-0198"

@pytest.mark.parametrize("phone", [
    "+1 212-555-0198",
    "(212) 555 0198",
    "212.555.0198",
    "+91 98765 43210",
    "+91-9876543210",
    "+44 20 7946 0958",
])
def test_phone_formats(phone):
    block = make(f"Call {phone} now")
    entities = detect([block])
    assert len(entities) == 1

def test_does_not_detect_random_number_as_phone():
    block = make("The transaction ID is 1234567890")
    entities = detect([block])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []


def test_does_not_detect_date_as_phone():
    block = make("The date is 12/05/2026")
    entities = detect([block])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []