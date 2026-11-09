@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo Installing NetPulse to C: Drive...
echo ========================================================
python installer.py
pause

