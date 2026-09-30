@echo off
REM ===================================================================
REM  DXRFID Bridge - one-click start for Windows
REM
REM  Double-click this file. It starts the bridge console and opens your
REM  browser. Close this window (or press a key) to stop.
REM
REM  No installation needed beyond Python itself - the bridge uses only
REM  the Python standard library. The USB encoder support is built in;
REM  no separate helper window anymore.
REM ===================================================================
setlocal
cd /d "%~dp0"
title DXRFID Bridge

echo.
echo   ============================================
echo     DXRFID Bridge
echo   ============================================
echo.

REM ---- 1. Find Python -------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo   [X] Python is not installed ^(or not on PATH^).
  echo.
  echo       Install Python 3.9 or newer from:
  echo           https://www.python.org/downloads/
  echo.
  echo       IMPORTANT: on the first installer screen, tick
  echo       "Add python.exe to PATH" before clicking Install.
  echo.
  pause
  exit /b 1
)

for /f "delims=" %%v in ('%PY% -c "import sys;print('%%d.%%d'%%sys.version_info[:2])" 2^>nul') do set "PYVER=%%v"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>nul
if errorlevel 1 (
  echo   [X] Python %PYVER% is too old - this project needs 3.9 or newer.
  echo       Get a current version from https://www.python.org/downloads/
  pause
  exit /b 1
)
echo   [ok] Python %PYVER%

REM ---- 2. Port ----------------------------------------------------------
set "PORT=5050"
set "INUSE="
for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr /r /c:"LISTENING" ^| findstr /c:":%PORT% "') do set "INUSE=%%p"
if defined INUSE (
  echo   [!] Port %PORT% is already in use by process %INUSE%.
  choice /c YN /n /m "      Stop that process and continue? [Y/N] "
  if errorlevel 2 (
    echo       Leaving it alone - the bridge may fail to start.
  ) else (
    taskkill /f /pid %INUSE% >nul 2>&1
    echo       Stopped process %INUSE%.
  )
)

REM ---- 3. Start the bridge ---------------------------------------------
echo   [..] Starting bridge on port %PORT%
start "DXRFID bridge" /min %PY% "app\server.py" --port %PORT%

timeout /t 2 /nobreak >nul
echo   [ok] Opening http://localhost:%PORT%
start "" "http://localhost:%PORT%"

echo.
echo   ============================================
echo     Running.
echo.
echo     Console:  http://localhost:%PORT%
echo.
echo     First time? Open the Settings tab:
echo       1. Backend URL + RFID API key -^> Save -^> Test connection
echo       2. Gate IP + port -^> Save
echo       3. Printer address -^> Test printer
echo.
echo     Press any key in THIS window to stop.
echo   ============================================
echo.
pause >nul

echo   Stopping...
taskkill /f /fi "WINDOWTITLE eq DXRFID bridge*" >nul 2>&1
echo   Stopped.
timeout /t 1 /nobreak >nul
exit /b 0
