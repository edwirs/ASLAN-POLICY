; Instalador del Agente ASLAN (Inno Setup 6). Lo compila construir_windows.ps1.
; - Se instala para el usuario (no pide administrador) en %LOCALAPPDATA%\Programs\ASLAN Agente.
; - Queda arrancando con Windows (minimizado) desde la carpeta Inicio del usuario: tiene que correr en la sesión del
;   usuario (no como servicio) para que las ventanas que piden una persona —captcha de Mapfre— se vean en pantalla.
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppId={{6C1F7B9E-3E4B-4E9B-9C0E-5A1D2B7F0A11}
AppName=Agente ASLAN
AppVersion={#Version}
AppPublisher=ASLAN MultiAgente de Seguros
DefaultDirName={localappdata}\Programs\ASLAN Agente
DefaultGroupName=ASLAN
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=salida
OutputBaseFilename=ASLAN-Agente-Setup
SetupIconFile=aslan.ico
UninstallDisplayIcon={app}\ASLAN Agente.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "dist\ASLAN Agente\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\Agente ASLAN"; Filename: "{app}\ASLAN Agente.exe"
Name: "{userprograms}\Agente ASLAN"; Filename: "{app}\ASLAN Agente.exe"
Name: "{userstartup}\Agente ASLAN"; Filename: "{app}\ASLAN Agente.exe"; Parameters: "--oculto"

[Run]
Filename: "{app}\ASLAN Agente.exe"; Description: "Abrir el Agente ASLAN ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM ""ASLAN Agente.exe"" /F"; Flags: runhidden; RunOnceId: "CerrarAgente"
