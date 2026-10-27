@echo off
REM Sends one clearly-labelled SAMPLE call to your Telegram to check the message layout.
cd /d "%~dp0"
python run.py --telegram-test
pause
