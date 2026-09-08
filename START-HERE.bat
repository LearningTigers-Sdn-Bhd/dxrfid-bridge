@echo off
REM ===================================================================
REM  DXRFID Bridge - one-click start for Windows
REM
REM  Double-click this file. It starts the dashboard (and the USB
REM  encoder helper) and opens your browser. Close this window to stop
REM  everything.
REM
REM  No installation needed beyond Python itself - this project uses
REM  only the Python standard library.
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
if not defined PYVER (
  echo   [X] Found Python but could not run it. Try reinstalling Python.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>nul
if errorlevel 1 (
  echo   [X] Python %PYVER% is too old - this project needs 3.9 or newer.
  echo       Get a current version from https://www.python.org/downloads/
  pause
  exit /b 1
)
echo   [ok] Python %PYVER%

REM ---- 2. Ports -------------------------------------------------------
set "DASH_PORT=5050"
set "ENC_PORT=7000"

call :FreePort %DASH_PORT% "dashboard"
call :FreePort %ENC_PORT% "encoder helper"

REM ---- 3. Start the encoder helper (registration desk only) -----------
REM Harmless on a gate PC: it simply reports "no encoder found".
echo   [..] Starting USB encoder helper on port %ENC_PORT%
start "DXRFID encoder helper" /min %PY% "app\encoder_service.py" --port %ENC_PORT%

REM ---- 4. Start the dashboard ----------------------------------------
echo   [..] Starting dashboard on port %DASH_PORT%
start "DXRFID dashboard" /min %PY% "app\server.py" --port %DASH_PORT%

REM Give the servers a moment to bind before the browser opens.
timeout /t 2 /nobreak >nul

REM ---- 5. Open the browser -------------------------------------------
echo   [ok] Opening http://localhost:%DASH_PORT%
start "" "http://localhost:%DASH_PORT%"

echo.
echo   ============================================
echo     Running.
echo.
echo     Dashboard:  http://localhost:%DASH_PORT%
echo     Encoder:    http://localhost:%ENC_PORT%
echo.
echo     First time here? Open the Settings tab and
echo     enter your reader's IP and the EventzFlow
echo     API URL, then press Save Settings.
echo.
echo     Press any key in THIS window to stop.
echo   ============================================
echo.
pause >nul

echo   Stopping...
taskkill /f /fi "WINDOWTITLE eq DXRFID dashboard*"      >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DXRFID encoder helper*" >nul 2>&1
echo   Stopped.
timeout /t 1 /nobreak >nul
exit /b 0

REM ---------------------------------------------------------------------
:FreePort
REM %1 = port, %2 = label. Offers to kill whatever is already listening.
set "INUSE="
for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr /r /c:"LISTENING" ^| findstr /c:":%~1 "') do set "INUSE=%%p"
if defined INUSE (
  echo   [!] Port %~1 ^(%~2^) is already in use by process %INUSE%.
  choice /c YN /n /m "      Stop that process and continue? [Y/N] "
  if errorlevel 2 (
    echo       Leaving it alone - %~2 may fail to start.
  ) else (
    taskkill /f /pid %INUSE% >nul 2>&1
    echo       Stopped process %INUSE%.
  )
)
goto :eof
