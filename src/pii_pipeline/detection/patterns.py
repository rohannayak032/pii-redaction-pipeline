import re

import phonenumbers
from phonenumbers import PhoneNumberMatcher
from presidio_analyzer import AnalyzerEngine

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
# Parentheses may optionally surround the entire ID:
# EMP-37655
# (EMP-37655)
EMPLOYEE_ID = re.compile(
    r"(?<![A-Za-z0-9])"  # Not immediately preceded by a letter or digit.
    r"\(?"               # Optional opening parenthesis.
    r"EMP-"              # Required EMP- prefix.
    r"\d{5}"             # Exactly 5 digits.
    r"\)?"               # Optional closing parenthesis.
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
# Born: 7 March 2001
#
# The surrounding label provides the context that tells us
# that the date represents a person's date of birth.
DOB = re.compile(
    r"(?i)"  # Make the pattern case-insensitive.
    r"(?:date\s+of\s+birth|dob|born)"  # Birth-related label.
    r"\s*[:\-]?\s*"  # Optional spaces and ':' or '-'.
    r"("  # Capture only the actual date.
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"  # Numeric date.
        r"|"
        r"\d{1,2}\s+"
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+\d{4}"  # Written date.
    r")"
)


# =========================================================
# PHONE NUMBER DETECTION
# =========================================================

def find_phones(block: TextBlock, region: str = "US") -> list[Entity]:
    """
    Find valid phone numbers inside a TextBlock.

    The phonenumbers library is used instead of creating one
    large regex for every country's phone-number format.

    Args:
        block: TextBlock containing the text to analyze.
        region: Default country/region used when a number does
                not contain an explicit country code.

    Returns:
        A list of detected phone-number entities.
    """

    # Store all valid phone-number entities found in this block.
    found = []

    # Search the entire text for phone-number candidates.
    #
    # PhoneNumberMatcher identifies phone-like candidates,
    # but a candidate is not necessarily a valid phone number.
    for match in PhoneNumberMatcher(block.text, region):

        # Validate the candidate using Google's libphonenumber
        # data through the phonenumbers Python library.
        if not phonenumbers.is_valid_number(match.number):
            continue

        # Convert the validated phone number into our standard
        # Entity format.
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

def find_persons(block: TextBlock) -> list[Entity]:
    """
    Detect person names using Presidio + spaCy NER.

    Presidio performs the PII analysis while spaCy provides
    the underlying NLP/NER capabilities.
    """

    # Store all PERSON entities detected in this text block.
    found = []

    # Ask Presidio to analyze the text specifically for PERSON
    # entities.
    results = presidio_analyzer.analyze(
        text=block.text,
        language="en",
        entities=["PERSON"],
    )

    # Process every PERSON entity detected by Presidio.
    for result in results:

        # Convert Presidio's result into our project's
        # standardized Entity schema.
        found.append(
            Entity(
                file=block.file,
                block_index=block.index,
                start=result.start,
                end=result.end,
                pii_type="PERSON",
                confidence=result.score,
                detector="presidio.spacy",
                value=block.text[result.start:result.end],
            )
        )

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
    # 4. Person-name detection
    # ---------------------------------------------------------

    # Use Presidio + spaCy NER for unstructured person names.
    found.extend(find_persons(block))

    # Return every detected PII entity from this block.
    return found