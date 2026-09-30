' Runs trigger_report.ps1 with no window at all -- see run_kanal_finans_hidden.vbs
' for why WScript.Shell.Run style 0 and not powershell.exe -WindowStyle Hidden,
' and why the third argument (wait) is True.
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptDir & "\trigger_report.ps1"""
shell.Run cmd, 0, True
