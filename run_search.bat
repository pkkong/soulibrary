@echo off
chcp 65001 >nul
echo [Search] Starting search-only app on port %LIBRARY_SEARCH_PORT: =5001%...

:: 1) Open search page (default 5001)
if "%LIBRARY_SEARCH_PORT%"=="" set LIBRARY_SEARCH_PORT=5001
start "" http://127.0.0.1:%LIBRARY_SEARCH_PORT%/

:: 1-1) Default PostgreSQL connection for local testing (override if needed)
if "%DB_HOST%"=="" set DB_HOST=localhost
if "%DB_PORT%"=="" set DB_PORT=5432
if "%DB_NAME%"=="" set DB_NAME=postgres
if "%DB_USER%"=="" set DB_USER=root
if "%DB_PASSWORD%"=="" set DB_PASSWORD=localpass

:: 2) Move to web directory
cd /d "%~dp0web"

:: 3) Run search-only server
set PORT=%LIBRARY_SEARCH_PORT%
python app_search.py

:: Keep window open
pause
