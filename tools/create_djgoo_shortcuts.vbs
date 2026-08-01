Option Explicit

Dim shell, desktop, projectRoot, pythonw, launcher
Set shell = CreateObject("WScript.Shell")
desktop = shell.SpecialFolders("Desktop")
projectRoot = "C:\Users\VERA\Documents\DiscordBot"
pythonw = projectRoot & "\.venv\Scripts\pythonw.exe"
launcher = projectRoot & "\tools\djgoo_stack.py"

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

CreateShortcut "Start DjGoo.lnk", "start"
CreateShortcut "Reset DjGoo.lnk", "reset"
CreateShortcut "Start DjGoo Voice.lnk", "start"
CreateShortcut "Stop DjGoo Voice.lnk", "stop"
