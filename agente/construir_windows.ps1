# Construye el instalador del Agente ASLAN en un PC con Windows (o lo hace GitHub Actions: .github/workflows/agente-windows.yml).
#
#   Requisitos: Python 3.12 (python.org, con tcl/tk) e Inno Setup 6 (https://jrsoftware.org/isdl.php).
#   Uso, desde la carpeta agente\ :   powershell -ExecutionPolicy Bypass -File construir_windows.ps1
#   Resultado:                        agente\salida\ASLAN-Agente-Setup.exe
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -m venv .venv-build
.\.venv-build\Scripts\python -m pip install --upgrade pip
.\.venv-build\Scripts\python -m pip install -r requirements.txt

# Carpeta (no un solo .exe): arranca más rápido y los antivirus la marcan menos.
.\.venv-build\Scripts\pyinstaller --noconfirm --clean --windowed --name "ASLAN Agente" `
    --icon aslan.ico --add-data "aslan.ico;." `
    --collect-all playwright --collect-submodules websockets `
    aslan_agente.py

$version = (Select-String -Path aslan_agente.py -Pattern "^VERSION = '(.+)'").Matches[0].Groups[1].Value
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'No se encontró Inno Setup 6 (ISCC.exe).' }
& $iscc "/DVersion=$version" instalador.iss
Write-Host "Listo: $PSScriptRoot\salida\ASLAN-Agente-Setup.exe"
