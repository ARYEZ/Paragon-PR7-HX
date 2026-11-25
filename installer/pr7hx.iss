; Paragon PR7-HX installer (Inno Setup 6): a hex editor, the way HxD edits.
;   iscc /DAppVersion=0.1.0 installer\pr7hx.iss      (after pyinstaller pr7hx.spec has made dist\PR7-HX)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-HX, with a Start menu entry. "Edit with PR7-HX" in
; Explorer's menu (ticked) is registered by PR7-HX itself (--register-menu; --unregister on uninstall), HKCU only, so the
; installer, Tools > Edit with PR7-HX in the Explorer Menu and the command line share shell.py.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{C612D234-7CDF-4811-BA78-1965A73D44AA}
AppName=Paragon PR7-HX
AppVersion={#AppVersion}
AppVerName=Paragon PR7-HX {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-HX
DefaultGroupName=Paragon PR7-HX
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-HX-Setup-{#AppVersion}
SetupIconFile=..\pr7hx\icons\app.ico
UninstallDisplayIcon={app}\PR7-HX.exe
UninstallDisplayName=Paragon PR7-HX
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "explorermenu"; Description: "Add ""Edit with PR7-HX"" to Explorer's menu"; GroupDescription: "Explorer:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-HX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-HX"; Filename: "{app}\PR7-HX.exe"; Comment: "Hex editor"
Name: "{autodesktop}\Paragon PR7-HX"; Filename: "{app}\PR7-HX.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-HX.exe"; Parameters: "--register-menu"; Tasks: explorermenu; Flags: runhidden waituntilterminated
Filename: "{app}\PR7-HX.exe"; Description: "{cm:LaunchProgram,Paragon PR7-HX}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-HX again when done.
Filename: "{app}\PR7-HX.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[UninstallRun]
Filename: "{app}\PR7-HX.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
