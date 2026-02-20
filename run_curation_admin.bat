@echo off
chcp 65001 >nul
echo [Curation Admin] Starting curation admin app...

:: 1) Port (default 5002)
if "%LIBRARY_CURATION_PORT%"=="" set LIBRARY_CURATION_PORT=5002
set LIBRARY_SEARCH_PORT=%LIBRARY_CURATION_PORT%

:: 2) Enable admin mode (disabled in run_search.bat)
set ENABLE_CURATION_ADMIN=1

:: 3) Default PostgreSQL connection for local testing (override if needed)
if "%DB_HOST%"=="" set DB_HOST=localhost
if "%DB_PORT%"=="" set DB_PORT=5432
if "%DB_NAME%"=="" set DB_NAME=soulib_test
if "%DB_USER%"=="" set DB_USER=root
if "%DB_PASSWORD%"=="" set DB_PASSWORD=localpass

:: 4) Open admin page
start "" http://127.0.0.1:%LIBRARY_CURATION_PORT%/admin/curations

:: 5) Move to web directory
cd /d "%~dp0web"

:: 6) Run app_search with curation admin enabled
python app_search.py

:: Keep window open
pause
