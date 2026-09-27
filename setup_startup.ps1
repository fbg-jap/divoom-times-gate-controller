param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'dist\DivoomKeeperStudio\DivoomKeeperStudio.exe'
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ($Disable) {
    Remove-ItemProperty -LiteralPath $key -Name DivoomKeeperStudio -ErrorAction SilentlyContinue
    Write-Output 'Autoarranque de Studio desactivado.'
} else {
    if (-not (Test-Path -LiteralPath $exe)) { throw "Primero compila la aplicación: $exe" }
    New-Item -Path $key -Force | Out-Null
    New-ItemProperty -LiteralPath $key -Name DivoomKeeperStudio -Value ('"' + $exe + '" --minimized') -PropertyType String -Force | Out-Null
    Write-Output 'Autoarranque de Studio activado.'
}
