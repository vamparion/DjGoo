Option Explicit

Dim shell, fso, desktop, folder, file, shortcut
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
desktop = shell.SpecialFolders("Desktop")
Set folder = fso.GetFolder(desktop)

For Each file In folder.Files
  If LCase(fso.GetExtensionName(file.Name)) = "lnk" And InStr(1, file.Name, "DjGoo", vbTextCompare) > 0 Then
    Set shortcut = shell.CreateShortcut(file.Path)
    WScript.Echo file.Path
    WScript.Echo "  Target: " & shortcut.TargetPath
    WScript.Echo "  Args:   " & shortcut.Arguments
    WScript.Echo "  Start:  " & shortcut.WorkingDirectory
  End If
Next
