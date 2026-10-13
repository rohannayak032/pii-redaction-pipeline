"""
Indian address detector built on a token-classification model.

The shiprocket-ai address models tag address *components* (house,
road, locality, city, state, pincode...). Redaction needs the whole
address, so neighbouring components are merged into one ADDRESS span.

A merged span is kept only if two different component types sit close
together somewhere in it. A lone city ("our Pune office"), a list of
cities or a lone 6-digit number is not an address, and the models tag
those even outside addresses.
"""

import re

from transformers import pipeline

from pii_pipeline.schemas import TextBlock, Entity
from pii_pipeline.detection.detector_b import _windows


# TinyBERT fine-tuned with notebooks/address_ner_colab.ipynb: on the test set it
# matched fine-tuned ModernBERT's recall at a quarter of the latency.
# Hosted on Hugging Face so everyone gets it; downloaded once, then cached.
MODEL = "PhoenixKnight/indian-address-tinybert-ft"

# Components at most _MAX_GAP characters apart belong to the same address.
# Gaps hold punctuation and untagged filler like ", P.O-" or "Unclassified";
# 99% of gaps in the gold data are under 43 characters.
_MAX_GAP = 40
# An address needs two different component types at most this far apart.
_CORE_GAP = 12

# On non-Indian documents the model tags headings, IDs and table rows as
# addresses, so a span is kept only if it has a 6-digit PIN code or names
# an Indian state, union territory or major city.
# shortcut: city list covers big cities only; extend it if real addresses with neither PIN nor state get dropped.
_INDIAN_SIGNAL = re.compile(
    # PIN not inside a longer number, so phone fragments like "212 555-0147" don't count.
    r"(?<![\d+-])(?<![\d+-]\s)[1-9]\d{2}\s?\d{3}(?!\s?[\d-])"
    r"|\b(?:India|Andhra|Arunachal|Assam|Bihar|Chhattisgarh|Goa|Gujarat|Haryana|Himachal"
    r"|Jharkhand|Karnataka|Kerala|Madhya Pradesh|Maharashtra|Manipur|Meghalaya|Mizoram"
    r"|Nagaland|Odisha|Orissa|Punjab|Rajasthan|Sikkim|Tamil\s?Nadu|Telangana|Tripura"
    r"|Uttar Pradesh|Uttarakhand|West Bengal|Delhi|Jammu|Kashmir|Ladakh|Puducherry"
    r"|Pondicherry|Chandigarh|Andaman|Lakshadweep|Dadra|Daman"
    r"|Mumbai|Bombay|Bengaluru|Bangalore|Hyderabad|Ahmedabad|Chennai|Madras|Kolkata"
    r"|Calcutta|Pune|Jaipur|Lucknow|Kanpur|Nagpur|Indore|Thane|Bhopal|Visakhapatnam"
    r"|Patna|Vadodara|Ghaziabad|Ludhiana|Agra|Nashik|Noida|Gurugram|Gurgaon|Coimbatore"
    r"|Kochi|Cochin|Mysuru|Mysore|Surat|Guwahati|Bhubaneswar|Thiruvananthapuram"
    r"|Dehradun|Ranchi|Raipur|Amritsar|Varanasi|Madurai|Vijayawada)\b",
    re.IGNORECASE,
)

# Loading a model is expensive, so each one is loaded once.
_models: dict = {}


def make_pipeline(model, tokenizer=None):
    """Token-classification pipeline from a model name, folder or loaded model."""
    return pipeline("token-classification", model=model, tokenizer=tokenizer,
                    aggregation_strategy="simple")


def _get_model(name: str):
    if name not in _models:
        _models[name] = make_pipeline(name)
    return _models[name]


def merge_components(text: str, components: list[dict]) -> list[tuple[int, int, float]]:
    """
    Merge component spans into (start, end, confidence) address spans.

    components: dicts with "start", "end", "label" and "score".
    """
    groups: list[list[dict]] = []
    for c in sorted(components, key=lambda c: c["start"]):
        if groups and _close(text, groups[-1][-1], c, _MAX_GAP):
            groups[-1].append(c)
        else:
            groups.append([c])

    addresses = []
    for g in groups:
        if not any(a["label"] != b["label"] and _close(text, a, b, _CORE_GAP)
                   for a, b in zip(g, g[1:])):
            continue
        start = g[0]["start"]
        end = max(c["end"] for c in g)
        # Models cut words in half ("Gu" + "wahati"); never leave half a word visible.
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end < len(text) and text[end].isalnum():
            end += 1
        score = sum(c["score"] for c in g) / len(g)
        addresses.append((start, end, score))
    return addresses


def _close(text: str, a: dict, b: dict, max_gap: int) -> bool:
    gap = text[a["end"]:b["start"]]
    # A blank line ends a paragraph, and so ends the address.
    return len(gap) <= max_gap and "\n\n" not in gap


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
            if not value or not _INDIAN_SIGNAL.search(value):
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
