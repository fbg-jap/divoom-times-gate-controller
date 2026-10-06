param([switch]$SkipInstall, [string]$DistPath = 'dist', [ValidateSet('qt', 'web')][string]$Ui = 'qt')
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
$appName = if ($Ui -eq 'web') { 'DivoomKeeperStudioWeb' } else { 'DivoomKeeperStudio' }
if ($Ui -eq 'web' -and -not $SkipInstall) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the server dependencies.' }
}
if ($Ui -eq 'web' -and -not (Test-Path -LiteralPath 'web\dist\index.html')) {
    Push-Location web
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'The web build failed.' }
    } finally { Pop-Location }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath $DistPath "packaging\$appName.spec"
if ($LASTEXITCODE -ne 0) { throw 'The build failed.' }
$studioOutput = Join-Path (Resolve-Path -LiteralPath $DistPath).Path "$appName\$appName.exe"
Write-Host "Application: $studioOutput" -ForegroundColor Green
Write-Host "Copy the entire $appName folder to distribute it."
