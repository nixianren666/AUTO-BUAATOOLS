; Inno Setup 6 脚本 - BUAA 课程独立签到助手安装包
; 针对 Windows 10 / 11 现代化安装向导优化

#define MyAppName "BUAA 课程独立签到助手"
#define MyAppEnglishName "BUAA-Signin"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "BUAA Open Source Community"
#define MyAppURL "https://github.com/BUAASubnet/UBAA"
#define MyAppExeName "BUAA-Signin.exe"

[Setup]
; 基础应用信息
AppId={{C8E2B548-7391-497B-95DC-8A2F226D1E3A}
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
OutputBaseFilename=BUAA-Signin-Setup-v1.2.0

; 压缩配置 (采用超高 LZMA2 压缩)
Compression=lzma2/ultra64
SolidCompression=yes

; 现代化向导视觉风格
WizardStyle=modern
WizardSizePercent=105
DisableProgramGroupPage=auto

; 自动检测并关闭运行中的应用
CloseApplications=yes
CloseApplicationsFilter=BUAA-Signin.exe
RestartApplications=no

; 权限与架构
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 (&D)"; GroupDescription: "附加快捷方式:"; Flags: checkedonce

[Files]
Source: "..\BUAA-Signin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[UninstallDelete]
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\使用帮助文档"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// 在安装前自动终止任何正在运行的 BUAA-Signin.exe，防止文件锁定导致无法覆盖安装旧版本
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM BUAA-Signin.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(400);
  Result := True;
end;

// 在卸载前自动终止任何正在运行的 BUAA-Signin.exe，彻底杜绝“卸载报错：文件正在被占用”
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM BUAA-Signin.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(400);
  Result := True;
end;
