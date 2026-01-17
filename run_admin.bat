@echo off
chcp 65001 >nul
echo [Admin] Starting library crawler dashboard...

:: PostgreSQL connection (local dev)
set DB_HOST=localhost
set DB_PORT=5432
set DB_NAME=postgres
set DB_USER=root
set DB_PASSWORD=localpass

:: 1) Open admin page in browser
start "" http://127.0.0.1:5000/admin

:: 2) Move to web directory (handles spaces/Korean paths)
cd /d "%~dp0web"

:: 3) Run server (keep this window open)
python app.py

:: Keep window open
pause
