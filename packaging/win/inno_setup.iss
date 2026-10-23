; Inno Setup 脚本 —— 生成 Windows 安装包
; 需要 Inno Setup 6（https://jrsoftware.org/isdl.php）
; 构建：iscc packaging\win\inno_setup.iss
; 产物：packaging\win\Output\LinguaForge-<version>-Setup.exe

#define MyAppName "LinguaForge"
#define MyAppChineseName "译匠"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "LinguaForge"
#define MyAppURL "https://github.com/<owner>/linguaforge"
#define MyAppExeName "LinguaForge.exe"
; 约定：PyInstaller 统一输出到 dist_v2（CI 与本地一致，见 .github/workflows/release.yml）。
; 不用 dist/ 是因为 PyInstaller 重建时会先删旧目录，在受管控环境里会触发批量删除确认。
#define MySourceDir "..\..\dist_v2\LinguaForge"

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
PrivilegesRequired=lowest
; 本应用不写 Program Files / HKLM，按用户安装即可。
; 若仍按管理员模式，静默安装会因 UAC 弹窗被抑制而卡住等待。
PrivilegesRequiredOverridesAllowed=dialog
ChangesEnvironment=no
; D6：V1.0 未签名。若日后购买证书，取消下一行注释并填入 pfx
; SignTool=linguaforge signtool sign /f "cert.pfx" /p "<pwd>" /tr http://timestamp.digicert.com /td sha256 /fd sha256 $f

[Languages]
; 本机 Inno Setup 未附带 ChineseSimplified.isl（winget 安装包缺该语言文件），
; 因此用 Default.isl 作底子，再用下方 [Messages] 覆盖成中文，避免构建中断。
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Messages]
; ---- 向导页标题与说明 ----
WizardWelcome=欢迎安装 LinguaForge 译匠
WelcomeLabel1=%n 将安装到您的电脑上。
WelcomeLabel2=建议在安装前关闭其他程序。\n\n点击“下一步”继续，或“取消”退出安装。
WizardSelectDir=选择安装位置
SelectDirDesc=安装程序将把 LinguaForge 安装到以下文件夹。
SelectDirLabel3=为避免权限问题，请不要安装到需要管理员权限的系统目录。
SelectDirBrowseLabel=点击“下一步”继续。若要更换文件夹，请点击“浏览”。
WizardSelectProgramGroup=选择开始菜单文件夹
WizardReady=准备安装
ReadyLabel1=安装程序已准备好开始安装 LinguaForge。
ReadyLabel2a=点击“安装”继续安装。若需更改设置，请点击“上一步”。
ReadyLabel2b=点击“安装”继续安装。
WizardPreparing=正在准备安装
WizardInstalling=正在安装
FinishedHeadingLabel=%n 安装向导已完成
; ---- 按钮 ----
ButtonNext=下一步(&N)>
ButtonBack=<上一步(&B)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
ButtonBrowse=浏览(&R)...
ButtonYes=是(&Y)
ButtonNo=否(&N)
ButtonOK=确定
; ---- 卸载 ----
UninstallAppFullTitle=%n 卸载
UninstallAppTitle=卸载 %n
UninstallStatusLabel=正在从您的电脑上卸载 %n，请稍候。
UninstalledAll=%n 已成功从您的电脑上卸载。
UninstalledMost=%n 卸载完成。\n\n部分内容未能删除，可手动清理。
UninstalledAndNeedsRestart=要完成 %n 的卸载，必须重启电脑。\n\n立即重启吗？
ConfirmUninstall=确定要完全卸载 %n 及其所有组件吗？
; ---- 其他 ----
SetupAborted=安装未完成。\n\n请修复问题后重新运行安装程序。
DiskSpaceWarningTitle=磁盘空间不足
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。\n\n现在退出，%n 将不会被安装。\n\n可稍后重新运行安装程序完成安装。
AboutSetupMenuItem=关于安装程序(&A)...

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加任务 / Additional tasks:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
