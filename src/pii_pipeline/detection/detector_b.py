
"""
GLiNER-based supplementary PII detector.

Detects candidate person names and addresses that may be missed by
rule-based detection. Predictions are validated before being converted
into the pipeline's Entity format.

Limitations:
- Predictions may contain false positives or miss real PII.
- Confidence scores are not necessarily calibrated probabilities.
- Address components may be detected separately.
- Word-based chunks do not guarantee a strict model-token limit.
"""

import re

from gliner import GLiNER

from pii_pipeline.schemas import TextBlock, Entity


# =========================================================
# MODEL INITIALIZATION
# =========================================================

_model = None


def _get_model():
    """Load the shared GLiNER model lazily and reuse it."""
    global _model

    if _model is None:
        _model = GLiNER.from_pretrained(
            "urchade/gliner_small-v2.1"
        )

    return _model


# =========================================================
# ENTITY LABELS AND FILTERS
# =========================================================

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


_GENERIC_PERSON_TERMS = {
    "approver",
    "administrator",
    "reviewer",
    "user",
    "users",
    "owner",
    "manager",
    "stakeholder",
    "stakeholders",
    "employee",
    "employees",
    "director",
    "directors",
    "vendor",
    "vendors",
    "customer",
    "customers",
    "client",
    "clients",
    "author",
    "approvers",
    "administrators",
    "reviewers",
    "owners",
    "managers",
}


_LABEL_MAP = {
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

_RETAINED_LABELS = {
    "person",
    "address",
    "street address",
}


# =========================================================
# LONG-TEXT CHUNKING
# =========================================================

def _iter_text_chunks(
    text: str,
    max_words: int = 20,
    overlap_words: int = 5,
):
    """Yield text chunks and their original character offsets."""

    if max_words <= 0:
        raise ValueError("max_words must be positive")

    if not 0 <= overlap_words < max_words:
        raise ValueError(
            "overlap_words must be between 0 and max_words - 1"
        )

    words = list(re.finditer(r"\S+", text))

    if not words:
        return

    if len(words) <= max_words:
        yield 0, text
        return

    step = max_words - overlap_words

    for i in range(0, len(words), step):
        window = words[i:i + max_words]

        if not window:
            break

        start = window[0].start()
        end = window[-1].end()

        yield start, text[start:end]

        if i + max_words >= len(words):
            break


# =========================================================
# GLiNER DETECTION
# =========================================================

def detect_with_gliner(
    blocks: list[TextBlock],
) -> list[Entity]:
    """Detect person names and addresses in text blocks."""

    model = _get_model()
    entities: list[Entity] = []

    for block in blocks:
        # Deduplicate entities returned by overlapping chunks.
        seen_spans: set[tuple[int, int, str]] = set()

        for chunk_start, chunk_text in _iter_text_chunks(block.text):
            predictions = model.predict_entities(
                chunk_text,
                _LABELS,
                threshold=0.5,
            )

            for prediction in predictions:
                label = prediction["label"]

                if label not in _RETAINED_LABELS:
                    continue

                value = prediction["text"]
                local_start = prediction["start"]
                local_end = prediction["end"]

                # Validate offsets relative to the current chunk.
                if not (
                    isinstance(local_start, int)
                    and isinstance(local_end, int)
                    and 0 <= local_start < local_end <= len(chunk_text)
                ):
                    continue

                if chunk_text[local_start:local_end] != value:
                    continue

                # Convert chunk-relative offsets to original-block offsets.
                start = chunk_start + local_start
                end = chunk_start + local_end

                if not (0 <= start < end <= len(block.text)):
                    continue

                if block.text[start:end] != value:
                    continue

                normalized_value = value.strip().casefold()

                # Remove a known address-label false positive.
                if (
                    label in {"address", "street address"}
                    and normalized_value == "email address"
                ):
                    continue

                # Filter implausibly short or generic person predictions.
                if label == "person":
                    if len(normalized_value) < 2:
                        continue

                    if normalized_value in _GENERIC_PERSON_TERMS:
                        continue

                pii_type = _LABEL_MAP.get(label)

                if pii_type is None:
                    continue

                span_key = (start, end, pii_type)

                if span_key in seen_spans:
                    continue

                seen_spans.add(span_key)

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
