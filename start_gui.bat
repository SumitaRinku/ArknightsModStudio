@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Please install Python 3.10+ first.
    pause
    exit /b 1
)
python -X utf8 -B mod_gui.py
if errorlevel 1 (
    echo.
    echo [ERROR] GUI exited with an error. See messages above.
    pause
)
