; OwlCheck installer for Windows (Inno Setup 6).
;
; Builds dist\OwlCheck-Setup-<version>.exe from dist\OwlCheck (PyInstaller's folder build).
;   Local:   packaging\build-installer.bat   (or: python packaging\build_exe.py --installer)
;   GitHub:  .github\workflows\build.yml runs it after PyInstaller.
;
; Installs for the current user only (no administrator password) in
; %LOCALAPPDATA%\Programs\OwlCheck, with a Start menu shortcut, an optional
; desktop shortcut and an uninstaller in "Add or remove programs".
;
; Look: the wizard uses the app's colors (paper and ink), its pixel font (Silkscreen,
; loaded only while setup runs) and pixel-art images made by packaging\make_icons.py.
; Buttons, title bar and progress bar stay as Windows draws them.
;
; This file is UTF-8 with a BOM, so Inno Setup reads the accented texts correctly.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "OwlCheck"
#define MyAppExeName "OwlCheck.exe"

[Setup]
; This AppId identifies OwlCheck on Windows. Never change it: it is how a new version
; updates the previous one instead of installing a second copy.
AppId={{400EFEF6-3D5C-4BD6-9E9F-205CFAE5A7E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Owlgorithm Research
AppPublisherURL=https://github.com/owlgorithm-research
AppSupportURL=https://github.com/owlgorithm-research/owlcheck/issues
AppUpdatesURL=https://github.com/owlgorithm-research/owlcheck/releases
AppCopyright=© 2026 PΛTTRN
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription=OwlCheck installer
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OwlCheck-Setup-{#MyAppVersion}
SetupIconFile=..\app\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
WizardImageFile=installer\wizard-large-100.bmp,installer\wizard-large-150.bmp,installer\wizard-large-200.bmp
WizardSmallImageFile=installer\wizard-small-100.bmp,installer\wizard-small-150.bmp,installer\wizard-small-200.bmp
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
english.WelcomeLabel1=WELCOME TO OWLCHECK
english.WelcomeLabel2=This assistant will install [name/ver] on your computer.%n%nIt installs for your user only, without an administrator password, and doesn't change anything outside its own folder.
english.FinishedHeadingLabel=ALL SET!
english.FinishedLabel=OwlCheck is installed on your computer. You'll also find it in the Start menu.
english.FinishedLabelNoIcons=OwlCheck is installed on your computer.
spanish.WelcomeLabel1=BIENVENIDO A OWLCHECK
spanish.WelcomeLabel2=Este asistente va a instalar [name/ver] en tu computadora.%n%nSe instala solo para tu usuario, sin contraseña de administrador, y no cambia nada fuera de su carpeta.
spanish.FinishedHeadingLabel=¡TODO LISTO!
spanish.FinishedLabel=OwlCheck ya está instalado en tu computadora. También lo encuentras en el menú Inicio.
spanish.FinishedLabelNoIcons=OwlCheck ya está instalado en tu computadora.
brazilianportuguese.WelcomeLabel1=BEM-VINDO AO OWLCHECK
brazilianportuguese.WelcomeLabel2=Este assistente vai instalar o [name/ver] no seu computador.%n%nEle instala só para o seu usuário, sem pedir senha de administrador, e não altera nada fora da pasta dele.
brazilianportuguese.FinishedHeadingLabel=TUDO PRONTO!
brazilianportuguese.FinishedLabel=O OwlCheck foi instalado no seu computador. Você também encontra ele no menu Iniciar.
brazilianportuguese.FinishedLabelNoIcons=O OwlCheck foi instalado no seu computador.

[CustomMessages]
english.OpenOwlCheck=Open OwlCheck
spanish.OpenOwlCheck=Abrir OwlCheck
brazilianportuguese.OpenOwlCheck=Abrir o OwlCheck

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; on update, removes the previous version's libraries before copying the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; fonts used only by the setup window (loaded privately, never installed on the computer)
Source: "installer\fonts\Silkscreen-Bold.ttf"; Flags: dontcopy
Source: "installer\fonts\Rubik-Regular.ttf"; Flags: dontcopy
Source: "..\dist\OwlCheck\*"; DestDir: "{app}"; Excludes: "owlcheck-log.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:OpenOwlCheck}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the startup log the app writes (user data in %APPDATA%\OwlCheck is left alone)
Type: files; Name: "{app}\owlcheck-log.txt"

[Code]
const
  PAPER = $00ECF1F2;   { #F2F1EC, the app's paper color (TColor is BGR) }
  INK = $00111111;     { #111111 }
  SOFT = $004F5455;    { #55544F }
  FR_PRIVATE = $10;

function AddFontResourceEx(FileName: String; Flags: Cardinal; Reserved: Cardinal): Integer;
  external 'AddFontResourceExW@gdi32.dll stdcall';

procedure LoadFont(const FileName: String);
begin
  ExtractTemporaryFile(FileName);
  AddFontResourceEx(ExpandConstant('{tmp}\') + FileName, FR_PRIVATE, 0);
end;

procedure PixelTitle(Lbl: TNewStaticText; Size: Integer);
begin
  Lbl.Font.Name := 'Silkscreen';
  Lbl.Font.Style := [fsBold];
  Lbl.Font.Size := Size;
  Lbl.Font.Color := INK;
end;

procedure InitializeWizard;
var
  HeaderLine: TPanel;
begin
  LoadFont('Silkscreen-Bold.ttf');
  LoadFont('Rubik-Regular.ttf');

  { paper background everywhere, like the app }
  WizardForm.Color := PAPER;
  WizardForm.Font.Name := 'Rubik Light';
  WizardForm.WelcomePage.Color := PAPER;
  WizardForm.FinishedPage.Color := PAPER;
  WizardForm.InnerPage.Color := PAPER;
  WizardForm.MainPanel.Color := PAPER;
  WizardForm.TasksList.Color := PAPER;
  WizardForm.RunList.Color := PAPER;

  { titles in the app's pixel font }
  PixelTitle(WizardForm.WelcomeLabel1, 14);
  PixelTitle(WizardForm.FinishedHeadingLabel, 14);
  PixelTitle(WizardForm.PageNameLabel, 10);
  WizardForm.PageDescriptionLabel.Font.Color := SOFT;

  { thick ink line under the header instead of the thin etched one }
  WizardForm.Bevel1.Visible := False;
  HeaderLine := TPanel.Create(WizardForm);
  HeaderLine.Parent := WizardForm.Bevel1.Parent;
  HeaderLine.Left := WizardForm.Bevel1.Left;
  HeaderLine.Top := WizardForm.Bevel1.Top;
  HeaderLine.Width := WizardForm.Bevel1.Width;
  HeaderLine.Height := ScaleY(2);
  HeaderLine.BevelOuter := bvNone;
  HeaderLine.ParentBackground := False;
  HeaderLine.Color := INK;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { page titles in capitals, like the app's headings }
  WizardForm.PageNameLabel.Caption := AnsiUppercase(WizardForm.PageNameLabel.Caption);
end;
