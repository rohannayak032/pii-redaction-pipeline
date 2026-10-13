@echo off
rem One-command start: builds the UI if needed, then serves UI + API on http://localhost:8000
cd /d "%~dp0"
if not exist frontend\dist ( cd frontend & call npm install & call npm run build & cd .. )
pip install -q -r backend\requirements.txt
cd ..\..\..
python -m uvicorn --app-dir src pii_pipeline.app.backend.server:app --host 127.0.0.1 --port 8000
