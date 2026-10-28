; Inno Setup 6 Script for OpenFlow
; Produces dist/OpenFlow-Setup.exe
; Installs per-user to {localappdata}\OpenFlow (no admin UAC elevation required)

#define MyAppName "OpenFlow"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "OpenFlow"
#define MyAppURL "https://sachin1724.github.io/OpenFlow/"
#define MyAppExeName "OpenFlow.exe"

[Setup]
AppId={{D1A3F5B8-7E92-4C61-B9D4-4328E0B5B721}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL=https://github.com/Sachin1724/OpenFlow/issues
AppUpdatesURL=https://github.com/Sachin1724/OpenFlow/releases
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=OpenFlow-Setup
SetupIconFile=OpenFlow.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
CloseApplications=yes
CloseApplicationsFilter=*OpenFlow*,*pythonw*
RestartApplications=no
DisableDirPage=auto
DisableProgramGroupPage=auto
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Launch OpenFlow automatically when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\OpenFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser; WorkingDir: "{app}"


[UninstallDelete]
Type: filesandordirs; Name: "{app}"
