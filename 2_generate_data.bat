@echo off
REM Step 2: generate both synthetic training sets into data\.
cd /d "%~dp0"
python data_gen.py
python friday_data_gen.py
pause
