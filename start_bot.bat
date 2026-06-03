@echo off
chcp 65001 >nul
cd /d C:\diar_car_buy
:loop
echo [%date% %time%] Starting Diar Car Buy AI...
python main.py
echo Bot stopped, restarting in 10 sec...
timeout /t 10 /nobreak >nul
goto loop
