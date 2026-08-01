Option Explicit

Dim shell, fso, desktop, toolsDir, projectRoot, pythonw, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
desktop = shell.SpecialFolders("Desktop")
toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(toolsDir)
pythonw = projectRoot & "\.venv\Scripts\pythonw.exe"
launcher = projectRoot & "\tools\djgoo_stack.py"

If Not fso.FileExists(pythonw) Then
  WScript.Echo "DjGoo Python was not found: " & pythonw
  WScript.Quit 1
End If

Sub CreateShortcut(name, args)
  Dim shortcut
  Set shortcut = shell.CreateShortcut(desktop & "\" & name)
  shortcut.TargetPath = pythonw
  shortcut.Arguments = """" & launcher & """ " & args
  shortcut.WorkingDirectory = projectRoot
  shortcut.Description = Replace(name, ".lnk", "")
  shortcut.IconLocation = pythonw & ",0"
  shortcut.Save
End Sub

Sub RemoveShortcut(name)
  Dim path
  path = desktop & "\" & name
  If fso.FileExists(path) Then
    fso.DeleteFile path, True
  End If
End Sub

' These legacy shortcuts controlled the whole stack despite their names.
RemoveShortcut "Start DjGoo Voice.lnk"
RemoveShortcut "Stop DjGoo Voice.lnk"

CreateShortcut "Start DjGoo.lnk", "start"
CreateShortcut "Reset DjGoo.lnk", "reset"
CreateShortcut "Stop DjGoo.lnk", "stop"

WScript.Echo "DjGoo shortcuts updated for " & projectRoot
