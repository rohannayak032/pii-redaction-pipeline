"""
server.py - HTTP API for the React front-end.

It wraps the workflow layer (pipeline.py), which calls the team's real extraction, detection and redaction
modules, and scores runs with the evaluation module. Nothing here re-implements detection or redaction.

Run from the repository root:  python -m uvicorn --app-dir src pii_pipeline.app.backend.server:app

Privacy: raw PII values stay inside the server process (in memory) and are never put in any response. Results are
kept per "run" only so exports and ground-truth scoring can be done; "Clear all" deletes the run.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import List
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from pii_pipeline.app.backend import pipeline as P
from pii_pipeline.evaluation.evaluate_redaction import (REQUIRED_COLUMNS, diagnose, evaluate_redaction,
                                                        load_ground_truth)

MAX_RUNS = 20

app = FastAPI(title="PII Shield API")
_lock = threading.Lock()
RUNS: "OrderedDict[str, List[P.DocResult]]" = OrderedDict()

FINDING_COLUMNS = ["file", "page", "location", "block_index", "start", "end", "pii_type", "confidence",
                   "detector", "placeholder", "merged_entities"]


def get_run(run_id: str) -> List[P.DocResult]:
    with _lock:
        run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found (it may have been cleared or the server restarted). Run the analysis again.")
    return run


def attachment(data, media_type: str, filename: str) -> Response:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "download"
    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": disp})


def stem(name: str) -> str:
    return os.path.splitext(os.path.basename(name))[0]


# ----------------------------------------------------------------- API
@app.get("/api/config")
def config():
    return {"max_file_mb": P.MAX_FILE_MB, "supported": P.SUPPORTED, "gt_columns": list(REQUIRED_COLUMNS)}


@app.post("/api/runs")
def create_run():
    run_id = uuid.uuid4().hex
    with _lock:
        RUNS[run_id] = []
        while len(RUNS) > MAX_RUNS:
            RUNS.popitem(last=False)
    return {"run_id": run_id}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    with _lock:
        RUNS.pop(run_id, None)
    return {"ok": True}


@app.post("/api/runs/{run_id}/process")
def process(run_id: str, file: UploadFile = File(...)):
    run = get_run(run_id)
    res = P.process_document(file.filename or "upload", file.file.read())
    with _lock:
        run.append(res)
        idx = len(run) - 1
    return P.view(res, idx)


@app.post("/api/runs/{run_id}/evaluate")
def evaluate(run_id: str, ground_truth: UploadFile = File(...), require_type: bool = Form(True),
             exact: bool = Form(False)):
    """Score the run with the evaluation module. Only counts and metrics are returned, never values."""
    done = [r for r in get_run(run_id) if r.status != "failed"]
    with tempfile.TemporaryDirectory(prefix="pii_gt_") as tmp:
        gt = Path(tmp) / "ground_truth.csv"
        gt.write_bytes(ground_truth.file.read())
        try:
            labelled = {s.file for s in load_ground_truth(str(gt))}
        except Exception:   # the loader's messages quote whole rows, i.e. ground-truth values
            raise HTTPException(400, "Could not read the ground truth. Expected a CSV with columns: "
                                + ", ".join(REQUIRED_COLUMNS) + ".")
        scored = [r for r in done if r.filename in labelled]
        if not scored:
            return {"files": [], "unlabelled": [r.filename for r in done]}

        def score(results):
            return evaluate_redaction(str(gt), [e for r in results for e in r.entities],
                                      [b for r in results for b in r.redacted],
                                      iou_threshold=1.0 if exact else 0.5, require_type_match=require_type)

        def counts(result):
            d = result["details"]
            return {"missed": len(d["missed"]), "leaked": len(d["leaked"]),
                    "false_positives": len(d["false_positives"]), "repeats": result["repeats"]}

        total = score(scored)
        files = []
        for r in scored:
            one = score([r])
            files.append({"file": r.filename, **one["overall"], **counts(one)})
        return {
            "files": files,
            "unlabelled": [r.filename for r in done if r.filename not in labelled],
            "overall": total["overall"],
            "per_type": [{"type": t, **m} for t, m in total["per_type"].items()],
            "counts": counts(total),
            "warnings": total["warnings"],
            "diagnosis": diagnose(total, [b for r in scored for b in r.extraction.blocks],
                                  [e for r in scored for e in r.entities]),
        }


# ----------------------------------------------------------------- exports
@app.get("/api/runs/{run_id}/report.json")
def export_report(run_id: str):
    files = []
    for i, r in enumerate(get_run(run_id)):
        v = P.view(r, i)
        files.append({k: v[k] for k in ("filename", "sha256", "status", "error", "failed_stage", "llm_ready",
                                        "block_count", "pages", "timings", "leaks", "extraction", "detectors",
                                        "detected_types", "report")})
    return attachment(json.dumps({"files": files}, indent=2).encode(), "application/json", "exposure_report.json")


@app.get("/api/runs/{run_id}/findings.csv")
def export_findings(run_id: str):
    buf = io.StringIO()
    w = csv.DictWriter(buf, FINDING_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for i, r in enumerate(get_run(run_id)):
        w.writerows(P.view(r, i)["records"])
    return attachment(buf.getvalue().encode("utf-8"), "text/csv", "findings.csv")


@app.get("/api/runs/{run_id}/redacted.zip")
def export_zip(run_id: str):
    cleared = [r for r in get_run(run_id) if r.llm_ready]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, r in enumerate(cleared):
            z.writestr(f"{i + 1:02d}_{stem(r.filename)}.redacted.txt", r.redacted_text())
    return attachment(buf.getvalue(), "application/zip", "redacted_for_llm.zip")


@app.get("/api/runs/{run_id}/files/{idx}/redacted.txt")
def export_one(run_id: str, idx: int):
    run = get_run(run_id)
    if not 0 <= idx < len(run):
        raise HTTPException(404, "File not found in this run.")
    r = run[idx]
    if not r.llm_ready:
        raise HTTPException(403, "This file is not cleared for LLM.")
    return attachment(r.redacted_text().encode("utf-8"), "text/plain; charset=utf-8", f"{stem(r.filename)}.redacted.txt")


# ----------------------------------------------------------------- serve the built front-end (production)
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
