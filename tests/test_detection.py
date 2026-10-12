import pytest

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector import detect


def make(text):
    # Create a TextBlock for testing.
    return TextBlock("a.txt", "para 1", 0, text)


# =========================================================
# EMAIL TESTS
# =========================================================

def test_finds_email_and_offsets_are_exact():
    block = make("Contact alice@example.com today")

    entities = detect([block])

    assert len(entities) == 1

    e = entities[0]

    assert e.pii_type == "EMAIL"
    assert e.value == "alice@example.com"
    assert block.text[e.start:e.end] == "alice@example.com"


def test_two_emails_in_one_block():
    entities = detect([make("a@x.com and b@y.org")])

    emails = [e for e in entities if e.pii_type == "EMAIL"]

    assert len(emails) == 2


def test_trailing_full_stop_not_included():
    block = make("Write to alice@example.com.")

    entities = detect([block])

    emails = [e for e in entities if e.pii_type == "EMAIL"]

    assert len(emails) == 1
    assert block.text[emails[0].start:emails[0].end] == "alice@example.com"


def test_no_email_no_result():
    assert detect([make("Nothing to see here, 123 at home")]) == []


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
    block = make(f"Call {phone} now")

    entities = detect([block])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert len(phones) == 1

    e = phones[0]

    assert e.pii_type == "PHONE"
    assert e.value == phone
    assert block.text[e.start:e.end] == phone


@pytest.mark.parametrize("text", [
    "Code 12345 is ready",
    "Date: 2026-10-07",
    "Ref 12345678901234567890 end",
])
def test_phone_not_matched(text):
    entities = detect([make(text)])

    phones = [e for e in entities if e.pii_type == "PHONE"]

    assert phones == []


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
    block = make(text)

    entities = detect([block])

    employee_ids = [
        e for e in entities
        if e.pii_type == "EMPLOYEE_ID"
    ]

    assert len(employee_ids) == 1

    e = employee_ids[0]

    assert e.value == employee_id
    assert block.text[e.start:e.end] == employee_id


@pytest.mark.parametrize("text", [
    "EMP-1234",
    "EMP-123456",
    "XEMP-37655ABC",
])
def test_invalid_employee_id_not_detected(text):
    entities = detect([make(text)])

    employee_ids = [
        e for e in entities
        if e.pii_type == "EMPLOYEE_ID"
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
    block = make(f"SSN: {ssn}")

    entities = detect([block])

    ssns = [e for e in entities if e.pii_type == "SSN"]

    assert len(ssns) == 1

    e = ssns[0]

    assert e.value == ssn
    assert block.text[e.start:e.end] == ssn


@pytest.mark.parametrize("text", [
    "805520432",
    "80-552-0432",
    "805-52-043",
])
def test_invalid_ssn_not_detected(text):
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
    block = make(f"PAN: {pan}")

    entities = detect([block])

    pans = [e for e in entities if e.pii_type == "PAN"]

    assert len(pans) == 1

    e = pans[0]

    assert e.value == pan
    assert block.text[e.start:e.end] == pan


@pytest.mark.parametrize("text", [
    "ABCDE123F",
    "ABCD12345F",
    "ABCDE12345F",
    "XABCDE1234FY",
])
def test_invalid_pan_not_detected(text):
    entities = detect([make(text)])

    pans = [e for e in entities if e.pii_type == "PAN"]

    assert pans == []


# =========================================================
# PASSPORT TESTS
# =========================================================

@pytest.mark.parametrize("passport", [
    "AB1#23456",
    "CD2#78901",
])
def test_passport_formats(passport):
    block = make(f"Passport: {passport}")

    entities = detect([block])

    passports = [
        e for e in entities
        if e.pii_type == "PASSPORT"
    ]

    assert len(passports) == 1

    e = passports[0]

    assert e.value == passport
    assert block.text[e.start:e.end] == passport


@pytest.mark.parametrize("text", [
    "AB123456",
    "AB1#2345",
    "AB1#234567",
])
def test_invalid_passport_not_detected(text):
    entities = detect([make(text)])

    passports = [
        e for e in entities
        if e.pii_type == "PASSPORT"
    ]

    assert passports == []


# =========================================================
# DOB TESTS
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
    block = make(text)

    entities = detect([block])

    dobs = [e for e in entities if e.pii_type == "DOB"]

    assert len(dobs) == 1

    e = dobs[0]

    # The entity value should contain only the date,
    # not the "DOB:" or "Date of birth:" label.
    assert e.value == expected_date

    # Verify that the stored offsets point exactly
    # to the date inside the original text.
    assert block.text[e.start:e.end] == expected_date


@pytest.mark.parametrize("text", [
    "The document was created on 14 July 1981.",
    "The meeting is scheduled for 05/12/2026.",
    "Policy effective date: 23-08-2026.",
    "Reborn 12/05/2026",
])
def test_ordinary_date_not_detected_as_dob(text):
    entities = detect([make(text)])

    dobs = [e for e in entities if e.pii_type == "DOB"]

    assert dobs == []

def test_person_detection():
    # Create a synthetic text block containing a person name.
    block = TextBlock(
        file="test.txt",
        location="paragraph 1",
        index=0,
        text="John Smith joined the company."
    )

    # Run the complete PII detection pipeline.
    entities = detect([block])

    # Keep only the entities classified as PERSON.
    persons = [e for e in entities if e.pii_type == "PERSON"]

    # Exactly one person should be detected.
    assert len(persons) == 1

    # Verify that the detected value is correct.
    assert persons[0].value == "John Smith"

    # Verify the exact character offsets.
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
