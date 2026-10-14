; GD Assistant v0.6-BETA web installer (small downloader).
;
; Downloads the portable one-file build from the v0.6 GitHub Release and
; installs it with Start Menu/desktop shortcuts and an uninstall entry. Build
; order:
;
;   1. python -m PyInstaller --noconfirm --clean GD_Assistant-v0.6-BETA.spec
;   2. Upload dist\GD_Assistant-v0.6-BETA.exe to the v0.6 GitHub Release
;   3. powershell -Command "(Get-FileHash 'dist\GD_Assistant-v0.6-BETA.exe' -Algorithm SHA256).Hash"
;   4. iscc /DPortableSHA256=<hash-from-step-3> installer\GD_Assistant-v0.6-BETA-Web.iss
;
; Without /DPortableSHA256 the download is installed without an integrity
; check (compile-time fallback only).
;
; Result: installer\Output\GD_Assistant-v0.6-BETA-WebSetup.exe

#ifndef PortableSHA256
#define PortableSHA256 ""
#endif

#define MyAppName "GD Assistant"
#define MyAppVersion "v0.6-BETA"
#define MyAppPublisher "GDDuong"
#define MyAppURL "https://github.com/GDDuong/GDAssistant"
#define MyAppExeName "GD_Assistant.exe"
#define PortableName "GD_Assistant-v0.6-BETA.exe"
#define DownloadURL "https://github.com/GDDuong/GDAssistant/releases/latest/download/GD_Assistant-v0.6-BETA.exe"

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
OutputBaseFilename=GD_Assistant-v0.6-BETA-WebSetup
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
Source: "{tmp}\{#PortableName}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadDone: Boolean;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and not DownloadDone then
  begin
    try
      // Third argument = SHA-256: verified by Inno itself when non-empty.
      DownloadTemporaryFile('{#DownloadURL}', '{#PortableName}', '{#PortableSHA256}', @OnDownloadProgress);
      DownloadDone := True;
    except
      MsgBox('GD Assistant could not be downloaded.' + #13#10 + #13#10 +
             GetExceptionMessage + #13#10 + #13#10 +
             'Check your internet connection and make sure the v0.6 release is published on GitHub, then run this installer again.',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;
