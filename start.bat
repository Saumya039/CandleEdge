@echo off
REM Practice mode (simulated data). Use start.bat --live for Kite live data.
cd /d "%~dp0"
python run.py %*
pause
