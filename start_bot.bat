@echo off
chcp 65001 >nul
cd /d C:\Users\ян\diar_car_buy
:loop
echo [%date% %time%] Запуск Diar Car Buy AI...
python main.py
echo [%date% %time%] Бот остановился (код %errorlevel%), перезапуск через 10 сек...
timeout /t 10 /nobreak >nul
goto loop
