"""Command line: check extraction on your own machine without exposing text.

    python -m pii_pipeline.extraction FILE [FILE ...]                 # summary only
    python -m pii_pipeline.extraction FILE --out data/extracted/x.jsonl

The summary prints counts, warning codes and locations, never document text.
``--out`` writes the full text and must point inside a ``data/`` folder, which
is git-ignored. Never paste that output into chats, tickets or AI tools.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path

from . import ExtractionError, extract_document_detailed


def _summary(result) -> list[str]:
    kinds = Counter(m.kind for m in result.meta)
    ocr = [b.ocr_confidence for b in result.blocks if b.ocr_confidence is not None]
    lines = [f"{result.file}: {len(result.blocks)} blocks"]
    lines += [f"  {kind:<14} {count}" for kind, count in sorted(kinds.items())]
    if ocr:
        lines.append(f"  OCR blocks: {len(ocr)}, mean confidence {sum(ocr) / len(ocr):.2f}, lowest {min(ocr):.2f}")
    for warning in result.warnings:
        lines.append(f"  WARNING {warning}")
    return lines


def _inside_data_dir(path: Path) -> bool:
    return any(part.lower() == "data" for part in path.resolve().parent.parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pii_pipeline.extraction", description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, help="JSONL file for the full text (must be inside a data/ folder)")
    args = parser.parse_args(argv)

    if args.out is not None and not _inside_data_dir(args.out):
        parser.error("--out must be inside a 'data/' folder (git-ignored), e.g. data/extracted/out.jsonl")

    records = []
    status = 0
    for path in args.files:
        try:
            result = extract_document_detailed(path)
        except ExtractionError as exc:
            print(f"{path.name}: ERROR {exc}", file=sys.stderr)
            status = 1
            continue
        print("\n".join(_summary(result)))
        for block, meta in zip(result.blocks, result.meta):
            records.append({"block": dataclasses.asdict(block), "meta": dataclasses.asdict(meta)})

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Full text written to {args.out} (git-ignored; do not share).")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
