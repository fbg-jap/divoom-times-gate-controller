param([switch]$Demo)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the dependencies.' }
}
if ($Demo) {
    & .\.venv\Scripts\python.exe app.py --demo
} else {
    & .\.venv\Scripts\python.exe app.py
}
