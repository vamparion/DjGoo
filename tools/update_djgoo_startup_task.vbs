Option Explicit

Const TASK_CREATE_OR_UPDATE = 6
Const TASK_LOGON_INTERACTIVE_TOKEN = 3
Const TASK_TRIGGER_LOGON = 9
Const TASK_TRIGGER_SESSION_STATE_CHANGE = 11
Const TASK_SESSION_UNLOCK = 8
Const TASK_ACTION_EXEC = 0

Dim service, folder, definition, principal, settings, action, trigger
Dim shell, fso, toolsDir, projectRoot, user, pythonw, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(toolsDir)
pythonw = projectRoot & "\.venv\Scripts\pythonw.exe"
launcher = projectRoot & "\tools\djgoo_stack.py"
user = CreateObject("WScript.Network").UserDomain & "\" & CreateObject("WScript.Network").UserName

If Not fso.FileExists(pythonw) Then
  WScript.Echo "DjGoo Python was not found: " & pythonw
  WScript.Quit 1
End If

Set service = CreateObject("Schedule.Service")
service.Connect
Set folder = service.GetFolder("\")
Set definition = service.NewTask(0)

Set principal = definition.Principal
principal.UserId = user
principal.LogonType = TASK_LOGON_INTERACTIVE_TOKEN

Set settings = definition.Settings
settings.Enabled = True
settings.MultipleInstances = 2
settings.ExecutionTimeLimit = "PT2M"
settings.DisallowStartIfOnBatteries = False
settings.StopIfGoingOnBatteries = False
settings.StartWhenAvailable = False

Set trigger = definition.Triggers.Create(TASK_TRIGGER_LOGON)
trigger.UserId = user
trigger.Enabled = True

Set trigger = definition.Triggers.Create(TASK_TRIGGER_SESSION_STATE_CHANGE)
trigger.UserId = user
trigger.StateChange = TASK_SESSION_UNLOCK
trigger.Enabled = True

Set action = definition.Actions.Create(TASK_ACTION_EXEC)
action.Path = pythonw
action.Arguments = """" & launcher & """ start"
action.WorkingDirectory = projectRoot

folder.RegisterTaskDefinition "DjGoo Startup", definition, TASK_CREATE_OR_UPDATE, Empty, Empty, TASK_LOGON_INTERACTIVE_TOKEN
WScript.Echo "DjGoo startup task updated for " & projectRoot
