; Inno Setup 6 Script for OpenFlow
; Produces dist/OpenFlow-Setup.exe
; Installs per-user to {localappdata}\OpenFlow (no admin UAC elevation required)

#define MyAppName "OpenFlow"
#define MyAppVersion "1.1.9"
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
CloseApplications=force
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

[Files]
Source: "..\dist\OpenFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs restartreplace

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[InstallDelete]
; autostart is the app's own setting (Run key); an old Startup shortcut launched it twice at boot
Type: files; Name: "{userstartup}\{#MyAppName}.lnk"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser; WorkingDir: "{app}"
Filename: "{app}\{#MyAppExeName}"; Flags: nowait runasoriginaluser; WorkingDir: "{app}"; Check: WizardSilent


[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // Forcibly terminate any running OpenFlow instances so executables and DLLs are never locked
  Exec('cmd.exe', '/c taskkill /f /im OpenFlow.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(300);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('cmd.exe', '/c taskkill /f /im OpenFlow.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(250);
  end;
end;
