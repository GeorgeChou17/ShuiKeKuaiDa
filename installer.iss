; ============================================================
; Inno Setup 安装脚本 - 水课快答
; 编译：用 Inno Setup Compiler 打开此文件 → Compile
; ============================================================

[Setup]
AppName=水课快答
AppVersion=1.2.2
AppPublisher=GeorgeChou
AppPublisherURL=https://github.com/GeorgeChou17/ShuiKeKuaiDa
DefaultDirName={autopf}\水课快答
DefaultGroupName=水课快答
OutputDir=dist_installer
OutputBaseFilename=水课快答_Setup_v1.2.2
SetupIconFile=logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall

[Files]
Source: "dist\水课快答.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\水课快答"; Filename: "{app}\水课快答.exe"; IconFilename: "{app}\水课快答.exe"
Name: "{group}\卸载 水课快答"; Filename: "{uninstallexe}"
Name: "{autodesktop}\水课快答"; Filename: "{app}\水课快答.exe"; IconFilename: "{app}\水课快答.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&)"; GroupDescription: "附加任务"; Flags: unchecked

[Run]
Filename: "{app}\水课快答.exe"; Description: "启动 水课快答"; Flags: nowait postinstall skipifdoesntexist

[UninstallDelete]
Type: files; Name: "{app}\*"
Type: filesandordirs; Name: "{app}"
