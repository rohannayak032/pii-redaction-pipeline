"""
GLiNER-based supplementary PII detector.

This module uses GLiNER, a named-entity recognition model, to identify
potential PII entities that may be missed by rule-based detection.

The detector currently focuses on:
- Person names
- Addresses
- Street addresses

GLiNER predictions are treated as candidates, not guaranteed truths.
The integration checks confidence thresholds and character offsets
before converting predictions into the pipeline's Entity format.

Limitations:
- Predictions may contain false positives or miss real PII.
- A confidence score is not necessarily a calibrated probability.
- The model may return spans that include contextual labels.
- Address components may be detected separately rather than as one
  complete address.
"""

from gliner import GLiNER

from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# MODEL INITIALIZATION
# =========================================================

# Keep the model in memory after its first use.
# Loading a machine-learning model is relatively expensive, so we
# avoid reloading it for every block of text.
_model = None


# =========================================================
# ENTITY LABELS
# =========================================================

# Natural-language entity labels supplied to GLiNER.
# These labels describe the types of information the model should find.
#
# Some labels are currently filtered out after prediction because
# Detector A already handles structured PII, such as email addresses,
# phone numbers, and common identifier formats.
_LABELS = [
    "person",
    "email address",
    "phone number",
    "employee ID",
    "vendor ID",
    "social security number",
    "passport number",
    "tax identification number",
    "date of birth",
    "address",
    "street address",
    "location",
    "financial account number",
    "payment card number",
]


def _get_model():
    """
    Return the shared GLiNER model, loading it on first use.

    Lazy loading avoids loading the model when this module is imported
    but GLiNER detection is never actually requested.
    """

    global _model

    if _model is None:
        # Download or load the configured pretrained model.
        # Subsequent calls reuse this same model instance.
        _model = GLiNER.from_pretrained(
            "urchade/gliner_small-v2.1"
        )

    return _model


# =========================================================
# GLiNER DETECTION
# =========================================================

def detect_with_gliner(
    blocks: list[TextBlock],
) -> list[Entity]:
    """
    Detect supplementary PII candidates in text blocks.

    Args:
        blocks: Extracted text blocks to analyze.

    Returns:
        Entity objects containing the predicted PII category,
        original-text offsets, confidence score, detector identifier,
        and detected text value.

    Only person-name and address-related predictions are retained
    by the current filtering policy.
    """

    # Retrieve the cached model instead of loading it for every call.
    model = _get_model()

    # Collect all accepted predictions across the supplied blocks.
    entities: list[Entity] = []

    # Translate GLiNER's natural-language labels into the category
    # names expected by the rest of the PII pipeline.
    label_map = {
        "person": "PERSON",
        "email address": "EMAIL",
        "phone number": "PHONE",
        "employee ID": "EMPLOYEE_ID",
        "vendor ID": "VENDOR_ID",
        "social security number": "SSN",
        "passport number": "PASSPORT",
        "tax identification number": "TAX_ID",
        "date of birth": "DOB",
        "address": "ADDRESS",
        "street address": "ADDRESS",
        "location": "LOCATION",
        "financial account number": "ACCOUNT_NUMBER",
        "payment card number": "PAYMENT_CARD",
    }

    for block in blocks:

        # Ask GLiNER to identify entities in this block.
        # The threshold filters out predictions with scores below 0.5.
        # This is a configurable cutoff, not a guarantee of correctness.
        predictions = model.predict_entities(
            block.text,
            _LABELS,
            threshold=0.5,
        )

        # Retain only categories that GLiNER currently supplements.
        # Detector A handles the structured PII categories separately.
        predictions = [
            prediction
            for prediction in predictions
            if prediction["label"] in {
                "person",
                "address",
                "street address",
            }
        ]

        for prediction in predictions:

            # Extract the predicted text and its character offsets.
            # GLiNER offsets are expected to refer to the original block.
            value = prediction["text"]
            start = prediction["start"]
            end = prediction["end"]

            # Reject invalid spans before creating an Entity.
            # The start must precede the end, and both must fit inside
            # the original text block.
            if not (0 <= start < end <= len(block.text)):
                continue

            # Confirm that the offsets select exactly the predicted text.
            # This prevents inconsistent spans from reaching redaction.
            if block.text[start:end] != value:
                continue

            # Reject implausibly short person-name predictions.
            # A single character is usually a false positive in this pipeline.
            # Do not apply this rule to addresses.
            if prediction["label"] == "person":
                if len(value.strip()) < 2:
                    continue

            # Convert the model's label to the pipeline's PII category.
            label = prediction["label"]
            pii_type = label_map.get(label)

            # Skip any label that has no corresponding category.
            if pii_type is None:
                continue

            # Convert the model prediction into the shared Entity schema
            # so downstream pipeline stages can process it consistently.
            entities.append(
                Entity(
                    file=block.file,
                    block_index=block.index,
                    start=start,
                    end=end,
                    pii_type=pii_type,
                    confidence=float(prediction["score"]),
                    detector="gliner",
                    value=value,
                )
            )

    return entities
