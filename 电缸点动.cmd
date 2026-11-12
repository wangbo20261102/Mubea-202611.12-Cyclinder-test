@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
  echo Install dependencies as described in README.md first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" mcea_jog.py
if errorlevel 1 pause
