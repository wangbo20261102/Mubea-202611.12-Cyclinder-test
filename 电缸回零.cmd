@echo off
chcp 65001 >nul
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Please install dependencies as described in README.md first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0mcea_home.py" --port COM3
pause
