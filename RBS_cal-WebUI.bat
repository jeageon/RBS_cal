@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PROJECT_NAME=RBS_cal"
set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"
set "MAX_PORT=8010"

call :log "== RBS_cal WebUI start =="
call :log "Project directory: %PROJECT_DIR%"

if not exist "%PROJECT_DIR%\app.py" (
  call :log "ERROR: app.py not found"
  echo app.py not found. Make sure this file is next to the .bat file.
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
  call :log "ERROR: cannot change directory"
  pause
  exit /b 1
)

call :log "Step 1) Resolve Python"
if exist "%VENV_DIR%\Scripts\python.exe" (
  set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      call :log "ERROR: Python3 not found"
      echo Python 3 is not found on PATH.
      echo Install Python 3 and re-run.
      pause
      exit /b 1
    )
    set "PYTHON_EXE=python"
  )
)

call :log "Use python: %PYTHON_EXE%"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  call :log "Step 2) Create virtual environment"
  %PYTHON_EXE% %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    call :log "ERROR: venv creation failed"
    type "%LOG_FILE%"
    pause
    exit /b 1
  )
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  call :log "ERROR: venv python not found"
  pause
  exit /b 1
)

call :log "Step 3) Install dependencies"
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  call :log "ERROR: pip upgrade failed"
  type "%LOG_FILE%"
  pause
  exit /b 1
)
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  call :log "ERROR: requirements installation failed"
  type "%LOG_FILE%"
  pause
  exit /b 1
)

call :log "Step 4) Find OSTIR binary"
set "FOUND_OSTIR="
if defined OSTIR_BIN if exist "%OSTIR_BIN%" set "FOUND_OSTIR=%OSTIR_BIN%"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir.exe" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir.exe"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir"
if not defined FOUND_OSTIR if defined ProgramW6432 if exist "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%p in ('dir /b /s "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" 2^>nul') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fp"
)
if not defined FOUND_OSTIR if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%p in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" 2^>nul') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fp"
)
if not defined FOUND_OSTIR where ostir >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%p in ('where ostir') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fp"
)
if defined FOUND_OSTIR (
  set "OSTIR_BIN=%FOUND_OSTIR%"
  call :log "Found OSTIR: %FOUND_OSTIR%"
) else (
  call :log "WARNING: OSTIR not found. Prediction may fail."
  echo OSTIR not found. Set OSTIR_BIN if needed.
)

call :log "Step 5) Select port"
set "PORT_SEARCH=%APP_PORT%"
:port_scan
if %PORT_SEARCH% gtr %MAX_PORT% (
  call :log "ERROR: no free port between %APP_PORT% and %MAX_PORT%"
  pause
  exit /b 1
)
netstat -ano | findstr ":%PORT_SEARCH% " >nul 2>&1
if errorlevel 1 goto port_found
set /a PORT_SEARCH=%PORT_SEARCH%+1
goto port_scan

:port_found
set "APP_PORT=%PORT_SEARCH%"
set "URL=http://%APP_HOST%:%APP_PORT%"
set "HOST=%APP_HOST%"
set "PORT=%APP_PORT%"

call :log "Start URL: %URL%"
echo.
echo RBS_cal WebUI will run on: %URL%
echo Logs: %LOG_FILE%
echo.

call :log "Step 6) Start Flask"
start "" /B powershell -NoProfile -Command "$ready=0; for($i=0; $i -lt 90; $i++){ try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('%APP_HOST%',[int]'%APP_PORT%'); $c.Close(); $ready=1; break } catch { Start-Sleep -Milliseconds 250 } }; if($ready -eq 1){ Start-Process '%URL%' }"
"%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  call :log "ERROR: Flask execution failed. see %LOG_FILE%"
  type "%LOG_FILE%"
  pause
  exit /b 1
)

call :log "Server stopped"
pause
exit /b 0

:log
set "TS=%date% %time%"
echo [%TS%] %~1
if defined LOG_FILE (
  echo [%TS%] %~1>>"%LOG_FILE%"
)
goto :eof
