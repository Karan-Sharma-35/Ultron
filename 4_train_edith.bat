@echo off
REM Step 4: train EDITH (assistant skills). Dry run first.
cd /d "%~dp0"
python train_lora.py --task edith --dry_run || goto :fail
python train_lora.py --task edith %*
pause
exit /b 0
:fail
echo Stopped - read the message above.
pause
exit /b 1
