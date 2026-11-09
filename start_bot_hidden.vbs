' Runs start_bot.bat with no visible window.
' Put a shortcut to this file in your Windows Startup folder (Win+R -> shell:startup).
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & folder & "\start_bot.bat""", 0, False
