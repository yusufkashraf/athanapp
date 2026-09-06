#define MyAppName "Athan"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Yusuf Kashraf"
#define MyAppExeName "Athan.exe"

[Setup]
AppId={{7F2D8B5E-5E9B-4A5D-9C8D-6A6F9F5B2A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\Athan
DefaultGroupName=Athan

OutputDir=installer
OutputBaseFilename=AthanSetup-{#MyAppVersion}

Compression=lzma
SolidCompression=yes

WizardStyle=modern

UninstallDisplayName=Athan
Uninstallable=yes

ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; \
    Flags: unchecked

[Files]
Source: "dist\app.exe"; \
    DestDir: "{app}"; \
    DestName: "{#MyAppExeName}"; \
    Flags: ignoreversion

[Icons]
Name: "{group}\Athan"; \
    Filename: "{app}\{#MyAppExeName}"

Name: "{autodesktop}\Athan"; \
    Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Launch Athan"; \
    Flags: nowait postinstall skipifsilent