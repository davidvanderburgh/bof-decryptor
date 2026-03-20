; BOF Asset Decryptor — Inno Setup Script
; Compile with: ISCC.exe /DAppVersion=1.0.0 /DPythonDir=build\python /DProjectDir=.. bof_decryptor.iss
; Or use build.ps1 which handles everything automatically.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef ProjectDir
  #define ProjectDir ".."
#endif

#ifndef PythonDir
  #define PythonDir "build\python"
#endif

[Setup]
AppId={{B3E5F7A1-4C2D-4E9B-8F3A-1D7C5E9B2F4A}
AppName=BOF Asset Decryptor
AppVersion={#AppVersion}
AppVerName=BOF Asset Decryptor v{#AppVersion}
AppPublisher=David Vanderburgh
AppPublisherURL=https://github.com/davidvanderburgh/bof-decryptor
AppSupportURL=https://github.com/davidvanderburgh/bof-decryptor/issues
DefaultDirName={autopf}\BOF Asset Decryptor
DefaultGroupName=BOF Asset Decryptor
OutputBaseFilename=BOF_Asset_Decryptor_Setup_v{#AppVersion}
SetupIconFile={#ProjectDir}\bof_decryptor\icon.ico
UninstallDisplayIcon={app}\bof_decryptor\icon.ico
LicenseFile={#ProjectDir}\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
WizardSizePercent=110
DisableProgramGroupPage=auto
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "runprereqs"; Description: "Install WSL2 prerequisites after setup"; GroupDescription: "Prerequisites:"; Flags: unchecked

[Files]
; Bundled Python with tkinter
Source: "{#PythonDir}\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion

; Application package
Source: "{#ProjectDir}\bof_decryptor\__init__.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\__main__.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\app.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\config.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\executor.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\gui.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\pipeline.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\updater.py"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion
Source: "{#ProjectDir}\bof_decryptor\icon.ico"; DestDir: "{app}\bof_decryptor"; Flags: ignoreversion

; Entry point and launcher
Source: "{#ProjectDir}\BOF Asset Decryptor.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.vbs"; DestDir: "{app}"; Flags: ignoreversion

; Prerequisites installer (can be re-run from Start Menu)
Source: "install_prerequisites.ps1"; DestDir: "{app}"; Flags: ignoreversion

; Documentation
Source: "{#ProjectDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\BOF Asset Decryptor"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\bof_decryptor\icon.ico"; Comment: "Decrypt and modify Barrels of Fun pinball game assets"
Name: "{group}\Install Prerequisites"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_prerequisites.ps1"""; WorkingDir: "{app}"; Comment: "Install WSL2 and Ubuntu"
Name: "{group}\{cm:UninstallProgram,BOF Asset Decryptor}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional)
Name: "{autodesktop}\BOF Asset Decryptor"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\bof_decryptor\icon.ico"; Tasks: desktopicon; Comment: "Decrypt and modify Barrels of Fun pinball game assets"

[Run]
; Run prerequisites installer if the user checked the box
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_prerequisites.ps1"""; WorkingDir: "{app}"; StatusMsg: "Installing prerequisites..."; Flags: runascurrentuser shellexec waituntilterminated; Tasks: runprereqs

; Offer to launch the app after install
Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; Description: "Launch BOF Asset Decryptor"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up Python bytecode cache
Type: filesandordirs; Name: "{app}\bof_decryptor\__pycache__"

[Code]
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox('BOF Asset Decryptor requires Windows 10 or later.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;
