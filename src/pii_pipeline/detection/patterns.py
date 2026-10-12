import re

import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberType
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.predefined_recognizers import InAadhaarRecognizer, InPassportRecognizer

from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# PRESIDIO ANALYZER
# =========================================================

# Create the Presidio analyzer once and reuse it for all
# text blocks instead of creating a new analyzer each time.
#
# Presidio uses spaCy as its NLP engine for entities such
# as PERSON.
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

# Match standard email addresses such as:
# john.smith@example.com
#
# re.compile() converts the regex into a reusable pattern.
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

# Match the SSN format observed in the sample documents:
# 3 digits - 2 digits - 4 digits
#
# Example:
# 805-52-0432
SSN = re.compile(
    r"(?<![A-Za-z0-9])"  # Not immediately preceded by a letter or digit.
    r"\d{3}"              # Exactly 3 digits.
    r"-"                  # Hyphen.
    r"\d{2}"              # Exactly 2 digits.
    r"-"                  # Hyphen.
    r"\d{4}"              # Exactly 4 digits.
    r"(?![A-Za-z0-9])"   # Not immediately followed by a letter or digit.
)


# =========================================================
# PAN DETECTION
# =========================================================

# PAN (Permanent Account Number) format:
# 5 uppercase letters + 4 digits + 1 uppercase letter.
#
# Example:
# ABCDE1234F
PAN = re.compile(
    r"(?<![A-Za-z0-9])"  # Not immediately preceded by a letter or digit.
    r"[A-Z]{5}"           # Exactly 5 uppercase letters.
    r"\d{4}"              # Exactly 4 digits.
    r"[A-Z]"              # Exactly 1 uppercase letter.
    r"(?![A-Za-z0-9])"   # Not immediately followed by a letter or digit.
)


# =========================================================
# PASSPORT DETECTION
# =========================================================

# Match the passport-style format observed in the sample documents:
# 2 uppercase letters + 1 digit + '#' + 5 alphanumeric characters.
#
# Example:
# AB1#23456
PASSPORT = re.compile(
    r"(?<![A-Za-z0-9])"  # Not immediately preceded by a letter or digit.
    r"[A-Z]{2}"           # Exactly 2 uppercase letters.
    r"\d"                 # Exactly 1 digit.
    r"#"                  # Literal '#' character.
    r"[A-Z0-9]{5}"        # Exactly 5 uppercase letters or digits.
    r"(?![A-Za-z0-9])"   # Not immediately followed by a letter or digit.
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

    # Return every valid phone entity found in the block.
    return found


# =========================================================
# DOB DETECTION
# =========================================================

def find_dobs(block: TextBlock) -> list[Entity]:
    """
    Find dates of birth inside a TextBlock.

    The detector uses contextual labels such as:
        "Date of birth:"
        "DOB:"
        "Born:"

    Only the actual date is returned as the Entity value.
    """

    # Store all DOB entities found in this text block.
    found = []

    # Search the block for a birth-related label followed by a date.
    for match in DOB.finditer(block.text):

        # Group 1 contains only the actual date,
        # not the "DOB:" or "Date of birth:" label.
        date = match.group(1)

        # Find the exact starting character position of the date.
        start = match.start(1)

        # Find the exact ending character position of the date.
        end = match.end(1)

        # Create an Entity containing only the date.
        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=start,
                end=end,
                pii_type="DOB",
                confidence=0.95,
                detector="regex.dob",
                value=date,
            )
        )

    # Return all DOB entities found in the block.
    return found


# =========================================================
# PERSON DETECTION
# =========================================================

def find_presidio(block: TextBlock) -> list[Entity]:
    """
    Detect person names (Presidio + spaCy NER) and Indian
    government IDs (Presidio's Aadhaar and passport recognizers).

    Presidio performs the PII analysis while spaCy provides
    the underlying NLP/NER capabilities.
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

    # IMPORTANT:
    # Return the list so find_patterns() can add these entities
    # to the overall detection result.
    return found


# =========================================================
# GENERAL PATTERN DETECTION
# =========================================================

# List of regex-based PII detectors.
#
# Each entry contains:
#   1. The regex pattern.
#   2. The PII type.
#   3. The confidence assigned to the detection.
#   4. The detector name.
#
# DOB is intentionally NOT included here because its regex
# uses surrounding context and captures only part of the match.
PATTERNS = [
    (EMAIL, "EMAIL", 0.90, "regex.email"),
    (EMPLOYEE_ID, "EMPLOYEE_ID", 0.95, "regex.employee_id"),
    (SSN, "SSN", 0.95, "regex.ssn"),
    (PAN, "PAN", 0.95, "regex.pan"),
    (PASSPORT, "PASSPORT", 0.95, "regex.passport"),
]


def find_patterns(block: TextBlock) -> list[Entity]:
    """
    Run all currently implemented PII detectors on a TextBlock.

    This combines:
        - Regex-based structured PII detection
        - libphonenumber phone detection
        - Contextual DOB detection
        - Presidio + spaCy PERSON detection
    """

    # Store every entity detected in this block.
    found = []

    # ---------------------------------------------------------
    # 1. Regex-based detectors
    # ---------------------------------------------------------

    for regex, pii_type, confidence, detector in PATTERNS:

        # Find every occurrence of the current pattern.
        for match in regex.finditer(block.text):

            # Convert the regex match into our standard Entity schema.
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
    # 2. Phone-number detection
    # ---------------------------------------------------------

    # Use libphonenumber because phone numbers have many
    # different country-specific formats.
    found.extend(find_phones(block))

    # ---------------------------------------------------------
    # 3. Date-of-birth detection
    # ---------------------------------------------------------

    # Use contextual matching because an ordinary date should
    # not automatically be classified as DOB.
    found.extend(find_dobs(block))

    # ---------------------------------------------------------
    # 4. Person names and Indian government IDs
    # ---------------------------------------------------------

    # Use Presidio: spaCy NER for names, checksum/context rules for IDs.
    found.extend(find_presidio(block))

    # Return every detected PII entity from this block.
    return found