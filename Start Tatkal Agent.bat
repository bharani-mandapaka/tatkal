@echo off
cd /d "%~dp0"
python chat_ui.py
if errorlevel 1 (
    echo.
    echo Something went wrong above. Leave this window open and send a screenshot.
    pause
)
