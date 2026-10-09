"""
Rule-based and Presidio-based PII detection.

This module detects structured PII using regular expressions and
specialized validation, and detects person names using Presidio.

Implemented detection categories:
- Email addresses
- Employee IDs
- Social Security Numbers (SSNs)
- Indian PAN identifiers
- Project-specific passport formats
- Payment cards validated with the Luhn checksum
- Phone numbers validated using the phonenumbers library
- Dates of birth identified using contextual labels
- Person names identified using Presidio and spaCy

Each detection is returned as an Entity containing its category,
character offsets in the original text block, confidence score,
detector identifier, and detected value.

Limitations:
- Regex formats do not cover every possible identifier format.
- Phone validation depends on numbering-plan metadata and the
  configured default region.
- DOB detection depends on recognizable birth-related labels.
- Person-name detection may produce false positives or miss names.
- A valid Luhn checksum does not establish that a card is real.
"""

import re

import phonenumbers
from phonenumbers import PhoneNumberMatcher
from presidio_analyzer import AnalyzerEngine

from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# PRESIDIO ANALYZER
# =========================================================

# Initialize Presidio once and reuse it across text blocks.
# Presidio uses an NLP model to identify person-name candidates.
presidio_analyzer = AnalyzerEngine()


# =========================================================
# EMAIL DETECTION
# =========================================================

# Match common email-address formats.
# Example: john.smith@example.com
# This pattern is practical for the project but is not a complete
# implementation of every email format permitted by email standards.
EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


# =========================================================
# EMPLOYEE ID DETECTION
# =========================================================

# Match EMP- followed by exactly five digits.
# Optional parentheses are accepted around the entire identifier.
# Alphanumeric boundaries prevent matching an ID embedded in a
# longer string, such as XEMP-37655ABC.
EMPLOYEE_ID = re.compile(
    r"(?<![A-Za-z0-9])"
    r"\(?"
    r"EMP-"
    r"\d{5}"
    r"\)?"
    r"(?![A-Za-z0-9])"
)


# =========================================================
# SOCIAL SECURITY NUMBER (SSN) DETECTION
# =========================================================

# Match the hyphenated SSN format, such as 805-52-0432.
# This checks the format only; it does not verify that the SSN
# was issued or is associated with a real person.
SSN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"\d{3}-\d{2}-\d{4}"
    r"(?![A-Za-z0-9])"
)


# =========================================================
# PAN DETECTION
# =========================================================

# Match the expected Indian PAN structure:
# five uppercase letters, four digits, and one uppercase letter.
# Example: ABCDE1234F
# This validates the format, not the actual issuance of the PAN.
PAN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Z]{5}\d{4}[A-Z]"
    r"(?![A-Za-z0-9])"
)


# =========================================================
# PASSPORT DETECTION
# =========================================================

# Match the two passport-like formats represented in our test data:
# 1. Two uppercase letters, one digit, '#', and five alphanumeric
#    characters, such as AB1#23456.
# 2. Two uppercase letters followed by seven digits, such as TK4820913.
# These are project-specific formats, not universal passport rules.
PASSPORT = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:[A-Z]{2}\d#[A-Z0-9]{5}|[A-Z]{2}\d{7})"
    r"(?![A-Za-z0-9])"
)


# =========================================================
# DATE OF BIRTH (DOB) DETECTION
# =========================================================

# Detect a date only when it follows a birth-related label.
# Supported labels include "Date of Birth", "DOB", and "Born".
# Group 1 captures the date itself so the label is not included
# in the detected PII value or its character offsets.
#
# Supported date forms include numeric dates and dates written
# with an English month name.
# This contextual approach reduces false positives from ordinary
# dates, but it can miss DOBs without a recognized label.
DOB = re.compile(
    r"(?i)"
    r"(?:date\s+of\s+birth|dob|born)"
    r"\s*[:\-]?\s*"
    r"("
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|"
    r"\d{1,2}\s+"
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
    r"\s+\d{4}"
    r")"
)


# =========================================================
# PAYMENT CARD DETECTION
# =========================================================

# Match candidate card numbers containing 13–19 digits.
# Spaces and hyphens may separate the digits.
# This pattern only finds candidates; passes_luhn() performs
# a separate checksum validation before an entity is returned.
PAYMENT_CARD = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
)


def passes_luhn(number: str) -> bool:
    """
    Validate a numeric candidate using the Luhn checksum.

    Formatting characters are ignored when extracting digits.
    The function checks the candidate's length and checksum.
    It does not prove that a card exists, is active, or belongs
    to a particular person.
    """

    # Keep only digits so formatted card numbers can be validated.
    digits = [int(char) for char in number if char.isdigit()]

    # Payment-card candidates must contain between 13 and 19 digits.
    if not 13 <= len(digits) <= 19:
        return False

    checksum = 0

    # Process digits from right to left, as required by the Luhn
    # algorithm. Every second digit, starting with the second
    # digit from the right, is doubled.
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2

            # Subtracting 9 from a doubled digit greater than 9
            # is equivalent to adding the digits of that result.
            if digit > 9:
                digit -= 9

        checksum += digit

    # A valid Luhn checksum produces a sum divisible by 10.
    return checksum % 10 == 0


# =========================================================
# PHONE NUMBER DETECTION
# =========================================================

def find_phones(
    block: TextBlock,
    region: str = "US",
) -> list[Entity]:
    """
    Find valid phone numbers inside a TextBlock.

    PhoneNumberMatcher locates phone-number candidates.
    is_valid_number() checks candidates against the library's
    numbering-plan metadata.

    The region is the default for numbers without an explicit
    international country code. It may need configuration for
    documents from other regions.
    """

    found = []

    # Search the original text for phone-number candidates.
    for match in PhoneNumberMatcher(block.text, region):

        # Ignore candidates that fail the library's validity checks.
        if not phonenumbers.is_valid_number(match.number):
            continue

        # Preserve the original text span and offsets so downstream
        # redaction can locate the number in the source text.
        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=match.start,
                end=match.end,
                pii_type="PHONE",
                confidence=0.95,
                detector="libphonenumber",
                value=match.raw_string,
            )
        )

    return found


# =========================================================
# DOB DETECTION
# =========================================================

def find_dobs(block: TextBlock) -> list[Entity]:
    """Find dates associated with DOB, Date of Birth, or Born labels."""

    found = []

    # finditer() provides each match and its position in the original text.
    for match in DOB.finditer(block.text):

        # Group 1 contains only the date, excluding the contextual label.
        date = match.group(1)

        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=match.start(1),
                end=match.end(1),
                pii_type="DOB",
                confidence=0.95,
                detector="regex.dob",
                value=date,
            )
        )

    return found


# =========================================================
# PERSON DETECTION
# =========================================================

def find_persons(block: TextBlock) -> list[Entity]:
    """
    Detect person-name candidates using Presidio and spaCy.

    The returned offsets refer to the original text block.
    NLP-based detection is heuristic, so predictions may need
    evaluation for false positives and missed names.
    """

    found = []

    # Ask Presidio to identify PERSON entities in English text.
    results = presidio_analyzer.analyze(
        text=block.text,
        language="en",
        entities=["PERSON"],
    )

    for result in results:
        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=result.start,
                end=result.end,
                pii_type="PERSON",
                confidence=result.score,
                detector="presidio.spacy",
                # Extract the exact substring corresponding to the
                # offsets returned by Presidio.
                value=block.text[result.start:result.end],
            )
        )

    return found


# =========================================================
# GENERAL REGEX DETECTION
# =========================================================

# Each tuple contains:
# 1. The compiled regular expression.
# 2. The PII category assigned to matches.
# 3. The configured confidence score.
# 4. An identifier describing the detection method.
#
# DOB and PAYMENT_CARD are handled separately because they require
# contextual matching or checksum validation.
PATTERNS = [
    (EMAIL, "EMAIL", 0.90, "regex.email"),
    (EMPLOYEE_ID, "EMPLOYEE_ID", 0.95, "regex.employee_id"),
    (SSN, "SSN", 0.95, "regex.ssn"),
    (PAN, "PAN", 0.95, "regex.pan"),
    (PASSPORT, "PASSPORT", 0.95, "regex.passport"),
]


def find_patterns(block: TextBlock) -> list[Entity]:
    """
    Run the implemented PII detectors on one TextBlock.

    This combines:
    1. Regular-expression detectors for structured identifiers.
    2. Payment-card candidate detection with Luhn validation.
    3. Phone-number detection and validation.
    4. Contextual date-of-birth detection.
    5. Presidio-based person-name detection.

    Each Entity retains offsets into the original block text.
    Results from different detectors may overlap; deduplication
    and overlap handling are responsibilities of the integration
    and redaction stages.
    """

    found = []

    # ---------------------------------------------------------
    # 1. Existing regex-based detectors
    # ---------------------------------------------------------

    # Find every match for each configured structured-PII pattern.
    for regex, pii_type, confidence, detector in PATTERNS:
        for match in regex.finditer(block.text):
            found.append(
                Entity(
                    file=block.file,
                    block_index=block.index,
                    start=match.start(),
                    end=match.end(),
                    pii_type=pii_type,
                    confidence=confidence,
                    detector=detector,
                    value=match.group(),
                )
            )

    # ---------------------------------------------------------
    # 2. Payment-card detection
    # ---------------------------------------------------------

    for match in PAYMENT_CARD.finditer(block.text):

        # Remove spaces and hyphens for checksum validation.
        # The Entity below still retains the original formatted value
        # and original character offsets.
        card_number = re.sub(r"[ -]", "", match.group())

        # Reject candidates that fail the Luhn checksum.
        if not passes_luhn(card_number):
            continue

        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=match.start(),
                end=match.end(),
                pii_type="PAYMENT_CARD",
                confidence=0.95,
                detector="regex.luhn",
                value=match.group(),
            )
        )

    # ---------------------------------------------------------
    # 3. Phone-number detection
    # ---------------------------------------------------------

    # Use the specialized library instead of relying on a broad
    # regular expression to identify phone-number formats.
    found.extend(find_phones(block))

    # ---------------------------------------------------------
    # 4. Contextual DOB detection
    # ---------------------------------------------------------

    # Only dates following recognized birth-related labels are matched.
    found.extend(find_dobs(block))

    # ---------------------------------------------------------
    # 5. Person-name detection
    # ---------------------------------------------------------

    # Add NLP-based person-name candidates from Presidio.
    found.extend(find_persons(block))

    return found
