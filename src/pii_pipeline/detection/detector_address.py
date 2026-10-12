"""
Indian address detector built on a token-classification model.

The shiprocket-ai address models tag address *components* (house,
road, locality, city, state, pincode...). Redaction needs the whole
address, so neighbouring components are merged into one ADDRESS span.

A merged span is kept only if it has at least two different component
types. A lone city ("our Pune office") or a lone 6-digit number is not
an address, and the models tag those even outside addresses.
"""

from transformers import pipeline

from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.detection.detector_b import _windows


MODEL = "shiprocket-ai/open-modernbert-indian-address-ner"

# Components separated by at most this many characters belong to the same
# address. Gaps hold punctuation and untagged prefixes like ", P.O-".
_MAX_GAP = 12
_MIN_TYPES = 2

# Loading a model is expensive, so each one is loaded once.
_models: dict = {}


def _get_model(name: str):
    if name not in _models:
        _models[name] = pipeline(
            "token-classification", model=name, aggregation_strategy="simple",
        )
    return _models[name]


def merge_components(text: str, components: list[dict]) -> list[tuple[int, int, float]]:
    """
    Merge component spans into (start, end, confidence) address spans.

    components: dicts with "start", "end", "label" and "score".
    """
    groups: list[list[dict]] = []
    for c in sorted(components, key=lambda c: c["start"]):
        if groups:
            gap = text[groups[-1][-1]["end"]:c["start"]]
            # A blank line ends a paragraph, and so ends the address.
            if len(gap) <= _MAX_GAP and "\n\n" not in gap:
                groups[-1].append(c)
                continue
        groups.append([c])

    addresses = []
    for g in groups:
        if len({c["label"] for c in g}) < _MIN_TYPES:
            continue
        start = g[0]["start"]
        end = max(c["end"] for c in g)
        score = sum(c["score"] for c in g) / len(g)
        addresses.append((start, end, score))
    return addresses


def detect_indian_addresses(blocks: list[TextBlock], model: str = MODEL) -> list[Entity]:
    """Detect complete Indian addresses in text blocks."""
    ner = _get_model(model)
    entities: list[Entity] = []

    for block in blocks:
        components = []
        for offset, chunk in _windows(block.text):
            for p in ner(chunk):
                components.append({
                    "start": p["start"] + offset,
                    "end": p["end"] + offset,
                    "label": p["entity_group"],
                    "score": float(p["score"]),
                })

        # Overlapping windows report the same component twice.
        components = list({(c["start"], c["end"]): c for c in components}.values())

        for start, end, score in merge_components(block.text, components):
            value = block.text[start:end]
            # Tokenizers may include leading spaces in a span.
            lead = len(value) - len(value.lstrip())
            start, value = start + lead, value.strip()
            if not value:
                continue
            entities.append(
                Entity(
                    file=block.file,
                    block_index=block.index,
                    start=start,
                    end=start + len(value),
                    pii_type="ADDRESS",
                    confidence=score,
                    detector=f"address_ner:{model.split('/')[-1]}",
                    value=value,
                )
            )
    return entities
