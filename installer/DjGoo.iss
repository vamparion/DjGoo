#define MyAppName "DjGoo"
#define MyAppVersion "0.3.0-alpha.29"
#define MyAppPublisher "DjGoo"

[Setup]
AppId={{AD9767E9-C1D3-4D20-AB85-4C45BD58EB1E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\DjGoo
DefaultGroupName=DjGoo
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=DjGoo-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DjGoo.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\build\windows-product\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\layers"

[Icons]
Name: "{group}\DjGoo"; Filename: "{app}\DjGoo.exe"
Name: "{group}\Repair DjGoo"; Filename: "{app}\DjGoo.Updater.exe"; Parameters: "repair"
Name: "{autodesktop}\DjGoo"; Filename: "{app}\DjGoo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DjGoo.exe"; Description: "Launch DjGoo"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\DjGoo.Updater.exe"; Parameters: "exit"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
