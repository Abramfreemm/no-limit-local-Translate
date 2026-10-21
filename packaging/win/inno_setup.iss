; Inno Setup 脚本 —— 生成 Windows 安装包
; 需要 Inno Setup 6（https://jrsoftware.org/isdl.php）
; 构建：iscc packaging\win\inno_setup.iss
; 产物：packaging\win\Output\LinguaForge-<version>-Setup.exe

#define MyAppName "LinguaForge"
#define MyAppChineseName "译匠"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "LinguaForge"
#define MyAppURL "https://github.com/<owner>/linguaforge"
#define MyAppExeName "linguaforge.exe"
#define MySourceDir "dist\linguaforge"

[Setup]
AppId={{A7C3E1D0-5B4A-4F2E-9C8D-LINGUAFORGE01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=Output
OutputBaseFilename=LinguaForge-{#MyAppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=..\..\resources\icons\app.ico
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=no
; D6：V1.0 未签名。若日后购买证书，取消下一行注释并填入 pfx
; SignTool=linguaforge signtool sign /f "cert.pfx" /p "<pwd>" /tr http://timestamp.digicert.com /td sha256 /fd sha256 $f

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加任务 / Additional tasks:"
Name: "quicklaunchicon"; Description: "创建快速启动栏快捷方式"; GroupDescription: "附加任务 / Additional tasks:"; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; VC++ 运行库（缺失时静默安装，避免"找不到 DLL"）
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: VCRedistNeedsInstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName} / Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 让卸载程序能显示软件大小
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}_is1"; \
    ValueType: string; ValueName: "DisplayVersion"; ValueData: "{#MyAppVersion}"; \
    Check: IsAdminInstallMode

[Run]
; 缺 VC++ 时先装运行库
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/quiet /norestart"; \
    StatusMsg: "正在安装 Visual C++ 运行库…"; Check: VCRedistNeedsInstall; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName} / Launch"; \
    Flags: postinstall nowait skipifsilent

[UninstallDelete]
; 卸载时默认保留用户数据（术语表 / 翻译记忆），由下方 [Code] 询问
Type: filesandordirs; Name: "{app}"

[Code]
var
  DataPage: TInputOptionWizardPage;

function VCRedistNeedsInstall: Boolean;
begin
  Result := not RegKeyExists(HKEY_LOCAL_MACHINE,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64');
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputOptionPage(wpSelectTasks,
    '数据清理 / Data cleanup',
    '卸载时是否保留你的数据？',
    '保留：术语表、翻译记忆、任务记录（位于 %LOCALAPPDATA%\LinguaForge）。删除：连同应用数据一并清除。',
    True, False);
  DataPage.Add('保留应用数据（推荐）');
  DataPage.Add('删除应用数据');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('是否删除应用数据（术语表 / 翻译记忆 / 任务记录）？',
              mbConfirmation, MB_YESNO) = IDYES then
      begin
        DataDir := ExpandConstant('{localappdata}\LinguaForge');
        if DirExists(DataDir) then DelTree(DataDir, True, True, True);
      end;
  end;
end;
