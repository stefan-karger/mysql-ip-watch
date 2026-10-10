[CmdletBinding()]
param([string]$PythonVersion = '3.11')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pythonExe = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & py "-$PythonVersion" -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ with the py launcher, then run setup again.' }
}
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Output 'Setup complete. Follow SETUP.md, run .\run.cmd --check, then .\run.cmd'
