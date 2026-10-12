"""
Build training and evaluation data for Indian address detection.

Source: gagan1985/indian-addresses-gold (Apache-2.0), 4,834 bare address
strings with character spans. 99.8% of its labels were reviewed by an
LLM, not a human, so treat them as silver rather than gold.

Bare addresses do not teach a model where an address starts and ends
inside ordinary text, and every gold address ends in a PIN code. So
each address is placed inside a sentence, and negative sentences are
added that mention cities, states and 6-digit numbers without being
addresses.

Output: data/indian_address/{train,dev,test}.jsonl, one example per line:
    {"text": ..., "spans": [{"start", "end", "label"}],
     "address": [start, end] or null, "source": ...}

Run: python -m pii_pipeline.detection.address_data
"""

import json
import random
from pathlib import Path

import pandas as pd


GOLD = Path("data/indian-addresses-gold/data/gold_addresses.parquet")
OUT = Path("data/indian_address")

# Gold field -> label of the shiprocket-ai address models (ModernBERT and
# TinyBERT share the same 11 types). They have no district/village type,
# so each maps to the nearest type. All of them end up inside one
# ADDRESS span anyway.
LABEL_MAP = {
    "houseNumber": "house_details",
    "houseName": "building_name",
    "poi": "landmarks",
    "street": "road",
    "subsubLocality": "sub_locality",
    "subLocality": "sub_locality",
    "locality": "locality",
    "village": "locality",
    "subDistrict": "city",
    "district": "city",
    "city": "city",
    "state": "state",
    "pincode": "pincode",
}

# Test sentences use templates never seen in training, so a high score
# cannot come from memorising the surrounding words.
TRAIN_CONTEXTS = [
    "{}",
    "Please ship the order to {} by Friday.",
    "Registered office: {}",
    "Kindly update my communication address to {} in your records.",
    "The customer said she lives at {} and asked for a callback.",
    "Bill To: {}\nGSTIN verification is pending.",
    "Address of the branch - {}. Working hours are 10 AM to 4 PM.",
    "Delivery attempted at {} but the premises were locked.",
    "He shifted last month and now stays at {}.",
    "Correspondence address\n{}\nPhone: on file",
]
TEST_CONTEXTS = [
    "{}",
    "Send the signed agreement to our office at {} before the 15th.",
    "As per KYC records, the account holder resides at {}.",
    "Pickup location: {}. Contact the security desk on arrival.",
    "The tenant vacated the flat at {} on 3 March.",
]

# Non-address sentences. {city}/{state}/{place} come from the gold data so
# negatives use the same vocabulary as positives.
NEGATIVES = [
    "Our {city} office will be closed on Monday for maintenance.",
    "Sales in {state} grew by 12% last quarter.",
    "Ticket {num} was resolved by the {city} support team.",
    "The meeting moved from {city} to {city2} because of the weather.",
    "Invoice total: Rs. {num} payable within 30 days.",
    "She grew up in {state} and now works remotely.",
    "The {place} project review is scheduled for next week.",
    "Reference number {num} has been assigned to your complaint.",
    "We are hiring engineers in {city} and {city2}.",
    "The festival in {place} draws large crowds every year.",
    "Order #{num} shipped on 12 June and arrives in 3 days.",
    "Temperatures in {city} touched 41 degrees on Tuesday.",
]
NEGATIVE_RATIO = 0.4   # negatives per positive in each split


def gold_records(df: pd.DataFrame) -> list[dict]:
    """
    Convert gold rows to {"text", "spans", "source"} with mapped labels.

    Gold spans may overlap (the same words tagged village and poi), but
    BIO tags allow one label per word, so the longest span wins.
    Duplicate addresses are kept once.
    """
    records, seen = [], set()
    for row in df.itertuples():
        text = row.raw_address
        if text in seen:
            continue
        seen.add(text)

        kept = []
        for s in sorted(row.spans, key=lambda s: (s["start"] - s["end"], s["start"])):
            if any(s["start"] < k["end"] and k["start"] < s["end"] for k in kept):
                continue
            kept.append({"start": int(s["start"]), "end": int(s["end"]),
                         "label": LABEL_MAP[s["label"]]})
        kept.sort(key=lambda s: s["start"])
        records.append({"text": text, "spans": kept, "source": f"gold:{row.record_id}"})
    return records


def embed(record: dict, template: str) -> dict:
    """Place an address inside a sentence and shift its spans to match."""
    offset = template.index("{}")
    text = template.replace("{}", record["text"], 1)
    spans = [{**s, "start": s["start"] + offset, "end": s["end"] + offset}
             for s in record["spans"]]
    return {"text": text, "spans": spans,
            "address": [offset, offset + len(record["text"])],
            "source": record["source"]}


def negatives(records: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Make n sentences that mention places and numbers but no address."""
    names = {"city": [], "state": [], "place": []}
    for r in records:
        for s in r["spans"]:
            word = r["text"][s["start"]:s["end"]]
            if s["label"] == "city":
                names["city"].append(word)
            elif s["label"] == "state" and len(word) > 3:   # skip codes like "AS"
                names["state"].append(word)
            elif s["label"] in ("locality", "sub_locality"):
                names["place"].append(word)

    out = []
    for _ in range(n):
        text = rng.choice(NEGATIVES).format(
            city=rng.choice(names["city"]).title(),
            city2=rng.choice(names["city"]).title(),
            state=rng.choice(names["state"]).title(),
            place=rng.choice(names["place"]).title(),
            num=rng.randint(100000, 999999),   # same shape as a PIN code
        )
        out.append({"text": text, "spans": [], "address": None, "source": "negative"})
    return out


def build(df: pd.DataFrame, seed: int = 13) -> dict[str, list[dict]]:
    """Split addresses 80/10/10, then add context and negatives per split."""
    rng = random.Random(seed)
    records = gold_records(df)
    rng.shuffle(records)

    n = len(records)
    parts = {
        "train": records[: int(n * 0.8)],
        "dev": records[int(n * 0.8): int(n * 0.9)],
        "test": records[int(n * 0.9):],
    }

    splits = {}
    for name, part in parts.items():
        contexts = TRAIN_CONTEXTS if name == "train" else TEST_CONTEXTS
        examples = [embed(r, rng.choice(contexts)) for r in part]
        # Negatives draw names only from this split, so test vocabulary
        # never leaks into training.
        examples += negatives(part, int(len(part) * NEGATIVE_RATIO), rng)
        rng.shuffle(examples)
        splits[name] = examples
    return splits


def main() -> None:
    splits = build(pd.read_parquet(GOLD))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, examples in splits.items():
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for example in examples:
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
        positives = sum(e["address"] is not None for e in examples)
        print(f"{name}: {len(examples)} examples ({positives} addresses)")


if __name__ == "__main__":
    main()
