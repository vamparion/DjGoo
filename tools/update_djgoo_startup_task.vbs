Option Explicit

Const TASK_CREATE_OR_UPDATE = 6
Const TASK_LOGON_INTERACTIVE_TOKEN = 3
Const TASK_TRIGGER_LOGON = 9
Const TASK_TRIGGER_SESSION_STATE_CHANGE = 11
Const TASK_SESSION_UNLOCK = 8
Const TASK_ACTION_EXEC = 0

Dim service, folder, definition, principal, settings, action, trigger, projectRoot, user
projectRoot = "C:\Users\VERA\Documents\DiscordBot"
user = CreateObject("WScript.Network").UserDomain & "\" & CreateObject("WScript.Network").UserName

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
settings.ExecutionTimeLimit = "PT10M"
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
action.Path = projectRoot & "\.venv\Scripts\pythonw.exe"
action.Arguments = """" & projectRoot & "\tools\djgoo_stack.py"" start"
action.WorkingDirectory = projectRoot

folder.RegisterTaskDefinition "DjGoo Startup", definition, TASK_CREATE_OR_UPDATE, Empty, Empty, TASK_LOGON_INTERACTIVE_TOKEN
