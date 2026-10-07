# Builds the portable Windows package:
#   dist\Auraplex_Material_Stock_Checker\                      (exe, _internal, README.txt)
#   dist\Auraplex_Material_Stock_Checker_v<version>_Portable.zip
# Uses only the project .venv (run Setup.bat first). Nothing is installed globally.
param([string]$Version = '1.0.0')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$name = 'Auraplex_Material_Stock_Checker'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project .venv not found. Run Setup.bat first.' }

function Invoke-Python {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "python $($args -join ' ') failed with exit code $LASTEXITCODE" }
}

Write-Host '== 1/5 PyInstaller in the project .venv'
& $python -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(\"PyInstaller\") else 1)'
if ($LASTEXITCODE -ne 0) { Invoke-Python -m pip install --disable-pip-version-check 'pyinstaller>=6.6,<7' }
Invoke-Python -c 'import sys, PyInstaller, openpyxl, tkinter; print(sys.version.split()[0], PyInstaller.__version__, openpyxl.__version__)'

Write-Host '== 2/5 Clean previous output'
foreach ($folder in 'build', 'dist') {
    $path = Join-Path $root $folder
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

Write-Host '== 3/5 Build (onedir, windowed)'
Invoke-Python -m PyInstaller --noconfirm --clean --onedir --windowed --name $name `
    --distpath (Join-Path $root 'dist') --workpath (Join-Path $root 'build') --specpath (Join-Path $root 'build') `
    (Join-Path $root 'app.py')

Write-Host '== 4/5 Distribution folder'
$app = Join-Path $root "dist\$name"
if (-not (Test-Path -LiteralPath (Join-Path $app "$name.exe") -PathType Leaf)) { throw 'Build did not produce the executable.' }
Copy-Item -LiteralPath (Join-Path $root 'PORTABLE_USER_GUIDE.txt') -Destination (Join-Path $app 'README.txt')
# Only the application belongs in the package: no workbooks, sources or tests.
$unexpected = Get-ChildItem -LiteralPath $app -Recurse -File | Where-Object { $_.Extension -in '.xlsx', '.xlsm', '.xls', '.csv' -or $_.Name -like '~$*' }
if ($unexpected) { throw "Unexpected data files in the package: $($unexpected.FullName -join ', ')" }

Write-Host '== 5/5 ZIP'
$zipBase = Join-Path $root "dist\${name}_v${Version}_Portable"
Invoke-Python -c "import shutil, sys; print(shutil.make_archive(sys.argv[1], 'zip', root_dir=sys.argv[2], base_dir=sys.argv[3]))" $zipBase (Join-Path $root 'dist') $name
$zip = Get-Item -LiteralPath "$zipBase.zip"
Write-Host ("Done: {0}  ({1:N1} MB)" -f $zip.FullName, ($zip.Length / 1MB))
