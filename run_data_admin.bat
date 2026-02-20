@echo off
chcp 65001 >nul
echo [Data Admin] Starting data quality dashboard...

:: 1) Port (default 5002, shared with curation admin app)
if "%LIBRARY_DATA_ADMIN_PORT%"=="" set LIBRARY_DATA_ADMIN_PORT=5002
set LIBRARY_SEARCH_PORT=%LIBRARY_DATA_ADMIN_PORT%

:: 2) Enable admin mode (required for /admin/data-quality)
set ENABLE_CURATION_ADMIN=1

:: 3) Default PostgreSQL connection for local testing
if "%DB_HOST%"=="" set DB_HOST=localhost
if "%DB_PORT%"=="" set DB_PORT=5432
if "%DB_NAME%"=="" set DB_NAME=soulib_test
if "%DB_USER%"=="" set DB_USER=root
if "%DB_PASSWORD%"=="" set DB_PASSWORD=localpass

:: 4) Open dashboard
start "" http://127.0.0.1:%LIBRARY_DATA_ADMIN_PORT%/admin/data-quality

:: 5) Move to web directory
cd /d "%~dp0web"

:: 6) Run app_search with admin mode
python app_search.py

:: Keep window open
pause
