@echo off
REM Step 5: score both adapters on the rows held out of their training.
cd /d "%~dp0"
python eval_lora.py --self_test || goto :fail
python eval_lora.py --task friday --save friday_eval.jsonl
python eval_lora.py --task edith --save edith_eval.jsonl
pause
exit /b 0
:fail
echo Stopped - read the message above.
pause
exit /b 1
