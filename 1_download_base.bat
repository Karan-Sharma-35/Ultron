@echo off
REM Step 1: download the base model (safetensors only) and run the safety check.
cd /d "%~dp0"
python download_base.py
pause
