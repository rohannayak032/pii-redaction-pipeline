"""Tests for Indian address data building and component merging (no model needed)."""

import random

import pandas as pd

from pii_pipeline.detection.address_data import build, embed, gold_records, negatives
from pii_pipeline.detection.address_eval import score
from pii_pipeline.detection.detector_address import merge_components


ADDRESS = "12, MG Road, Koramangala, Bengaluru, Karnataka 560034"


def span(text, part, label):
    start = text.index(part)
    return {"start": start, "end": start + len(part), "label": label}


def gold_frame(n=20):
    rows = []
    for i in range(n):
        text = ADDRESS.replace("12", str(i + 10))
        rows.append({
            "record_id": f"r{i}",
            "raw_address": text,
            "spans": [
                span(text, str(i + 10), "houseNumber"),
                span(text, "MG Road", "street"),
                span(text, "Koramangala", "locality"),
                span(text, "Koramangala", "poi"),   # overlaps: longest/first wins
                span(text, "Bengaluru", "city"),
                span(text, "Karnataka", "state"),
                span(text, "560034", "pincode"),
            ],
        })
    return pd.DataFrame(rows)


def test_gold_records_maps_labels_and_drops_overlaps():
    record = gold_records(gold_frame(1))[0]
    labels = [s["label"] for s in record["spans"]]
    assert labels == ["house_details", "road", "locality", "city", "state", "pincode"]


def test_gold_records_drops_duplicate_addresses():
    df = pd.concat([gold_frame(1), gold_frame(1)])
    assert len(gold_records(df)) == 1


def test_embed_shifts_spans_to_the_same_words():
    record = gold_records(gold_frame(1))[0]
    example = embed(record, "Please ship the order to {} by Friday.")
    s, e = example["address"]
    assert example["text"][s:e] == record["text"]
    for old, new in zip(record["spans"], example["spans"]):
        assert example["text"][new["start"]:new["end"]] == record["text"][old["start"]:old["end"]]


def test_negatives_have_no_address():
    records = gold_records(gold_frame(5))
    for n in negatives(records, 10, random.Random(0)):
        assert n["spans"] == [] and n["address"] is None


def test_build_keeps_splits_disjoint():
    splits = build(gold_frame(50))
    sources = {name: {e["source"] for e in ex if e["address"]} for name, ex in splits.items()}
    assert not sources["train"] & sources["test"]
    assert not sources["train"] & sources["dev"]
    assert sum(len(s) for s in sources.values()) == 50


def test_merge_joins_neighbouring_components():
    text = "Ship to 12, MG Road, Bengaluru 560034 today."
    comps = [
        {**span(text, "12", "house_details"), "score": 0.9},
        {**span(text, "MG Road", "road"), "score": 0.9},
        {**span(text, "Bengaluru", "city"), "score": 0.9},
        {**span(text, "560034", "pincode"), "score": 0.9},
    ]
    [(start, end, _)] = merge_components(text, comps)
    assert text[start:end] == "12, MG Road, Bengaluru 560034"


def test_merge_drops_lone_city():
    text = "Our Pune office is closed."
    comps = [{**span(text, "Pune", "city"), "score": 0.99}]
    assert merge_components(text, comps) == []


def test_merge_splits_distant_components():
    text = "Bengaluru 560034 is far from here. Much later we visited Chennai, Tamil Nadu."
    comps = [
        {**span(text, "Bengaluru", "city"), "score": 0.9},
        {**span(text, "560034", "pincode"), "score": 0.9},
        {**span(text, "Chennai", "city"), "score": 0.9},
        {**span(text, "Tamil Nadu", "state"), "score": 0.9},
    ]
    assert len(merge_components(text, comps)) == 2


def test_score_counts_leaks_and_false_positives():
    examples = [
        {"text": "At 12 MG Road.", "address": [3, 13]},
        {"text": "At 12 MG Road.", "address": [3, 13]},
        {"text": "Pune is hot.", "address": None},
    ]
    # full cover, cover missing "12", a false positive on the negative
    result = score(examples, [[(3, 13)], [(6, 13)], [(0, 4)]])
    assert result["complete_recall"] == 0.5
    assert result["false_positive_rate"] == 1.0
