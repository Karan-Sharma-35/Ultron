@echo off
REM Step 3: train FRIDAY (triage). Dry run first - it stops before loading the model if anything is wrong.
cd /d "%~dp0"
python train_lora.py --task friday --dry_run || goto :fail
python train_lora.py --task friday %*
pause
exit /b 0
:fail
echo Stopped - read the message above.
pause
exit /b 1
