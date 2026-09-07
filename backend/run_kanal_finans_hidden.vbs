' Runs the Kanal Finans task with no window at all.
'
' powershell.exe -WindowStyle Hidden CREATES the window and then hides it,
' which on an interactive logon session shows as a brief flash every 15
' minutes (sometimes the PowerShell window, sometimes the console host behind
' it). WScript.Shell.Run with style 0 never creates one.
'
' The third argument is True (wait): Task Scheduler's MultipleInstances=
' IgnoreNew setting only works if wscript.exe stays "running" until the
' PowerShell it launched has finished. Without the wait, a slow run could be
' overlapped by the next trigger.
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptDir & "\run_kanal_finans.ps1"""
shell.Run cmd, 0, True
