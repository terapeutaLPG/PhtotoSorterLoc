@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>&1
if errorlevel 1 (
    set "PHOTOSORTER_PYTHON=python"
) else (
    set "PHOTOSORTER_PYTHON=py -3"
)

%PHOTOSORTER_PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo Install Python 3.11 or newer, then run this script again.
    goto :error
)

%PHOTOSORTER_PYTHON% -m venv .venv
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto :error
set "PYINSTALLER_CONFIG_DIR=%CD%\.cache\pyinstaller"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist\windows --workpath build\windows packaging\windows.spec
if errorlevel 1 goto :error

echo.
echo Ready: dist\windows\PhotoSorter.exe
exit /b 0

:error
echo Build failed. See the error above.
exit /b 1
