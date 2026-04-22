@echo off
chcp 65001 >nul
set "SEOULIB_TG_BOT_TOKEN=replace-with-your-token"
set "SEOULIB_TG_CHAT_ID=replace-with-your-chat-id"
cd /d "%~dp0"
python -B scripts\telegram_crawl_bot.py bot-loop
if errorlevel 1 pause
