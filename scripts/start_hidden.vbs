' PaperForge - windowless launcher for the panjuan:// protocol handler
'
' Why this file exists: if the registry handler points straight at powershell.exe,
' every click flashes a blue console window and it looks like a virus. wscript.exe
' running a .vbs can start it genuinely hidden (2nd arg 0 = hidden, 3rd False = don't wait).
'
' %1 is the URI the browser handed over (panjuan://start) - ignored on purpose:
' start.ps1 is idempotent, it opens the browser only when it is safe to.
'
' NOTE: keep this file pure ASCII. WSH reads .vbs with the system ANSI codepage,
' so a UTF-8 Chinese comment is the kind of thing that bites you later.
Option Explicit
Dim fso, sh, root, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & root & "\scripts\start.ps1"" -NoBrowser"
sh.Run cmd, 0, False
