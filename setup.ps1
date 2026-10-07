# Creates a private .venv inside this project and installs requirements.txt into it.
# Nothing is installed globally, and no other project or Python installation is changed.
param([string]$Python)
$ErrorActionPreference = 'Stop'

function Test-Base([string]$exe, [string[]]$pre) {
    # Usable base interpreter: Python 3.10+ with tkinter and venv. Returns its real path or $null.
    try {
        $found = & $exe @pre -c 'import sys, tkinter, venv; assert sys.version_info >= (3, 10); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -Last 1).Trim() }
    } catch { }
    return $null
}

$base = $null
if ($Python) {
    $base = Test-Base $Python @()
    if (-not $base) { throw "Not a usable Python 3.10+ with tkinter: $Python" }
}
if (-not $base -and $env:MRC_PYTHON) { $base = Test-Base $env:MRC_PYTHON @() }
if (-not $base -and (Get-Command py -ErrorAction SilentlyContinue)) { $base = Test-Base 'py' @('-3') }
if (-not $base) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    # The WindowsApps "python" is a Microsoft Store placeholder, not an interpreter.
    if ($command -and $command.Source -notlike '*\WindowsApps\*') { $base = Test-Base $command.Source @() }
}
if (-not $base) {
    throw @'
No usable Python was found. Nothing was installed.
Install Python 3.10 or newer for Windows from https://www.python.org/downloads/
(keep the default "tcl/tk and IDLE" option ticked), then run Setup.bat again.
Or run:  powershell -ExecutionPolicy Bypass -File setup.ps1 -Python "C:\path\to\python.exe"
'@
}

$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
Write-Host "Base Python : $base"
Write-Host "Project venv: $venv"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $base -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install requirements into .venv (internet access is needed once).' }
& $venvPython -c 'import tkinter, openpyxl; print(openpyxl.__version__)'
if ($LASTEXITCODE -ne 0) { throw '.venv was created but tkinter/openpyxl cannot be imported.' }
Write-Host 'Setup complete. Start the checker with "Start M0.bat".'
