@echo off
REM ===================================================================
REM  DXRFID Bridge - DEMO mode (no RFID hardware needed)
REM
REM  Runs the bridge against a fake EventzFlow backend that speaks the
REM  real RFID device contract, plus a fake gate reader on TCP. You can
REM  click through the full desk + gate flow on any PC.
REM ===================================================================
setlocal
cd /d "%~dp0"
title DXRFID Bridge (demo)

echo.
echo   ============================================
echo     DXRFID Bridge - DEMO MODE
echo     ^(fake backend, fake gate, no hardware^)
echo   ============================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo   [X] Python is not installed ^(or not on PATH^).
  echo       Get it from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)
echo   [ok] Python found

set "PORT=5050"
set "GATE_PORT=6688"
set "API_PORT=9100"
set "API_KEY=demo-key"

echo   [..] Starting fake gate reader on port %GATE_PORT%
start "DXRFID mock gate" /min %PY% "app\mock_reader.py" --port %GATE_PORT%

echo   [..] Starting mock EventzFlow backend on port %API_PORT%
start "DXRFID mock backend" /min %PY% "app\mock_rfid_backend.py" --port %API_PORT% --api-key %API_KEY%

echo   [..] Starting bridge on port %PORT%
start "DXRFID bridge" /min %PY% "app\server.py" --port %PORT%

timeout /t 2 /nobreak >nul
start "" "http://localhost:%PORT%"

echo.
echo   ============================================
echo     Demo running.
echo.
echo     Console:       http://localhost:%PORT%
echo     Mock backend:  http://localhost:%API_PORT%  ^(ticket list^)
echo.
echo     Try this:
echo       1. Settings -^> Backend URL  http://127.0.0.1:%API_PORT%
echo          API key  %API_KEY%  -^> Save -^> Test connection
echo       2. Settings -^> Gate IP 127.0.0.1 port %GATE_PORT% -^> Save
echo       3. Open the mock backend page and copy a ticket UUID
echo       4. Desk tab -^> paste it in "Scan QR" -^> Enter
echo       5. Link a sticker ^(type any 16-hex UID^), then Gate -^>
echo          Start watch and copy that UID when the mock shows tags
echo.
echo     Press any key in THIS window to stop.
echo   ============================================
echo.
pause >nul

echo   Stopping...
taskkill /f /fi "WINDOWTITLE eq DXRFID bridge*"       >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DXRFID mock gate*"    >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DXRFID mock backend*" >nul 2>&1
echo   Stopped.
timeout /t 1 /nobreak >nul
exit /b 0
