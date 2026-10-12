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

import re

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

# GLiNER label -> the pipeline's PII category.
#
# Ask only for labels we keep. GLiNER gives each span one label, so
# extra labels steal spans: with "location" in the list, "Mumbai" in
# an address became a location and was thrown away. Structured PII
# (emails, phones, IDs) is left to Detector A.
_LABEL_MAP = {
    "person": "PERSON",
    "address": "ADDRESS",
    "street address": "ADDRESS",
}
_LABELS = list(_LABEL_MAP)

# GLiNER flags pronouns ("She", "He") as people.
_PRONOUNS = {
    "i", "me", "you", "he", "him", "she", "her", "it", "we", "us",
    "they", "them", "his", "hers", "their", "theirs",
}

# GLiNER reads at most ~384 tokens and silently ignores the rest, and
# it counts punctuation as tokens. Long blocks are therefore read in
# overlapping windows of whitespace-separated words.
_WINDOW_WORDS = 200
_OVERLAP_WORDS = 50   # an entity shorter than this is whole in some window


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

    for block in blocks:

        # Overlapping windows find the same entity twice.
        seen: set[tuple[int, int, str]] = set()

        for offset, chunk in _windows(block.text):

            # The threshold filters out predictions with scores below 0.5.
            # This is a configurable cutoff, not a guarantee of correctness.
            predictions = model.predict_entities(chunk, _LABELS, threshold=0.5)

            for prediction in predictions:

                # GLiNER offsets refer to the chunk; shift them to the block.
                value = prediction["text"]
                start = prediction["start"] + offset
                end = prediction["end"] + offset

                # Reject spans that do not select exactly the predicted
                # text, so inconsistent offsets never reach redaction.
                if not (0 <= start < end <= len(block.text)):
                    continue
                if block.text[start:end] != value:
                    continue

                pii_type = _LABEL_MAP[prediction["label"]]

                if pii_type == "PERSON" and value.lower() in _PRONOUNS:
                    continue

                if (start, end, pii_type) in seen:
                    continue
                seen.add((start, end, pii_type))

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


def _windows(text: str) -> list[tuple[int, str]]:
    """Split text into overlapping word windows: (start offset, chunk)."""

    words = list(re.finditer(r"\S+", text))
    if len(words) <= _WINDOW_WORDS:
        return [(0, text)]

    windows = []
    step = _WINDOW_WORDS - _OVERLAP_WORDS
    for i in range(0, len(words), step):
        first, last = words[i], words[min(i + _WINDOW_WORDS, len(words)) - 1]
        windows.append((first.start(), text[first.start():last.end()]))
        if i + _WINDOW_WORDS >= len(words):
            break
    return windows
