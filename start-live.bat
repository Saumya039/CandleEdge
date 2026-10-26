@echo off
REM Live Kite data (read-only, no orders). Asks once for your API key and secret.
cd /d "%~dp0"
python run.py --live %*
pause
