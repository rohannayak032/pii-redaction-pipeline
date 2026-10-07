import pytest

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection.detector import detect


# ---------------------------------------------------------
# TEST HELPER
# ---------------------------------------------------------

def make(text):
    """
    Create a simple TextBlock for testing.
    We use the same dummy file/block information for every test
    and only change the actual text being detected.
    """
    return TextBlock("a.txt", "para 1", 0, text)


# =========================================================
# EMAIL DETECTION TESTS
# =========================================================

def test_finds_email_and_offsets_are_exact():
    """
    Test that an email is detected and that its start/end
    positions point to exactly the email text.
    """

    # Create sample input text containing one email.
    block = make("Contact alice@example.com today")

    # Run the actual PII detection pipeline.
    # detect() expects a list of TextBlocks.
    entities = detect([block])

    # Exactly one entity should be detected.
    assert len(entities) == 1

    # Get the detected entity.
    e = entities[0]

    # Verify that the detected character range contains
    # exactly the email and not any surrounding text.
    assert block.text[e.start:e.end] == "alice@example.com"


def test_two_emails_in_one_block():
    """
    Test that multiple emails in the same text block
    are detected.
    """

    # The text contains two different email addresses.
    entities = detect([make("a@x.com and b@y.org")])

    # Both emails should be detected.
    assert len(entities) == 2


def test_trailing_full_stop_not_included():
    """
    Test that punctuation immediately after an email
    is not included in the detected PII.
    """

    block = make("Write to alice@example.com.")

    # Get the first detected entity.
    e = detect([block])[0]

    # The final '.' is sentence punctuation and should
    # NOT be part of the email entity.
    assert block.text[e.start:e.end] == "alice@example.com"


def test_no_email_no_result():
    """
    Test that text containing no email produces no entities.
    """

    # No PII is present, so detection should return an empty list.
    assert detect([make("Nothing to see here, 123 at home")]) == []


# =========================================================
# PHONE FALSE-POSITIVE TESTS
# =========================================================

@pytest.mark.parametrize("text", [
    "Code 12345 is ready",
    "Date: 2026-10-07",
    "Ref 12345678901234567890 end",
])
def test_phone_not_matched(text):
    """
    Test that ordinary numbers, dates and long reference IDs
    are not incorrectly detected as phone numbers.

    @pytest.mark.parametrize runs this same test once for
    each value in the list above.
    """

    # None of these strings should produce a PII entity.
    assert detect([make(text)]) == []


# =========================================================
# PHONE FORMAT TESTS
# =========================================================

@pytest.mark.parametrize("phone", [
    "+1 212-555-0198",       
    "(212) 555 0198",        # Parentheses + spaces
    "212.555.0198",          # Dots as separators
    "+91 98765 43210",       
    "+91-9876543210",        
    "+44 20 7946 0958",      
])
def test_phone_formats(phone):
    """
    Test that different valid phone-number formats
    are correctly detected.
    """

    # Insert the phone number into some normal text.
    block = make(f"Call {phone} now")

    # Run the detection pipeline.
    entities = detect([block])

    # Exactly one entity should be found.
    assert len(entities) == 1

    # Get the detected entity.
    e = entities[0]

    # Make sure the detector classified it as PHONE.
    assert e.pii_type == "PHONE"

    # Make sure the detected character range contains
    # exactly the original phone number.
    assert block.text[e.start:e.end] == phone


# =========================================================
# PHONE FALSE-POSITIVE / CONTEXT TESTS
# =========================================================

def test_does_not_detect_random_number_as_phone():
    """
    A random 10-digit number such as a transaction ID
    should not automatically be treated as a phone number.
    """

    block = make("The transaction ID is 1234567890")

    # Run detection.
    entities = detect([block])

    # Keep only entities classified as PHONE.
    phones = [e for e in entities if e.pii_type == "PHONE"]

    # No phone numbers should have been detected.
    assert phones == []


def test_does_not_detect_date_as_phone():
    """
    A date should not be incorrectly classified as a phone number.
    """

    block = make("The date is 12/05/2026")

    # Run detection.
    entities = detect([block])

    # Filter the results to PHONE entities only.
    phones = [e for e in entities if e.pii_type == "PHONE"]

    # The date should produce zero phone detections.
    assert phones == []