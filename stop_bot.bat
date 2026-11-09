@echo off
rem Stops the tray icon and the background bot.
rem (Normally you can just right-click the tray icon -> Quit.)
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*reel-notes*tray.py*' -or $_.CommandLine -like '*reel-notes*start_bot.bat*' -or $_.CommandLine -like '*reel-notes*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Bot stopped.
pause
