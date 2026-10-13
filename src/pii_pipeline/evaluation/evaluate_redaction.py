"""Evaluate a PII redaction pipeline against a ground-truth CSV.

The evaluator answers two questions for every ground-truth entity:

1. Was it *detected*?  A predicted entity must have the same ``file``, the
   same PII type and a matching value (equal, or one containing the other).
   Offsets are not compared: the ground truth has no ``block_index`` and its
   offsets are not in extraction's block coordinates. Overlapping predictions
   are first merged the way redaction merges them, so each replaced span
   counts once.
2. Was it really *redacted*?  The original value must no longer appear in the
   text of the ``RedactedBlock`` objects returned by ``redact_document``.

Definitions (entity level)
--------------------------
TP : ground-truth entity that was detected AND whose value is gone from the
     redacted output.
FN : ground-truth entity that was missed, mis-typed, or detected but still
     visible (leaked) in the redacted output.
FP : predicted entity that matches no ground-truth entity (over-redaction).

Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2PR / (P + R)
Accuracy  = TP / (TP + FP + FN)
            There are no "true negatives" in entity-level evaluation, so
            accuracy is defined as the share of all entities (truth or
            predicted) that the system got right.

Run ``python evaluate_redaction.py --selftest`` for the built-in tests, or
``python evaluate_redaction.py --demo --gt ground_truth.csv`` for a demo.
To score the real pipeline (prints only the metrics table)::

    python -m pii_pipeline.evaluation.evaluate_redaction --gt GT.csv --docs A.pdf B.docx [--diagnose]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

REQUIRED_COLUMNS: Tuple[str, ...] = (
    "file", "case_id", "type", "value", "location", "start", "end",
)

# Map common detector labels onto the labels used in the ground truth.
TYPE_ALIASES: Dict[str, str] = {
    "PERSON": "NAME",
    "PER": "NAME",
    "FULL_NAME": "NAME",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "MOBILE": "PHONE",
    "AADHAR": "AADHAAR",
    "AADHAAR_NUMBER": "AADHAAR",
    "PAN_NUMBER": "PAN",
    "CREDIT_CARD": "CARD",
    "CARD_NUMBER": "CARD",
    "DATE_OF_BIRTH": "DOB",
    "IP_ADDRESS": "IP",
    "BANK_ACCOUNT": "ACCOUNT",
    "ACCOUNT_NUMBER": "ACCOUNT",
    "PASSPORT_NUMBER": "PASSPORT",
    "DIRECTOR_ID": "EMPLOYEE_ID",   # the Cadence ground truth labels DIR- IDs as EMPLOYEE_ID
}

_TEXT_ATTRS: Tuple[str, ...] = ("redacted_text", "text", "content")


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Span:
    """A PII span used internally for matching."""

    file: str
    pii_type: str
    start: Optional[int]
    end: Optional[int]
    value: str
    case_id: str = ""
    location: str = ""

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "file": self.file, "case_id": self.case_id, "type": self.pii_type,
            "start": self.start, "end": self.end, "value": self.value,
        }


def normalize_type(raw: Any) -> str:
    """Upper-case a PII type label and resolve known aliases."""
    label = str(raw).strip().upper().replace(" ", "_")
    return TYPE_ALIASES.get(label, label)


def load_ground_truth(ground_truth_csv: str) -> List[Span]:
    """Load the ground-truth CSV into a list of :class:`Span`.

    Raises:
        ValueError: if required columns are missing or offsets are invalid.
    """
    df = pd.read_csv(ground_truth_csv, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Ground-truth CSV is missing columns: {missing}")

    spans: List[Span] = []
    for row in df.itertuples(index=False):
        pii_type = normalize_type(row.type)
        if pii_type == "NONE":
            # Negative test case: the file must contain no PII. Nothing to
            # match here; any prediction in that file becomes a false positive.
            continue
        start_raw, end_raw = str(row.start).strip(), str(row.end).strip()
        start: Optional[int] = None
        end: Optional[int] = None
        if start_raw or end_raw:
            try:
                start, end = int(float(start_raw)), int(float(end_raw))
            except ValueError as exc:
                raise ValueError(f"Non-integer offsets in row: {row}") from exc
            if end <= start:
                raise ValueError(f"end must be > start in row: {row}")
        # Rows without offsets are matched by file + type + value instead.
        spans.append(Span(str(row.file), pii_type, start, end,
                          str(row.value), str(row.case_id), str(row.location)))
    return spans


def in_split(file: str, location: str, split: Optional[str]) -> bool:
    """Dev/test split: dev = every non-PDF file plus PDF odd pages, test = PDF even pages.

    Works for both ground-truth locations ("page 3 figure") and extraction
    locations ("page 3, paragraph 2 (OCR)").
    """
    if split is None:
        return True
    page = re.match(r"page (\d+)", location) if file.lower().endswith(".pdf") else None
    if page is None:
        return split == "dev"
    return (int(page.group(1)) % 2 == 1) == (split == "dev")


def entities_to_spans(entities: Sequence[Any]) -> List[Span]:
    """Convert pipeline ``Entity`` objects (duck-typed) into spans."""
    return [
        Span(str(e.file), normalize_type(e.pii_type),
             int(e.start), int(e.end), str(getattr(e, "value", "")))
        for e in entities
    ]


def merge_overlaps(entities: Sequence[Any]) -> List[Any]:
    """Collapse overlapping predictions per block the way redaction does.

    The merged span takes the winner's type (redaction's ``resolve_overlaps``)
    and its value is rebuilt from the members, which cover the union.
    """
    from pii_pipeline.redaction import resolve_overlaps

    by_block: Dict[Tuple[str, int], List[Any]] = defaultdict(list)
    for e in entities:
        by_block[(e.file, e.block_index)].append(e)
    merged: List[Any] = []
    for (file, block_index), group in by_block.items():
        chars = {e.start + i: ch for e in group for i, ch in enumerate(e.value)}
        for s in resolve_overlaps(group):
            merged.append(SimpleNamespace(
                file=file, block_index=block_index, start=s.start, end=s.end,
                pii_type=s.pii_type,
                value="".join(chars[i] for i in range(s.start, s.end))))
    return merged


def _overlap_ratio(a: Span, b: Span) -> float:
    """Value overlap: len(shorter) / len(longer) if one contains the other.

    Values are compared on letters and digits only, lower-cased, so OCR slips
    in spacing and punctuation ("+44 20 75550163", "tlindqvist@...") still
    match. For nested spans this equals their intersection-over-union,
    without needing offsets in the same coordinates.
    """
    x, y = sorted((_alnum(a.value), _alnum(b.value)), key=len)
    if x and x in y:
        return len(x) / len(y)
    # One OCR-misread letter in a name or email ("a.chatteree@...",
    # "cadencetg.com"). Values with digits (IDs, phones, PAN) must match
    # exactly: one changed digit is another person.
    if len(x) >= 8 and not any(c.isdigit() for c in x + y):
        ratio = difflib.SequenceMatcher(None, x, y).ratio()
        if ratio >= 0.9:
            return ratio
    return 0.0


def _alnum(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


def _squash(text: str) -> str:
    """Collapse all whitespace runs (incl. line breaks) to single spaces."""
    return " ".join(text.split())


def _safe_div(num: float, den: float) -> float:
    """Division that returns 0.0 when the denominator is zero."""
    return num / den if den else 0.0


def _metrics(tp: int, fp: int, fn: int) -> Dict[str, float]:
    """Compute precision / recall / F1 / accuracy from raw counts."""
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    return {
        "tp": tp, "fp": fp, "fn": fn, "support": tp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_safe_div(2 * precision * recall, precision + recall), 4),
        "accuracy": round(_safe_div(tp, tp + fp + fn), 4),
    }


def _collect_redacted_text(
    redacted_blocks: Sequence[Any],
) -> Tuple[Dict[Optional[str], str], bool]:
    """Join redacted text per file. Returns (texts, text_was_found)."""
    texts: Dict[Optional[str], List[str]] = defaultdict(list)
    found = False
    for block in redacted_blocks:
        for attr in _TEXT_ATTRS:
            value = getattr(block, attr, None)
            if isinstance(value, str):
                texts[getattr(block, "file", None)].append(value)
                found = True
                break
    return {k: "\n".join(v) for k, v in texts.items()}, found


# --------------------------------------------------------------------------- #
# Main evaluation function
# --------------------------------------------------------------------------- #
def evaluate_redaction(
    ground_truth_csv: str,
    predicted_entities: Sequence[Any],
    redacted_blocks: Sequence[Any],
    iou_threshold: float = 0.5,
    require_type_match: bool = True,
    check_redaction: bool = True,
    split: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a PII redaction pipeline against ground truth.

    Args:
        ground_truth_csv: Path to CSV with columns ``file, case_id, type,
            value, location, start, end``.
        predicted_entities: Entities passed to / produced for
            ``redact_document`` (need ``file, start, end, pii_type, value``).
        redacted_blocks: Output blocks of ``redact_document``. Each should
            expose ``file`` and the redacted text (``text``/``redacted_text``).
        iou_threshold: Minimum overlap (0-1] for a prediction to count as
            matching a ground-truth value. Use ``1.0`` for exact values.
        require_type_match: If True, PII types must agree to match.
        check_redaction: If True, a detected value that still appears in the
            redacted text is counted as a miss (FN), not a TP.

    Returns:
        A dict with ``overall`` and ``per_type`` metrics, plus ``details``
        (missed, leaked and false-positive entities) and ``warnings``.
    """
    if not 0.0 < iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be in (0, 1].")

    truth = load_ground_truth(ground_truth_csv)
    preds = entities_to_spans(merge_overlaps(predicted_entities))
    warnings: List[str] = []

    # Score only files that were run, so a held-out document is not counted as missed.
    truth = [g for g in truth if in_split(g.file, g.location, split)]
    run_files = {getattr(b, "file", None) for b in redacted_blocks}
    if run_files:
        skipped = sum(g.file not in run_files for g in truth)
        truth = [g for g in truth if g.file in run_files]
        if skipped:
            warnings.append(f"{skipped} ground-truth rows skipped: their files were not run.")

    texts, text_found = _collect_redacted_text(redacted_blocks)
    leak_check = check_redaction and text_found
    if check_redaction and not text_found:
        warnings.append(
            "No redacted text found on redacted_blocks; leak check skipped "
            "(detection-only scoring)."
        )

    # ---- greedy one-to-one matching, best overlap first, per file --------
    candidates: List[Tuple[float, int, int]] = []
    for gi, g in enumerate(truth):
        for pi, p in enumerate(preds):
            if g.file != p.file:
                continue
            if require_type_match and g.pii_type != p.pii_type:
                continue
            ratio = _overlap_ratio(g, p)
            if ratio >= iou_threshold:
                candidates.append((ratio, gi, pi))
    candidates.sort(key=lambda c: -c[0])

    gt_to_pred: Dict[int, int] = {}
    used_preds: set = set()
    for _, gi, pi in candidates:
        if gi not in gt_to_pred and pi not in used_preds:
            gt_to_pred[gi] = pi
            used_preds.add(pi)

    # ---- classify -------------------------------------------------------
    counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0})
    missed: List[Dict[str, Any]] = []
    leaked: List[Dict[str, Any]] = []
    false_pos: List[Dict[str, Any]] = []

    for gi, g in enumerate(truth):
        if gi not in gt_to_pred:
            counts[g.pii_type]["fn"] += 1
            missed.append(g.as_dict())
            continue
        if leak_check:
            haystack = _squash(texts.get(g.file, "") + "\n" + texts.get(None, ""))
            if g.value and _squash(g.value) in haystack:
                counts[g.pii_type]["fn"] += 1
                leaked.append(g.as_dict())
                continue
        counts[g.pii_type]["tp"] += 1

    # A detection that repeats a labelled value in the same file is PII the
    # ground truth labelled only once (e.g. once per slide), not over-redaction.
    repeats = 0
    for pi, p in enumerate(preds):
        if pi in used_preds:
            continue
        if any(g.file == p.file and (not require_type_match or g.pii_type == p.pii_type)
               and _overlap_ratio(g, p) >= iou_threshold for g in truth):
            repeats += 1
            continue
        counts[p.pii_type]["fp"] += 1
        false_pos.append(p.as_dict())

    tp = sum(c["tp"] for c in counts.values())
    fp = sum(c["fp"] for c in counts.values())
    fn = sum(c["fn"] for c in counts.values())

    return {
        "overall": _metrics(tp, fp, fn),
        "per_type": {t: _metrics(c["tp"], c["fp"], c["fn"])
                     for t, c in sorted(counts.items())},
        "details": {"missed": missed, "leaked": leaked,
                    "false_positives": false_pos},
        "repeats": repeats,
        "warnings": warnings,
    }


def format_report(result: Dict[str, Any]) -> str:
    """Render the result of :func:`evaluate_redaction` as a text table."""
    header = (f"{'TYPE':<10}{'TP':>5}{'FP':>5}{'FN':>5}"
              f"{'Prec':>8}{'Recall':>8}{'F1':>8}{'Acc':>8}")
    lines = [header, "-" * len(header)]

    def row(name: str, m: Dict[str, float]) -> str:
        return (f"{name:<10}{m['tp']:>5}{m['fp']:>5}{m['fn']:>5}"
                f"{m['precision']:>8.3f}{m['recall']:>8.3f}"
                f"{m['f1']:>8.3f}{m['accuracy']:>8.3f}")

    for name, m in result["per_type"].items():
        lines.append(row(name, m))
    lines.append("-" * len(header))
    lines.append(row("OVERALL", result["overall"]))
    d = result["details"]
    lines.append(f"\nMissed: {len(d['missed'])} | Leaked: {len(d['leaked'])} "
                 f"| False positives: {len(d['false_positives'])} "
                 f"| Repeats of labelled values (not FP): {result.get('repeats', 0)}")
    for w in result["warnings"]:
        lines.append(f"WARNING: {w}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Tests (run with `pytest evaluate_redaction.py` or `--selftest`)
# --------------------------------------------------------------------------- #
def _entity(file: str, t: str, start: int, end: int, value: str, block: int = 0) -> Any:
    """Minimal stand-in for the pipeline's Entity (see make_entity)."""
    return SimpleNamespace(file=file, block_index=block, start=start, end=end,
                           pii_type=t, confidence=0.95, detector="test",
                           value=value)


def _block(file: str, text: str) -> Any:
    """Minimal stand-in for RedactedBlock."""
    return SimpleNamespace(file=file, index=0, text=text)


def _write_gt(tmp_path: Any) -> str:
    path = str(tmp_path / "gt.csv")
    pd.DataFrame(
        [
            ["a.txt", "T1", "EMAIL", "bob@x.com", "paragraph", 0, 9],
            ["a.txt", "T1", "PHONE", "9876543210", "paragraph", 20, 30],
        ],
        columns=list(REQUIRED_COLUMNS),
    ).to_csv(path, index=False)
    return path


def test_perfect(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com"),
             _entity("a.txt", "PHONE", 20, 30, "9876543210")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[EMAIL_1] [PHONE_1]")])
    assert out["overall"]["f1"] == 1.0 and out["overall"]["accuracy"] == 1.0


def test_missed_entity(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[EMAIL_1] 9876543210")])
    assert out["overall"]["recall"] == 0.5 and out["overall"]["precision"] == 1.0
    assert out["per_type"]["PHONE"]["fn"] == 1


def test_false_positive(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com"),
             _entity("a.txt", "PHONE", 20, 30, "9876543210"),
             _entity("a.txt", "NAME", 40, 45, "Alice")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[E] [P] [N]")])
    assert out["overall"]["fp"] == 1 and out["overall"]["precision"] < 1.0


def test_leak_counts_as_miss(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com"),
             _entity("a.txt", "PHONE", 20, 30, "9876543210")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[E] 9876543210")])
    assert out["overall"]["tp"] == 1 and len(out["details"]["leaked"]) == 1


def test_wrong_type_is_fn_and_fp(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "NAME", 0, 9, "bob@x.com"),
             _entity("a.txt", "PHONE", 20, 30, "9876543210")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[N] [P]")])
    assert out["per_type"]["EMAIL"]["fn"] == 1
    assert out["per_type"]["NAME"]["fp"] == 1


def test_alias_and_partial_overlap(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL_ADDRESS", 0, 8, "bob@x.co"),
             _entity("a.txt", "PHONE_NUMBER", 20, 30, "9876543210")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[E] [P]")])
    assert out["overall"]["tp"] == 2
    exact = evaluate_redaction(gt, preds, [_block("a.txt", "[E] [P]")],
                               iou_threshold=1.0)
    assert exact["overall"]["tp"] == 1


def test_none_rows_and_missing_offsets(tmp_path: Any) -> None:
    path = str(tmp_path / "gt2.csv")
    pd.DataFrame(
        [
            ["neg.docx", "N1", "NONE", "", "paragraph", "", ""],
            ["pg.pdf", "P1", "AADHAAR", "2345 6789 0123", "page break", "", ""],
        ],
        columns=list(REQUIRED_COLUMNS),
    ).to_csv(path, index=False)
    # Offsetless GT matches by value; the entity in the NONE file is an FP.
    preds = [_entity("pg.pdf", "AADHAAR", 3, 17, "2345 6789 0123"),
             _entity("neg.docx", "NAME", 0, 4, "Rahul")]
    blocks = [_block("pg.pdf", "[AADHAAR_1]"), _block("neg.docx", "[NAME_1]")]
    out = evaluate_redaction(path, preds, blocks)
    assert out["overall"]["tp"] == 1 and out["overall"]["fp"] == 1
    assert out["overall"]["fn"] == 0


def test_ground_truth_offsets_are_not_block_offsets(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 100, 109, "bob@x.com", block=3),
             _entity("a.txt", "PHONE", 5, 15, "9876543210", block=7)]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[E] [P]")])
    assert out["overall"]["tp"] == 2 and out["overall"]["fp"] == 0


def test_overlapping_predictions_count_once(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com"),
             _entity("a.txt", "NAME", 0, 3, "bob"),
             _entity("a.txt", "PHONE", 20, 30, "9876543210")]
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[EMAIL_1] [PHONE_1]")])
    assert out["overall"]["tp"] == 2 and out["overall"]["fp"] == 0


def test_files_that_were_not_run_are_skipped(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    out = evaluate_redaction(gt, [], [_block("b.txt", "nothing here")])
    assert out["overall"]["fn"] == 0 and len(out["warnings"]) == 1


def test_diagnose_shows_shapes_not_values(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    blocks = [SimpleNamespace(file="a.txt", index=0, text="bob@x.com 9876543210 Alice")]
    preds = [_entity("a.txt", "EMAIL", 0, 9, "bob@x.com"),
             _entity("a.txt", "NAME", 21, 26, "Alice")]
    result = evaluate_redaction(gt, preds, [_block("a.txt", "[E] 9876543210 [N]")])
    report = diagnose(result, blocks, preds)
    assert "9999999999" in report and "not detected" in report
    assert not any(v in report for v in ("bob@x.com", "9876543210", "Alice"))


def test_ocr_spacing_matches_and_repeats_are_not_fp(tmp_path: Any) -> None:
    gt = _write_gt(tmp_path)
    preds = [_entity("a.txt", "EMAIL", 0, 8, "bobx.com"),              # OCR dropped "@"
             _entity("a.txt", "PHONE", 20, 31, "98765 43210"),          # OCR added a space
             _entity("a.txt", "EMAIL", 0, 9, "bob@x.com", block=1)]     # same value again
    out = evaluate_redaction(gt, preds, [_block("a.txt", "[E] [P] [E]")])
    assert out["overall"]["tp"] == 2 and out["overall"]["fp"] == 0 and out["repeats"] == 1


def test_one_misread_letter_matches_but_one_digit_does_not(tmp_path: Any) -> None:
    path = str(tmp_path / "gt4.csv")
    pd.DataFrame([["a.txt", "T", "EMAIL", "a.chatterjee@cadencefg.com", "p", "", ""],
                  ["a.txt", "T", "PHONE", "+44 20 7555 0171", "p", "", ""]],
                 columns=list(REQUIRED_COLUMNS)).to_csv(path, index=False)
    preds = [_entity("a.txt", "EMAIL", 0, 25, "a.chatteree@cadencefg.com"),
             _entity("a.txt", "PHONE", 30, 46, "+44 20 7555 0172")]
    out = evaluate_redaction(path, preds, [_block("a.txt", "[E] [P]")])
    assert out["per_type"]["EMAIL"]["tp"] == 1 and out["per_type"]["PHONE"]["fp"] == 1


def test_director_ids_score_as_employee_ids(tmp_path: Any) -> None:
    path = str(tmp_path / "gt3.csv")
    pd.DataFrame([["a.txt", "T", "EMPLOYEE_ID", "DIR-0042", "page 1", "", ""]],
                 columns=list(REQUIRED_COLUMNS)).to_csv(path, index=False)
    out = evaluate_redaction(path, [_entity("a.txt", "DIRECTOR_ID", 0, 8, "DIR-0042")],
                             [_block("a.txt", "[DIRECTOR_ID_1]")])
    assert out["overall"]["tp"] == 1


def test_dev_test_split_by_pdf_page(tmp_path: Any) -> None:
    assert in_split("d.pdf", "page 3 figure", "dev") and not in_split("d.pdf", "page 3, paragraph 1 (OCR)", "test")
    assert in_split("d.pdf", "page 4", "test") and not in_split("d.pdf", "page 4", "dev")
    assert in_split("d.docx", "page 4", "dev") and not in_split("d.pptx", "slide 2", "test")
    assert in_split("d.pdf", "document properties", "dev") and in_split("d.pdf", "page 4", None)


def _run_selftests() -> int:
    import tempfile
    from pathlib import Path

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                print(f"PASS {fn.__name__}")
            except AssertionError:
                failed += 1
                print(f"FAIL {fn.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# Demo: simulate a pipeline from the ground truth file
# --------------------------------------------------------------------------- #
def _demo(gt_path: str) -> None:
    """Fake a pipeline: miss every 10th entity, leak every 15th, add noise."""
    truth = load_ground_truth(gt_path)
    preds: List[Any] = []
    leaked_values: Dict[str, List[str]] = defaultdict(list)
    for i, g in enumerate(truth):
        if i % 10 == 9:
            continue  # missed entirely
        start = g.start if g.start is not None else 0
        end = g.end if g.end is not None else len(g.value)
        preds.append(_entity(g.file, g.pii_type, start, end, g.value, block=i))
        if i % 15 == 14:
            leaked_values[g.file].append(g.value)  # detected but not removed
    for f in sorted({g.file for g in truth})[:3]:
        preds.append(_entity(f, "NAME", 500, 505, "Noise"))  # false alarms

    files = sorted({g.file for g in truth})
    blocks = [_block(f, "[REDACTED] " + " ".join(leaked_values.get(f, [])))
              for f in files]
    print(format_report(evaluate_redaction(gt_path, preds, blocks)))


def run_pipeline(gt_path: str, docs: Sequence[str],
                 split: Optional[str] = None) -> Tuple[Dict[str, Any], list, list]:
    """Extract, detect and redact ``docs``, then score them.

    File names must match the CSV's ``file`` column. A ``.jsonl`` doc is read
    as blocks already saved by the extraction CLI. Returns the result plus
    the blocks and entities, for :func:`diagnose`.
    """
    from pii_pipeline.detection.detector import detect
    from pii_pipeline.extraction import extract_document
    from pii_pipeline.redaction import redact_document

    from pii_pipeline.schemas import TextBlock

    def load(doc: str) -> list:
        # Blocks saved by `python -m pii_pipeline.extraction FILE --out x.jsonl` skip slow OCR.
        if str(doc).endswith(".jsonl"):
            with open(doc, encoding="utf-8") as handle:
                return [TextBlock(**json.loads(line)["block"]) for line in handle]
        return extract_document(doc)

    blocks = [b for doc in docs for b in load(doc) if in_split(b.file, b.location, split)]
    entities = detect(blocks)
    redacted, _ = redact_document(blocks, entities)
    return evaluate_redaction(gt_path, entities, redacted, split=split), blocks, entities


def _shape(value: str) -> str:
    """A value's format without its content: "EMP-12 x" -> "AAA-99 a"."""
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", _squash(value))))[:40]


def diagnose(result: Dict[str, Any], blocks: Sequence[Any], entities: Sequence[Any],
             show_values: bool = False) -> str:
    """Why ground truth was missed and what false positives look like.

    By default shows only counts and value shapes, never values, so it is safe
    to share. ``show_values`` adds the actual values for local tuning only.
    """
    text: Dict[str, str] = defaultdict(str)
    for b in blocks:
        text[b.file] += "\n" + _squash(b.text)
    preds = entities_to_spans(merge_overlaps(entities))
    causes: Counter = Counter()
    shapes: Dict[str, Counter] = defaultdict(Counter)
    for m in result["details"]["missed"]:
        v, f, t = _squash(m["value"]), m["file"], m["type"]
        if v not in text[f]:
            cause = "not in extracted text"
        elif any(p.file == f and p.value and (v in _squash(p.value) or _squash(p.value) in v)
                 for p in preds):
            cause = "found, wrong type or span"
        else:
            cause = "not detected"
        causes[(t, cause)] += 1
        if t != "NAME":
            shapes[t][_shape(v)] += 1
    details = result["details"]
    fps = details["false_positives"]
    lines = ["MISSED by cause:"]
    lines += [f"  {t:<12} {c:<27} {n}" for (t, c), n in sorted(causes.items())]
    lines.append("MISSED value shapes (non-NAME):")
    lines += [f"  {t}: {dict(c.most_common(8))}" for t, c in sorted(shapes.items())]
    lines.append(f"LEAKED by type: {dict(Counter(m['type'] for m in details['leaked']))}")
    lines.append(f"FALSE POSITIVES by type: {dict(Counter(p['type'] for p in fps))}")
    lines.append("FP shapes (non-NAME): "
                 f"{dict(Counter((p['type'], _shape(p['value'])) for p in fps if p['type'] != 'NAME').most_common(10))}")
    lines.append("NAME FP word counts: "
                 f"{dict(sorted(Counter(len(p['value'].split()) for p in fps if p['type'] == 'NAME').items()))}")
    lines.append("RAW detections by type/detector: "
                 f"{dict(Counter((e.pii_type, e.detector.split(':')[0]) for e in entities))}")
    if show_values:
        lines.append("\nLOCAL ONLY - contains document values, never share:")
        for t in sorted({p["type"] for p in fps}):
            top = Counter(_squash(p["value"]) for p in fps if p["type"] == t).most_common(40)
            lines.append(f"FP {t}: {top}")
        for m in details["missed"]:
            v = _squash(m["value"])
            near = [f"{p.pii_type}:{p.value!r}" for p in preds if p.file == m["file"] and p.value
                    and (v in _squash(p.value) or _squash(p.value) in v)]
            lines.append(f"MISSED {m['type']} {v!r} {m['case_id']} near={near[:3]}")
        lines += [f"LEAKED {m['type']} {_squash(m['value'])!r}" for m in details["leaked"]]
    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gt", default="ground_truth.csv")
    ap.add_argument("--demo", action="store_true", help="run a simulated demo")
    ap.add_argument("--selftest", action="store_true", help="run unit tests")
    ap.add_argument("--docs", nargs="+",
                    help="run the real pipeline on these files and print the metrics table")
    ap.add_argument("--diagnose", action="store_true",
                    help="with --docs: also print miss causes and value shapes (no values)")
    ap.add_argument("--show-values", action="store_true",
                    help="with --diagnose: also list false-positive and missed VALUES (local only)")
    ap.add_argument("--split", choices=("dev", "test"),
                    help="with --docs: dev = non-PDF files + PDF odd pages, test = PDF even pages")
    args = ap.parse_args(argv)
    if args.selftest:
        return _run_selftests()
    if args.docs:
        result, blocks, entities = run_pipeline(args.gt, args.docs, args.split)
        print(format_report(result))
        if args.diagnose:
            print("\n" + diagnose(result, blocks, entities, args.show_values))
        return 0
    if args.demo:
        _demo(args.gt)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
