# PII Shield (React + FastAPI)

Web front-end for the team's pipeline. Every number on screen is an output of the real modules:

| Step | Module call |
|------|-------------|
| Extraction | `pii_pipeline.extraction.extract_document_detailed` (blocks, block metadata, coded warnings) |
| Detection | `pii_pipeline.detection.detector.detect` (rules + Presidio + GLiNER + TinyBERT address NER) |
| Redaction | `pii_pipeline.redaction.redact_document` (verifies every block) and `build_report` |
| Residual check | app: no detected value may appear anywhere in the redacted text |
| Evaluation | `pii_pipeline.evaluation.evaluate_redaction.evaluate_redaction` and `diagnose` |

```
app/
  backend/    server.py (FastAPI) + pipeline.py (workflow layer)
  frontend/   React (Vite) source; frontend/dist = built UI (git-ignored)
  start.sh / start.bat
```

## Run
Install the project requirements first (`pip install -r requirements.txt` at the repo root, plus Tesseract for OCR), then:
```
src/pii_pipeline/app/start.sh            # Windows: src\pii_pipeline\app\start.bat
```
Open http://localhost:8000. The first file is slow while the detection models load.

## Develop the UI (hot reload)
```
python -m uvicorn --app-dir src pii_pipeline.app.backend.server:app --port 8000   # from the repo root
cd src/pii_pipeline/app/frontend && npm install && npm run dev                      # http://localhost:5173
```

## Evaluation tab
Upload a ground-truth CSV with columns `file, case_id, type, value, location, start, end`
(e.g. `src/pii_pipeline/evaluation/ground_truth_cadence_updated_with_addresses.csv`).
Rows are matched to processed files by the `file` column, so upload the documents under the same names.

## Demo report (screenshots + Word document)
With the server running and `data/sample.pdf`, `sample.docx`, `sample.pptx` in place:
```
cd src/pii_pipeline/app/report && npm install && npm run all
```
`capture.js` drives the UI in headless Chrome (`CHROME_PATH` to override the browser), runs the evaluation and
saves screenshots, API responses and exports to `data/outputs/`. `build_report.js` writes
`data/outputs/PII_Shield_Report.docx`; every number in it is read from those saved responses.
`data/` is git-ignored, so the outputs stay on your machine.

## Privacy
The original block text never leaves the server process. Detected values are sent to the browser only to fill the
Value column of the detection tables; trace records, the exposure report, the evaluation results and every export
(JSON, CSV, ZIP, .txt) contain no raw values. Run the server on a trusted machine only (it binds to 127.0.0.1).
Results are held in memory per run (max 20) so exports and evaluation work; **Clear all** deletes the run.
