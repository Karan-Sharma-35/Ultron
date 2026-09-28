@echo off
REM Step 6: run Ultron - the HUD opens in its own window; type there or here. Say "power down" to close.
cd /d "%~dp0"
python ultron.py %*
pause
