@echo off
REM One-time: connect your own Telegram so CandleEdge can send you setup alerts.
cd /d "%~dp0"
python run.py --telegram-setup
pause
