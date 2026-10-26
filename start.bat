@echo off
REM Practice mode (simulated data). Double-click start-live.bat for Kite live data.
cd /d "%~dp0"
python run.py %*
pause
