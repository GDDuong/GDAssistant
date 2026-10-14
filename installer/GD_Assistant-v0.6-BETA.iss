; GD Assistant v0.6-BETA offline installer.
;
; Packages the onedir PyInstaller build into a single Setup.exe with Start
; Menu/desktop shortcuts and an uninstaller. Build order:
;
;   1. python -m PyInstaller --noconfirm --clean GD_Assistant-v0.6-BETA-Setup.spec
;   2. iscc installer\GD_Assistant-v0.6-BETA.iss
;
; Result: installer\Output\GD_Assistant-v0.6-BETA-Setup.exe

#define MyAppName "GD Assistant"
#define MyAppVersion "v0.6-BETA"
#define MyAppPublisher "GDDuong"
#define MyAppURL "https://github.com/GDDuong/GDAssistant"
#define MyAppExeName "GD_Assistant.exe"

[Setup]
AppId={{8E245D86-1895-4B1A-A709-F5C5577FA364}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=GD_Assistant-v0.6-BETA-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\GD_Assistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
