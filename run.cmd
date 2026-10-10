@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.ps1 first.
    popd
    exit /b 2
)
".venv\Scripts\python.exe" watch.py %*
set "watchExitCode=%errorlevel%"
popd
exit /b %watchExitCode%
