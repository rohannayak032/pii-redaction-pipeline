"""
Fine-tune an address NER model on data/indian_address (see address_data).

Starts from the shiprocket-ai checkpoint, so its 11 component types and
classifier head are kept. Training teaches it which words around an
address are not part of it, and that most sentences hold no address.
Runs on CPU.

Run: python -m pii_pipeline.detection.address_train modernbert [epochs]
The epoch with the best dev score is saved to data/models/<model>-ft/;
evaluate it with address_eval, passing that folder as the model.
"""

import json
import math
import random
import sys
import time
from pathlib import Path

import torch
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    get_linear_schedule_with_warmup,
)

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection import detector_address
from pii_pipeline.detection.address_eval import DATA, MODELS, score

OUT = Path("data/models")   # gitignored, like the data
MAX_TOKENS = 256


def load(split: str) -> list[dict]:
    lines = (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def encode(tokenizer, example: dict, label2id: dict) -> dict:
    """Tokenize one example and give every token a BIO component label."""
    enc = tokenizer(example["text"], truncation=True, max_length=MAX_TOKENS,
                    return_offsets_mapping=True)
    labels, started = [], set()
    for start, end in enc.pop("offset_mapping"):
        if start == end:   # special tokens carry no text
            labels.append(-100)
            continue
        tag = "O"
        for i, span in enumerate(example["spans"]):
            if start < span["end"] and end > span["start"]:
                tag = ("I-" if i in started else "B-") + span["label"]
                started.add(i)
                break
        labels.append(label2id[tag])
    return {**enc, "labels": labels}


def dev_score(model, tokenizer, examples: list[dict]) -> dict:
    """Score through the real detector path: components, merging, ADDRESS spans."""
    model.eval()
    detector_address._models["training"] = detector_address.make_pipeline(model, tokenizer)
    predictions = []
    with torch.no_grad():
        for i, ex in enumerate(examples):
            found = detector_address.detect_indian_addresses(
                [TextBlock("dev.jsonl", "line", i, ex["text"])], "training")
            predictions.append([(e.start, e.end) for e in found])
    return score(examples, predictions)


def train(name: str, epochs: int = 3, lr: float = 3e-5, batch_size: int = 16, seed: int = 13) -> None:
    random.seed(seed)
    torch.manual_seed(seed)

    base = MODELS.get(name, name)
    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForTokenClassification.from_pretrained(base)
    label2id = {label: int(i) for i, label in model.config.id2label.items()}

    train_set = [encode(tokenizer, ex, label2id) for ex in load("train")]
    dev = load("dev")
    longest = max(len(ex["input_ids"]) for ex in train_set)
    print(f"{len(train_set)} training examples, longest {longest} tokens", flush=True)

    collate = DataCollatorForTokenClassification(tokenizer)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * math.ceil(len(train_set) / batch_size)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.1 * steps), steps)

    out = OUT / f"{base.rstrip('/').split('/')[-1]}-ft"
    # Both matter for redaction: leaked addresses and redacted non-addresses.
    best = -math.inf
    for epoch in range(1, epochs + 1):
        model.train()
        random.shuffle(train_set)
        started, total = time.time(), 0.0
        for i in range(0, len(train_set), batch_size):
            loss = model(**collate(train_set[i:i + batch_size])).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total += loss.item()

        result = dev_score(model, tokenizer, dev)
        combined = result["complete_recall"] - result["false_positive_rate"]
        print(f"epoch {epoch}: loss {total / math.ceil(len(train_set) / batch_size):.4f}, "
              f"{time.time() - started:.0f}s, dev {json.dumps({k: round(v, 3) for k, v in result.items()})}",
              flush=True)
        if combined > best:
            best = combined
            model.save_pretrained(out)
            tokenizer.save_pretrained(out)
            print(f"  saved to {out}", flush=True)


if __name__ == "__main__":
    train(sys.argv[1], *(int(a) for a in sys.argv[2:3]))
