#!/usr/bin/env bash
# One-command start: builds the UI if needed, then serves UI + API on http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d frontend/dist ]; then (cd frontend && npm install && npm run build); fi
pip install -q -r backend/requirements.txt
cd ../../..
python -m uvicorn --app-dir src pii_pipeline.app.backend.server:app --host 127.0.0.1 --port 8000
