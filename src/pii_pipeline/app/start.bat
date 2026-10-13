@echo off
cd /d "%~dp0"
if not exist frontend\dist ( cd frontend & call npm install & call npm run build & cd .. )
cd backend
pip install -q -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
