"""
server.py - HTTP API for the React front-end.

It only wraps the existing workflow layer (pipeline.py / mock_modules.py / backend_config.py), which are used
UNCHANGED. Nothing here re-implements detection or redaction.

Privacy: raw PII values stay inside the server process (in memory) and are never put in any response. Results are
kept per "run" only so exports and ground-truth scoring can be done; "Clear all" deletes the run.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import backend_config as cfg
import pipeline as P

# Fixed defaults (the settings panel was removed from the UI). Override with env vars if ever needed.
SETTINGS = P.Settings(
    force_mock=os.getenv("PII_FORCE_MOCK", "0") == "1",
    strict_real=os.getenv("PII_STRICT_REAL", "0") == "1",
    min_confidence=float(os.getenv("PII_MIN_CONFIDENCE", "0.0")),
)
MAX_RUNS = 20

app = FastAPI(title="PII Shield API")
_lock = threading.Lock()
RUNS: "OrderedDict[str, List[P.DocResult]]" = OrderedDict()

ENTITY_COLUMNS = ["#", "Type", "Severity", "Page/Slide", "Location", "Block", "Start", "End", "Confidence",
                  "Detector", "Placeholder"]


# ----------------------------------------------------------------- helpers
def _jsonable(obj):
    try:
        return json.loads(json.dumps(obj, default=repr))
    except Exception:
        return repr(obj)


def serialize(r: P.DocResult, idx: int) -> dict:
    """View-model for the UI. No raw PII values and no original block text."""
    rep, note = P.scrubbed_teammate_report(r)
    keep = P.non_pii_preserved(r)
    ocr = [b.ocr_confidence for b in r.blocks if b.ocr_confidence is not None]
    if r.aligned:
        redacted = [{"location": b.location, "page": b.page, "text": t} for b, t in zip(r.blocks, r.redacted_texts)]
    else:
        redacted = [{"location": "", "page": 1, "text": "\n".join(r.redacted_texts)}]
    return {
        "index": idx,
        "filename": r.filename, "file_type": r.file_type, "status": r.status, "error": r.error,
        "failed_stage": r.failed_stage, "risk": r.risk, "llm_ready": r.llm_ready, "aligned": r.aligned,
        "pages": r.pages, "block_count": len(r.blocks), "categories": r.by_category(),
        "warnings": r.warnings, "leaks": r.leaks, "timings": r.timings, "log": r.log, "backends": r.backends,
        "entities": [dict(e.public(), n=i + 1) for i, e in enumerate(r.entities)],
        "skipped_entities": [e.public() for e in r.skipped_entities],
        "redacted": redacted,
        "placeholders": P.placeholder_table(r),
        "report": r.to_report(),
        "teammate_report": _jsonable(rep) if rep is not None else None,
        "teammate_report_note": note,
        "non_pii_preserved": keep,
        "lowest_ocr": min(ocr) if ocr else None,
    }


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
    return {
        "max_file_mb": cfg.MAX_FILE_MB,
        "supported": sorted(cfg.SUPPORTED_TYPES),          # with leading dot, sorted (as shown in the footer)
        "types": cfg.SUPPORTED_TYPES,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "backends": P.backend_status(SETTINGS)}


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
    data = file.file.read()
    res = P.process_document(file.filename or "upload", data, SETTINGS)
    with _lock:
        run.append(res)
        idx = len(run) - 1
    return serialize(res, idx)


@app.post("/api/runs/{run_id}/evaluate")
def evaluate(run_id: str, ground_truth: UploadFile = File(...), partial: bool = Form(False),
             match_type: bool = Form(False)):
    run = get_run(run_id)
    ok = [r for r in run if r.status != "failed"]
    try:
        raw = ground_truth.file.read().decode("utf-8-sig")
        if (ground_truth.filename or "").lower().endswith(".json"):
            data = json.loads(raw)
            truth = data if isinstance(data, list) else data.get("entities", [])
        else:
            truth = list(csv.DictReader(io.StringIO(raw)))
        files_rows, type_rows = P.evaluate_detection(ok, truth, partial, match_type)
    except Exception as e:
        raise HTTPException(400, f"Could not read or score the ground truth ({type(e).__name__}).")
    summary = None
    if files_rows:
        gtn = sum(f["Ground truth"] for f in files_rows)
        hits = sum(f["Hits"] for f in files_rows)
        det = sum(f["Detected"] for f in files_rows)
        fp = sum(f["False positives"] for f in files_rows)
        summary = {"recall": hits / gtn if gtn else None, "precision": (det - fp) / det if det else None,
                   "missed": sum(f["Missed (false negatives)"] for f in files_rows)}
    return {"files": files_rows, "types": type_rows, "summary": summary}


# ----------------------------------------------------------------- exports
@app.get("/api/runs/{run_id}/report.json")
def export_report(run_id: str):
    run = get_run(run_id)
    body = json.dumps({"files": [r.to_report() for r in run]}, indent=2, default=str)
    return attachment(body.encode(), "application/json", "exposure_report.json")


@app.get("/api/runs/{run_id}/findings.csv")
def export_findings(run_id: str):
    run = get_run(run_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(ENTITY_COLUMNS + ["File"])
    for r in [r for r in run if r.status != "failed"]:
        for i, e in enumerate(r.entities):
            p = e.public()
            w.writerow([i + 1, p["entity_type"], p["severity"], p["page"], p["location"], p["block"],
                        "" if p["start"] is None else p["start"], "" if p["end"] is None else p["end"],
                        p["confidence"], p["detector"], p["placeholder"], r.filename])
    return attachment(buf.getvalue().encode("utf-8"), "text/csv", "findings.csv")


@app.get("/api/runs/{run_id}/redacted.zip")
def export_zip(run_id: str):
    run = get_run(run_id)
    cleared = [r for r in run if r.llm_ready]
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
