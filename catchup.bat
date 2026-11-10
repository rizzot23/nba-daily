@echo off
cd /d "%~dp0"
python scripts\catchup.py %*
echo.
pause
