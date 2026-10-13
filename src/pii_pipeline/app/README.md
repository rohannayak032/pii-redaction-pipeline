# PII Shield (React + Python)

Same interface and features as the Streamlit app, rebuilt as a React front-end.
Your pipeline code is reused **unchanged** (`pipeline.py`, `mock_modules.py`, `backend_config.py`).

```
pii-shield/
  backend/    server.py (FastAPI)  + pipeline.py, mock_modules.py, backend_config.py, make_samples.py
  frontend/   React (Vite) source; frontend/dist = ready-built UI
  samples/    fake test files + ground_truth.csv
  start.sh / start.bat
```

## Run (production style, one process)
```
./start.sh            # Windows: start.bat
```
Open http://localhost:8000  (needs Python 3.10+; Node only if `frontend/dist` is missing or you edit the UI).

## Develop the UI (hot reload)
```
cd backend  && pip install -r requirements.txt && python -m uvicorn server:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173 (proxies /api to :8000)
```

## How it maps to the Streamlit app
| Streamlit                         | Now                                                    |
|-----------------------------------|--------------------------------------------------------|
| `app.py` UI                       | `frontend/src/*` (React)                               |
| `P.process_document(...)`         | `POST /api/runs/{id}/process` in `server.py`           |
| `P.evaluate_detection(...)`       | `POST /api/runs/{id}/evaluate`                         |
| download buttons                  | `GET /api/runs/{id}/report.json, findings.csv, redacted.zip, files/{n}/redacted.txt` |
| sidebar settings (removed)        | fixed defaults; env vars `PII_FORCE_MOCK`, `PII_STRICT_REAL`, `PII_MIN_CONFIDENCE` |

Connecting the team's real modules is unchanged: edit `backend/backend_config.py`.
Theme: Light / Dark / System switch (top right), remembered in the browser.

## Privacy
Raw PII and original block text never leave the server process and are never in any API response.
Results are held in memory per run (max 20) so exports/evaluation work; **Clear all** deletes the run.
