@echo off
rem Starts the Reel Notes bot and restarts it if it ever stops.
rem Output goes to bot.log in this folder.
cd /d "%~dp0"

rem Wait ~30 seconds after login so Wi-Fi and Ollama are ready
ping -n 31 127.0.0.1 >nul

:loop
echo [%date% %time%] Starting bot >> "%~dp0bot.log"
"%~dp0.venv\Scripts\python.exe" -u "%~dp0bot.py" >> "%~dp0bot.log" 2>&1
echo [%date% %time%] Bot stopped, restarting in 60 seconds >> "%~dp0bot.log"
ping -n 61 127.0.0.1 >nul
goto loop
