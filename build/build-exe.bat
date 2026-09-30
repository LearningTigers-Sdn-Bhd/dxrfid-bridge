@echo off
REM Build dxrfid-bridge.exe — run on Windows from the dxrfid-bridge folder.
REM Needs 64-bit Python 3.9+ (the bundled ECRFID.dll is 64-bit).
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.9+ from python.org
    echo and tick "Add python.exe to PATH" on the first installer screen.
    pause
    exit /b 1
)

python -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 else 1)" || (
    echo This must be 64-bit Python — the vendor ECRFID.dll is 64-bit.
    pause
    exit /b 1
)

python -m pip install --quiet --disable-pip-version-check pyinstaller || (
    echo Could not install PyInstaller.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean build\dxrfid-bridge.spec --distpath dist --workpath build\work
if errorlevel 1 (
    echo Build failed — see output above.
    pause
    exit /b 1
)

echo.
echo Built: dist\dxrfid-bridge.exe
echo Test it: dist\dxrfid-bridge.exe --open
echo.
pause
