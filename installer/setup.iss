; Inno Setup 6 脚本 - BUAA 课程独立签到助手安装包
; 针对 Windows 10 / 11 现代化安装向导优化

#define MyAppName "BUAA 课程独立签到助手"
#define MyAppEnglishName "BUAA-Signin"
#define MyAppVersion "1.4.13"
#define MyAppPublisher "nixianren666"
#define MyAppURL "https://github.com/nixianren666/AUTO-BUAATOOLS"
#define MyAppExeName "BUAA-Signin.exe"

[Setup]
; 基础应用信息
AppId={code:GetApplicationId}
UsePreviousLanguage=no
UsePreviousPrivileges=no
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 安装路径配置 (默认安装至 Program Files 或当前用户本地软件目录)
DefaultDirName={autopf}\{#MyAppEnglishName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
OutputDir=..\dist_installer
OutputBaseFilename=BUAA-Signin-Setup-v1.4.13
SetupIconFile=..\app_icon.ico

; 压缩配置 (采用超高 LZMA2 压缩)
Compression=lzma2/ultra64
SolidCompression=yes

; 现代化向导视觉风格
WizardStyle=modern
WizardSizePercent=105
DisableProgramGroupPage=auto

; 自动检测并关闭运行中的应用
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

; 权限与架构
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\app_icon.ico

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 (&D)"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
Source: "..\dist\BUAA-Signin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[UninstallDelete]

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\使用帮助文档"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\app_icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

; Restart Manager only considers files that this installer updates.
; No process-name-wide taskkill and no recursive deletion of user data.

[Code]
function GetApplicationId(Param: String): String;
begin
  if ExpandConstant('{param:BUAA-ACCEPTANCE|0}') = '1' then
    Result := '{D925D39B-16C2-4FAA-BB5C-9B5725290B88}'
  else
    Result := '{C8E2B548-7391-497B-95DC-8A2F226D1E3A}';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command, InstalledExe: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BUAA-Signin', Command) then
    begin
      Command := Lowercase(Trim(Command));
      InstalledExe := Lowercase(ExpandConstant('{app}\{#MyAppExeName}'));
      if (Command = InstalledExe) or (Pos('"' + InstalledExe + '"', Command) = 1) or (Pos(InstalledExe + ' ', Command) = 1) then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BUAA-Signin');
    end;
  end;
end;
