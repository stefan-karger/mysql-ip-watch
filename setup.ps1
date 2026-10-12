[CmdletBinding()]
param([string]$PythonVersion = '3.11')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPath = Join-Path $root '.venv'
$pythonExe = Join-Path $root '.venv\Scripts\python.exe'
$uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $pythonExe)) {
    if ($uvCommand) {
        & $uvCommand.Source venv --python $PythonVersion $venvPath
        if ($LASTEXITCODE -ne 0) { throw "uv could not create the Python $PythonVersion environment. Check internet access and run setup again." }
    } else {
        $pyCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
        if (-not $pyCommand) { throw 'Install uv, or Python with the py launcher, then run setup again.' }
        & $pyCommand.Source "-$PythonVersion" -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw "Install uv, or Python $PythonVersion with the py launcher, then run setup again." }
    }
}
if ($uvCommand) {
    & $uvCommand.Source pip install --python $pythonExe -r (Join-Path $root 'requirements.txt')
} else {
    & $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$configPath = Join-Path $root 'config.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath (Join-Path $root 'config.example.json') -Destination $configPath
    Write-Output 'Created config.json from config.example.json. Edit it with your database details and target IP.'
}
Write-Output 'Setup complete. Follow SETUP.md, run .\run.cmd --check, then .\run.cmd'
