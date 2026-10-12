"""
Evaluate address detectors on data/indian_address/<split>.jsonl.

Reports, per detector:
- complete recall: share of addresses whose every letter/digit is inside
  a predicted ADDRESS span (nothing would leak after redaction)
- 90% recall: share with at least 90% of letters/digits covered
- false-positive rate: share of negative sentences with any ADDRESS span
- over-redaction: predicted characters outside the true address
- latency per example and peak process memory

Run one detector per call (modernbert, tinybert, gliner or a model id):
    python -m pii_pipeline.detection.address_eval modernbert [test|dev]
"""

import json
import sys
import time
from pathlib import Path

from pii_pipeline.schemas import TextBlock
from pii_pipeline.detection import detector_address

DATA = Path("data/indian_address")

MODELS = {
    "modernbert": "shiprocket-ai/open-modernbert-indian-address-ner",
    "tinybert": "shiprocket-ai/open-tinybert-indian-address-ner",
}


def _detector(name: str):
    """Return a function block -> list of (start, end) ADDRESS spans."""
    if name == "gliner":
        from pii_pipeline.detection.detector_b import detect_with_gliner
        def run(block):
            return [(e.start, e.end) for e in detect_with_gliner([block]) if e.pii_type == "ADDRESS"]
        return run

    model = MODELS.get(name, name)   # a short name or any Hugging Face id
    def run(block):
        return [(e.start, e.end) for e in detector_address.detect_indian_addresses([block], model)]
    return run


def _peak_memory_mb() -> float:
    """Peak resident memory of this process."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (f, ctypes.c_size_t) for f in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        c = Counters(cb=ctypes.sizeof(Counters))
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.WinDLL("psapi").GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / 2**20
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024   # KB on Linux


def score(examples: list[dict], predictions: list[list[tuple[int, int]]]) -> dict:
    """Compare predicted ADDRESS spans with the true address of each example."""
    complete = partial = positives = 0
    false_pos = negatives = 0
    over = 0

    for ex, spans in zip(examples, predictions):
        covered = set()
        for s, e in spans:
            covered.update(range(s, e))

        if ex["address"] is None:
            negatives += 1
            false_pos += bool(spans)
            continue

        positives += 1
        a, b = ex["address"]
        needed = {i for i in range(a, b) if ex["text"][i].isalnum()}
        share = len(needed & covered) / len(needed)
        complete += share == 1.0
        partial += share >= 0.9
        over += len({i for i in covered if not a <= i < b})

    return {
        "complete_recall": complete / positives,
        "recall_90": partial / positives,
        "false_positive_rate": false_pos / negatives if negatives else 0.0,
        "over_redacted_chars_per_address": over / positives,
    }


def evaluate(name: str, split: str = "test") -> dict:
    lines = (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
    examples = [json.loads(line) for line in lines]
    run = _detector(name)

    run(TextBlock("warmup", "-", 0, examples[0]["text"]))   # loads the model
    predictions, times = [], []
    for i, ex in enumerate(examples):
        t = time.perf_counter()
        predictions.append(run(TextBlock(f"{split}.jsonl", "line", i, ex["text"])))
        times.append(time.perf_counter() - t)

    times.sort()
    return {
        "detector": name,
        **score(examples, predictions),
        "ms_per_example": 1000 * sum(times) / len(times),
        "p95_ms": 1000 * times[int(len(times) * 0.95)],
        "peak_memory_mb": _peak_memory_mb(),
    }


if __name__ == "__main__":
    # One detector per process, so peak memory is not shared between them.
    print(json.dumps(evaluate(sys.argv[1], *sys.argv[2:3]), indent=2))
