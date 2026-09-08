@echo off
REM ===================================================================
REM  DXRFID Bridge - DEMO mode (no RFID hardware needed)
REM
REM  Same as START-HERE.bat, but also runs a fake reader and a fake
REM  EventzFlow server, so you can click around a fully working
REM  dashboard on any PC. Nothing here touches real hardware.
REM ===================================================================
setlocal
cd /d "%~dp0"
title DXRFID Bridge (demo)

echo.
echo   ============================================
echo     DXRFID Bridge - DEMO MODE
echo     ^(fake reader, fake server, no hardware^)
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

set "DASH_PORT=5050"
set "READER_PORT=6688"
set "FAKE_API_PORT=9000"

echo   [..] Starting fake reader on port %READER_PORT%
start "DXRFID mock reader" /min %PY% "app\mock_reader.py" --port %READER_PORT%

echo   [..] Starting fake EventzFlow server on port %FAKE_API_PORT%
start "DXRFID mock api" /min %PY% "app\mock_eventzflow.py" --port %FAKE_API_PORT%

echo   [..] Starting dashboard on port %DASH_PORT%
start "DXRFID dashboard" /min %PY% "app\server.py" --port %DASH_PORT%

timeout /t 2 /nobreak >nul
start "" "http://localhost:%DASH_PORT%"

echo.
echo   ============================================
echo     Demo running.
echo.
echo     Dashboard:    http://localhost:%DASH_PORT%
echo     Fake server:  http://localhost:%FAKE_API_PORT%
echo.
echo     Try this:
echo       1. Press Connect ^(already points at the fake reader^)
echo       2. Settings tab - API URL:
echo            http://127.0.0.1:%FAKE_API_PORT%/events
echo          then Save Settings
echo       3. Test tab - Read Tags
echo       4. Dashboard - Auto-Forward - Turn On
echo.
echo     Press any key in THIS window to stop.
echo   ============================================
echo.
pause >nul

echo   Stopping...
taskkill /f /fi "WINDOWTITLE eq DXRFID dashboard*"   >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DXRFID mock reader*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq DXRFID mock api*"    >nul 2>&1
echo   Stopped.
timeout /t 1 /nobreak >nul
exit /b 0
