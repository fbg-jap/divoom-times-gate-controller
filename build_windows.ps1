param([switch]$SkipInstall, [string]$DistPath = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
if (-not $SkipInstall) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the dependencies.' }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath $DistPath packaging\DivoomKeeperStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'The build failed.' }
$studioOutput = Join-Path (Resolve-Path -LiteralPath $DistPath).Path 'DivoomKeeperStudio\DivoomKeeperStudio.exe'
Write-Host "Application: $studioOutput" -ForegroundColor Green
Write-Host 'Copy the entire DivoomKeeperStudio folder to distribute it.'
