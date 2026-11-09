@echo off
rem Stops the background bot (both the restart loop and Python).
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*reel-notes*start_bot.bat*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force };" ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*reel-notes*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Bot stopped.
pause
