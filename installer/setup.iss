; Inno Setup script: per-user install, no admin rights needed
#define AppName "FTTH Aerial Designer"
#define AppVer GetEnv("APP_VERSION")
[Setup]
AppId={{6C1B7B5E-4F3A-4D0B-9B7C-AE1F7D2C5A11}
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={localappdata}\Programs\FTTH Aerial Designer
DefaultGroupName=FTTH Aerial Designer
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Setup_FTTH_Aerial_Designer
Compression=lzma2/fast
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
[Files]
Source: "..\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{autoprograms}\مصمم الدراسات الهوائية"; Filename: "{app}\python\pythonw.exe"; Parameters: "-X utf8 ""{app}\app\core\ftth_web.py"""; WorkingDir: "{app}\app"
Name: "{autodesktop}\مصمم الدراسات الهوائية"; Filename: "{app}\python\pythonw.exe"; Parameters: "-X utf8 ""{app}\app\core\ftth_web.py"""; WorkingDir: "{app}\app"
[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-X utf8 ""{app}\app\core\ftth_web.py"""; WorkingDir: "{app}\app"; Description: "Launch"; Flags: nowait postinstall skipifsilent
