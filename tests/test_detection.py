"""Tests for rule-based and Presidio-based PII detection."""

import pytest

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector import detect


def make(text):
    """
    Create a TextBlock containing the supplied text.

    Using a helper keeps individual tests short and consistent.
    The file name, location, and block index are fixed because
    most tests focus on detection behavior rather than metadata.
    """
    return TextBlock("a.txt", "para 1", 0, text)


# =========================================================
# EMAIL TESTS
# =========================================================

def test_finds_email_and_offsets_are_exact():
    """Detect an email and verify its value and character offsets."""

    block = make("Contact alice@example.com today")

    entities = detect([block])

    # Keep only detections classified as email addresses.
    emails = [e for e in entities if e.pii_type == "EMAIL"]

    assert len(emails) == 1
    assert emails[0].value == "alice@example.com"

    # Confirm that the offsets point to the exact email in the
    # original text. This is important for accurate redaction.
    assert block.text[emails[0].start:emails[0].end] == "alice@example.com"


def test_two_emails_in_one_block():
    """Detect multiple email addresses in the same text block."""

    entities = detect([make("a@x.com and b@y.org")])

    emails = [e for e in entities if e.pii_type == "EMAIL"]

    assert len(emails) == 2


def test_trailing_full_stop_not_included():
    """Ensure sentence punctuation is not included in the email span."""

    block = make("Write to alice@example.com.")

    entities = detect([block])
    emails = [e for e in entities if e.pii_type == "EMAIL"]

    assert len(emails) == 1
    assert block.text[emails[0].start:emails[0].end] == "alice@example.com"


def test_no_email_no_result():
    """Ensure ordinary text without an email produces no email entity."""

    entities = detect([make("Nothing to see here, 123 at home")])

    assert not any(e.pii_type == "EMAIL" for e in entities)


# =========================================================
# PHONE TESTS
# =========================================================

@pytest.mark.parametrize("phone", [
    "+1 212-555-0198",
    "(212) 555 0198",
    "212.555.0198",
    "+91 98765 43210",
    "+91-9876543210",
    "+44 20 7946 0958",
    # Indian numbers without +91.
    "98765 43210",
    "9876543210",
    "022 2345 6789",
])
def test_phone_formats(phone):
    """Detect phone numbers in several common international formats."""

    block = make(f"Call {phone} now")

    entities = detect([block])
    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert len(phones) == 1
    assert phones[0].value == phone

    # Verify that formatting characters and offsets are preserved.
    assert block.text[phones[0].start:phones[0].end] == phone


@pytest.mark.parametrize("text", [
    "Code 12345 is ready",
    "Date: 2026-10-07",
    "Ref 12345678901234567890 end",
])
def test_phone_not_matched(text):
    """Reject examples that should not be identified as phone numbers."""

    entities = detect([make(text)])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []


def test_does_not_detect_random_number_as_phone():
    """Avoid treating an ordinary transaction number as a phone number."""

    entities = detect([make("The transaction ID is 1234567890")])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []


def test_does_not_detect_date_as_phone():
    """Ensure a date is not incorrectly classified as a phone number."""

    entities = detect([make("The date is 12/05/2026")])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []


# =========================================================
# EMPLOYEE ID TESTS
# =========================================================

@pytest.mark.parametrize("employee_id, text", [
    ("EMP-37655", "Employee ID: EMP-37655"),
    ("EMP-38104", "Employee ID: EMP-38104"),
    # Parentheses stay outside the span.
    ("EMP-37655", "Employee ID: (EMP-37655)"),
])
def test_employee_id_formats(employee_id, text):
    """Detect employee IDs in the supported formats."""

    block = make(text)

    entities = detect([block])
    employee_ids = [
        e for e in entities if e.pii_type == "EMPLOYEE_ID"
    ]

    assert len(employee_ids) == 1
    assert employee_ids[0].value == employee_id

    # Check that the span covers exactly the identifier,
    # without surrounding parentheses.
    assert block.text[
        employee_ids[0].start:employee_ids[0].end
    ] == employee_id


@pytest.mark.parametrize("text", [
    "EMP-1234",
    "EMP-123456",
    "XEMP-37655ABC",
])
def test_invalid_employee_id_not_detected(text):
    """Reject employee IDs with invalid lengths or surrounding characters."""

    entities = detect([make(text)])

    employee_ids = [
        e for e in entities if e.pii_type == "EMPLOYEE_ID"
    ]

    assert employee_ids == []


# =========================================================
# SSN TESTS
# =========================================================

@pytest.mark.parametrize("ssn", [
    "805-52-0432",
    "900-42-7721",
])
def test_ssn_formats(ssn):
    """Detect SSNs that match the supported hyphenated format."""

    block = make(f"SSN: {ssn}")

    entities = detect([block])
    ssns = [e for e in entities if e.pii_type == "SSN"]

    assert len(ssns) == 1
    assert ssns[0].value == ssn
    assert block.text[ssns[0].start:ssns[0].end] == ssn


@pytest.mark.parametrize("text", [
    "805520432",
    "80-552-0432",
    "805-52-043",
])
def test_invalid_ssn_not_detected(text):
    """Reject SSNs that do not match the expected structure."""

    entities = detect([make(text)])

    ssns = [e for e in entities if e.pii_type == "SSN"]

    assert ssns == []


# =========================================================
# PAN TESTS
# =========================================================

@pytest.mark.parametrize("pan", [
    "ABCDE1234F",
    "QWERT1234Z",
])
def test_pan_formats(pan):
    """Detect PAN identifiers matching the expected format."""

    block = make(f"PAN: {pan}")

    entities = detect([block])
    pans = [e for e in entities if e.pii_type == "PAN"]

    assert len(pans) == 1
    assert pans[0].value == pan
    assert block.text[pans[0].start:pans[0].end] == pan


@pytest.mark.parametrize("text", [
    "ABCDE123F",
    "ABCD12345F",
    "ABCDE12345F",
    "XABCDE1234FY",
])
def test_invalid_pan_not_detected(text):
    """Reject PAN candidates with incorrect structure or boundaries."""

    entities = detect([make(text)])

    pans = [e for e in entities if e.pii_type == "PAN"]

    assert pans == []


# =========================================================
# PASSPORT TESTS
# =========================================================

@pytest.mark.parametrize("passport", [
    "AB1#23456",
    "CD2#78901",
    "TK4820913",  # Passport-style format found in the case-study example.
])
def test_passport_formats(passport):
    """Detect passport identifiers matching the project's supported formats."""

    block = make(f"Passport: {passport}")

    entities = detect([block])
    passports = [e for e in entities if e.pii_type == "PASSPORT"]

    assert len(passports) == 1
    assert passports[0].value == passport
    assert block.text[passports[0].start:passports[0].end] == passport


@pytest.mark.parametrize("text", [
    "AB123456",
    "AB1#2345",
    "AB1#234567",
])
def test_invalid_passport_not_detected(text):
    """Reject passport candidates that do not match supported formats."""

    entities = detect([make(text)])

    passports = [e for e in entities if e.pii_type == "PASSPORT"]

    assert passports == []


# =========================================================
# DATE OF BIRTH (DOB) TESTS
# =========================================================

@pytest.mark.parametrize("text, expected_date", [
    ("Date of birth: 14 July 1981", "14 July 1981"),
    ("DATE OF BIRTH: 05/12/1990", "05/12/1990"),
    ("DOB: 23-08-1985", "23-08-1985"),
    ("dob - 7 March 2001", "7 March 2001"),
    ("Born: 12/10/1995", "12/10/1995"),
    ("Born on 7 March 2001", "7 March 2001"),
    ("DOB: 1985-08-23", "1985-08-23"),
    ("D.O.B: 14-Jul-1981", "14-Jul-1981"),
])
def test_dob_formats(text, expected_date):
    """Detect supported date formats when a birth-related label is present."""

    block = make(text)

    entities = detect([block])
    dobs = [e for e in entities if e.pii_type == "DOB"]

    assert len(dobs) == 1
    assert dobs[0].value == expected_date

    # The entity should cover only the date, not the DOB label.
    assert block.text[dobs[0].start:dobs[0].end] == expected_date


@pytest.mark.parametrize("text", [
    "The document was created on 14 July 1981.",
    "The meeting is scheduled for 05/12/2026.",
    "Policy effective date: 23-08-2026.",
    "Reborn 12/05/2026",
])
def test_ordinary_date_not_detected_as_dob(text):
    """Avoid classifying ordinary dates as DOBs without birth context."""

    entities = detect([make(text)])

    dobs = [e for e in entities if e.pii_type == "DOB"]

    assert dobs == []


# =========================================================
# PERSON TESTS
# =========================================================

def test_person_detection():
    """Detect a person name using the configured NLP-based detector."""

    block = make("John Smith joined the company.")

    entities = detect([block])
    persons = [e for e in entities if e.pii_type == "PERSON"]

    assert len(persons) == 1
    assert persons[0].value == "John Smith"
    assert persons[0].start == 0
    assert persons[0].end == 10

def test_all_caps_person_detection():
    block = make("PRIYA NAIR | EMP-37655 | Finance")

    persons = [e for e in detect([block]) if e.pii_type == "PERSON"]

    assert [block.text[e.start:e.end] for e in persons] == ["PRIYA NAIR"]


def test_job_title_not_detected_as_person():
    entities = detect([make("Contact the Sales Director for details")])

    assert [e for e in entities if e.pii_type == "PERSON"] == []


# =========================================================
# INDIAN GOVERNMENT ID TESTS (Presidio recognizers)
# =========================================================

def test_aadhaar_detection():
    # Fake number that passes the Aadhaar (Verhoeff) checksum.
    block = make("Aadhaar: 2345 6789 0124")

    aadhaars = [e for e in detect([block]) if e.pii_type == "AADHAAR"]

    assert [block.text[e.start:e.end] for e in aadhaars] == ["2345 6789 0124"]


def test_aadhaar_checksum_failure_not_detected():
    entities = detect([make("Aadhaar: 2345 6789 0123")])

    assert [e for e in entities if e.pii_type == "AADHAAR"] == []


def test_indian_passport_detection():
    block = make("Passport no. J8369854")

    passports = [e for e in detect([block]) if e.pii_type == "PASSPORT"]

    assert [block.text[e.start:e.end] for e in passports] == ["J8369854"]


# =========================================================
# PAYMENT CARD TESTS
# =========================================================

def test_valid_payment_card():
    """Detect a synthetic card number that passes the Luhn checksum."""

    # Synthetic test card number; do not use real card data.
    block = make("Test card: 4111111111111111")

    entities = detect([block])
    cards = [e for e in entities if e.pii_type == "PAYMENT_CARD"]

    assert len(cards) == 1
    assert cards[0].value == "4111111111111111"
    assert block.text[cards[0].start:cards[0].end] == cards[0].value


def test_payment_card_with_spaces():
    """Detect a card candidate with spaces between digit groups."""

    block = make("Test card: 4111 1111 1111 1111")

    entities = detect([block])
    cards = [e for e in entities if e.pii_type == "PAYMENT_CARD"]

    assert len(cards) == 1
    assert cards[0].value == "4111 1111 1111 1111"
    assert block.text[cards[0].start:cards[0].end] == cards[0].value


def test_payment_card_with_hyphens():
    """Detect a card candidate with hyphens between digit groups."""

    block = make("Test card: 4111-1111-1111-1111")

    entities = detect([block])
    cards = [e for e in entities if e.pii_type == "PAYMENT_CARD"]

    assert len(cards) == 1
    assert cards[0].value == "4111-1111-1111-1111"
    assert block.text[cards[0].start:cards[0].end] == cards[0].value


def test_invalid_luhn_number_not_detected_as_payment_card():
    """Reject a card-shaped number that fails the Luhn checksum."""

    block = make("Test number: 4111111111111112")

    entities = detect([block])
    cards = [e for e in entities if e.pii_type == "PAYMENT_CARD"]

    assert cards == []
