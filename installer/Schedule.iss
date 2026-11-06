[Setup]
AppId={{B35937E4-C453-4EF7-A030-08EA295E9F52}
AppName=Расписание
AppVersion=1.0.0
AppPublisher=Расписание
DefaultDirName={localappdata}\Programs\ScheduleDesktop
DefaultGroupName=Расписание
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=Schedule-Setup-1.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Schedule.exe
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: checkedonce

[Files]
Source: "..\dist\Schedule\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "tools\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Расписание"; Filename: "{app}\Schedule.exe"
Name: "{autodesktop}\Расписание"; Filename: "{app}\Schedule.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Schedule.exe"; Description: "Запустить Расписание"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
             RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)) and
             (Version <> '') and (Version <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if not HasWebView then begin
    WizardForm.StatusLabel.Caption := 'Установка Microsoft WebView2. Требуется подключение к интернету...';
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
      Result := 'Не удалось запустить установку Microsoft WebView2.'
    else if not HasWebView then
      Result := 'Microsoft WebView2 не установлен. Проверьте подключение к интернету и повторите установку. Код: ' + IntToStr(Code);
  end;
end;
