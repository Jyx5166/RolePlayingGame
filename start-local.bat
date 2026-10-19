@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launcher\launch_local.py
) else (
  python launcher\launch_local.py
)
