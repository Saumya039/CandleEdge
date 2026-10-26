@echo off
REM Live Kite data for EVERY F^&O index and stock (first start takes several minutes).
cd /d "%~dp0"
python run.py --live --all-fno %*
pause
