param([switch]$SmokeTest)
$ErrorActionPreference = 'Stop'
# Order: explicit override, then the project's own .venv created by Setup.bat. No machine-specific paths.
$taskCandidates = @(
    $env:MRC_PYTHON,
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
)
$taskPython = $null
foreach ($taskCandidate in $taskCandidates) {
    if ($taskCandidate -and (Test-Path -LiteralPath $taskCandidate -PathType Leaf)) {
        $taskPython = $taskCandidate
        break
    }
}
if (-not $taskPython) {
    throw 'This computer is not set up yet. Double-click Setup.bat once (it creates .venv in this folder; nothing is installed globally), then start again. See README.md.'
}
& $taskPython -c 'import tkinter, openpyxl'
if ($LASTEXITCODE -ne 0) {
    throw "The Python at $taskPython cannot import tkinter and openpyxl. Run Setup.bat again, or delete the .venv folder and run Setup.bat. Nothing was installed."
}
if ($SmokeTest) {
    & $taskPython (Join-Path $PSScriptRoot 'app.py') --smoke-test
} else {
    & $taskPython (Join-Path $PSScriptRoot 'app.py')
}
if ($LASTEXITCODE -ne 0) { throw "The checker exited with code $LASTEXITCODE" }
