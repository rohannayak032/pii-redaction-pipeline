import re
import phonenumbers
from phonenumbers import PhoneNumberMatcher

# TextBlock = input to our detector
# Entity = standardized representation of detected PII
from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# EMAIL DETECTION
# =========================================================

# re.compile() converts the regex into a reusable pattern.
EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


# List of regex-based PII detectors.
#
# Each entry contains:
#   1. The regex pattern
#   2. The type of PII it detects
#   3. Confidence assigned to the detection
#   4. Name of the detector used
#
# This makes it easy to add more regex-based PII types later.
PATTERNS = [
    (EMAIL, "EMAIL", 0.9, "regex.email"),
]


# =========================================================
# PHONE NUMBER DETECTION
# =========================================================

def find_phones(block: TextBlock, region: str = "US") -> list[Entity]:
    """
    Find valid phone numbers inside a TextBlock.

    We use the phonenumbers library instead of trying to
    create one huge regex for every country's phone formats.

    region:
        Default country/region used when a number does not
        contain an explicit country code.
    """

    # Store all valid phone-number entities found in this block.
    found = []

    # Search the entire text for possible phone numbers.
    # PhoneNumberMatcher identifies phone-like candidates.
    # It does NOT mean every candidate is necessarily valid.
    for match in PhoneNumberMatcher(block.text, region):

        # Validate the candidate using libphonenumber.
  
        if not phonenumbers.is_valid_number(match.number):
            continue

        # Convert the valid phone number into our standard
        # Entity format so the rest of the pipeline can use it.
        found.append(Entity(
            # Which source file did this PII come from?
            file=block.file,

            # Which text block contains the PII?
            block_index=block.index,

            # Starting character position of the phone number.
            start=match.start,

            # Ending character position of the phone number.
            end=match.end,

            # Classification of this PII.
            pii_type="PHONE",

            # Confidence assigned to this detection.
            confidence=0.95,

            # Identifies which detection method produced it.
            detector="libphonenumber",

            # Store the exact phone-number text from the document.
            value=match.raw_string,
        ))

    # Return every valid phone entity found in the block.
    return found


# =========================================================
# GENERAL PATTERN DETECTION
# =========================================================

def find_patterns(block: TextBlock) -> list[Entity]:
    """
    Run all pattern-based detectors on a TextBlock.

    Currently this includes:
        - Email regex detection
        - Phone-number detection
    """

    # This will contain all PII entities detected in the block.
    found = []

    # -----------------------------------------------------
    # REGEX-BASED DETECTORS
    # -----------------------------------------------------

    # Go through every detector registered in PATTERNS.

    for regex, pii_type, confidence, detector in PATTERNS:

        # Search the entire text for every occurrence
        # of the current regex pattern.
        for m in regex.finditer(block.text):

            # Convert each regex match into our standard
            # Entity object.
            found.append(Entity(
                # Source file containing the PII.
                file=block.file,

                # Text block containing the PII.
                block_index=block.index,

                # Exact starting character position.
                start=m.start(),

                # Exact ending character position.
                end=m.end(),

                # PII classification supplied by PATTERNS.
                pii_type=pii_type,

                # Confidence supplied by PATTERNS.
                confidence=confidence,

                # Detector that produced this entity.
                detector=detector,

                # Exact text matched by the regex.
                value=m.group(),
            ))

    # -----------------------------------------------------
    # PHONE DETECTION
    # -----------------------------------------------------

    # Phone detection uses libphonenumber rather than a
    # normal regex, so we run it separately.

    # extend() adds all phone entities to the existing
    # list instead of creating a nested list.
    found.extend(find_phones(block))

    # Return all detected PII from this text block.
    return found
