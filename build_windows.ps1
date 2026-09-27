param([switch]$SkipInstall, [string]$DistPath = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
}
if (-not $SkipInstall) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath $DistPath packaging\DivoomKeeperStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'La compilación ha fallado.' }
$studioOutput = Join-Path (Resolve-Path -LiteralPath $DistPath).Path 'DivoomKeeperStudio\DivoomKeeperStudio.exe'
Write-Host "Aplicación: $studioOutput" -ForegroundColor Green
Write-Host 'Copia la carpeta DivoomKeeperStudio completa para distribuirla.'
