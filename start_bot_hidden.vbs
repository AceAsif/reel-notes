' Starts the Reel Notes tray icon (which runs the bot) with no console window.
' Put a shortcut to this file in your Windows Startup folder (Win+R -> shell:startup).
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" """ & folder & "\tray.py""", 0, False
