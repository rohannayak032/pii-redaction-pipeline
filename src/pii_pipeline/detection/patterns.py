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
from phonenumbers import PhoneNumberMatcher, PhoneNumberType
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.predefined_recognizers import InAadhaarRecognizer, InPassportRecognizer

from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# PRESIDIO ANALYZER
# =========================================================

# Initialize Presidio once and reuse it across text blocks.
# Presidio uses an NLP model to identify person-name candidates.
presidio_analyzer = AnalyzerEngine()

# India recognizers ship with Presidio but are off by default.
# Aadhaar is checksum-validated; passport scores low unless a
# context word like "passport" is nearby.
presidio_analyzer.registry.add_recognizer(InAadhaarRecognizer())
presidio_analyzer.registry.add_recognizer(InPassportRecognizer())

# Presidio entity name -> our pii_type.
PRESIDIO_TYPES = {
    "PERSON": "PERSON",
    "IN_AADHAAR": "AADHAAR",
    "IN_PASSPORT": "PASSPORT",
}

# Two all-caps words in a row, e.g. "PRIYA NAIR". spaCy misses
# names written like this, so such blocks get a second pass.
CAPS_RUN = re.compile(r"\b[A-Z]{2,}\s+[A-Z]{2,}\b")


def overlaps(entity: Entity, found: list[Entity]) -> bool:
    """True if `entity` overlaps a span of the same type already in `found`."""
    return any(
        e.pii_type == entity.pii_type and e.start < entity.end and entity.start < e.end
        for e in found
    )


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

# Employee IDs follow the observed format:
# EMP- followed by exactly 5 digits.
#
# Surrounding parentheses stay outside the span, so
# "(EMP-37655)" yields "EMP-37655".
EMPLOYEE_ID = re.compile(
    r"(?<![A-Za-z0-9])"  # Not immediately preceded by a letter or digit.
    r"EMP-"              # Required EMP- prefix.
    r"\d{5}"             # Exactly 5 digits.
    r"(?![A-Za-z0-9])"   # Not immediately followed by a letter or digit.
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

# Look for a birth-related label followed by a date.
#
# Examples:
# Date of birth: 14 July 1981
# DATE OF BIRTH: 05/12/1990
# DOB: 23-08-1985
# D.O.B: 1985-08-23
# Born on 7 March 2001
# DOB: 14-Jul-1981
#
# The surrounding label provides the context that tells us
# that the date represents a person's date of birth.
DOB = re.compile(
    r"(?i)"  # Make the pattern case-insensitive.
    r"\b(?:date\s+of\s+birth|d\.?o\.?b\.?|born(?:\s+on)?)\b"  # Birth-related label, whole words only.
    r"\s*[:\-]?\s*"  # Optional spaces and ':' or '-'.
    r"("  # Capture only the actual date.
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"  # Numeric date.
        r"|"
        r"\d{4}-\d{2}-\d{2}"  # ISO date.
        r"|"
        r"\d{1,2}[\s-]+"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"  # Full or short month.
        r"[\s-]+\d{4}"  # Written date.
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

INDIAN_MOBILE = (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE)


def find_phones(block: TextBlock, regions: tuple[str, ...] = ("US", "IN")) -> list[Entity]:
    """
    Find valid phone numbers inside a TextBlock.

    The phonenumbers library is used instead of creating one
    large regex for every country's phone-number format.

    Args:
        block: TextBlock containing the text to analyze.
        regions: Countries tried, in order, for numbers without
                 an explicit country code. The documents mix US
                 and Indian numbers.

    Returns:
        A list of detected phone-number entities.
    """

    # Store all valid phone-number entities found in this block.
    found = []

    for region in regions:

        # PhoneNumberMatcher identifies phone-like candidates,
        # but a candidate is not necessarily a valid phone number.
        for match in PhoneNumberMatcher(block.text, region):

            if not phonenumbers.is_valid_number(match.number):
                continue

            # Almost any 10 digits is a valid Indian landline, so without
            # a leading 0 accept only mobiles: "1234567890" is not a phone.
            if (
                region == "IN"
                and not match.raw_string.startswith("0")
                and phonenumbers.number_type(match.number) not in INDIAN_MOBILE
            ):
                continue

            entity = Entity(
                file=block.file,
                block_index=block.index,
                start=match.start,
                end=match.end,
                pii_type="PHONE",
                confidence=0.95,
                detector="libphonenumber",
                value=match.raw_string,
            )

            # A number with a country code is found once per region.
            if not overlaps(entity, found):
                found.append(entity)

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

def find_presidio(block: TextBlock) -> list[Entity]:
    """
    Detect person names (Presidio + spaCy NER) and Indian
    government IDs (Presidio's Aadhaar and passport recognizers).

    The returned offsets refer to the original text block.
    NLP-based detection is heuristic, so predictions may need
    evaluation for false positives and missed names.
    """

    text = block.text

    # Store all entities detected in this text block.
    found = []

    # spaCy relies on capitalisation, so "PRIYA NAIR" is missed.
    # Title-casing keeps every offset when the length is unchanged.
    passes = [text]
    titled = text.title()
    if CAPS_RUN.search(text) and len(titled) == len(text):
        passes.append(titled)

    for i, analyzed in enumerate(passes):
        results = presidio_analyzer.analyze(
            text=analyzed,
            language="en",
            entities=list(PRESIDIO_TYPES),
        )

        for result in results:
            span = text[result.start:result.end]

            # From the title-cased pass keep only all-caps spans;
            # elsewhere it would invent names from capitalised words.
            if i == 1 and not span.isupper():
                continue

            entity = Entity(
                file=block.file,
                block_index=block.index,
                start=result.start,
                end=result.end,
                pii_type=PRESIDIO_TYPES[result.entity_type],
                confidence=result.score,
                detector="presidio",
                value=span,
            )
            if not overlaps(entity, found):
                found.append(entity)

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
    # 4. Person names and Indian government IDs
    # ---------------------------------------------------------

    # Use Presidio: spaCy NER for names, checksum/context rules for IDs.
    found.extend(find_presidio(block))

    return found
