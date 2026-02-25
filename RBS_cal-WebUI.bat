@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "LOG_FILE=%PROJECT_DIR%\\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\\.venv"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "HOST=127.0.0.1"
set "PORT=8000"
set "MAX_PORT=8010"

if exist "%LOG_FILE%" del "%LOG_FILE%" >nul 2>&1
call :log "== RBS_cal WebUI start =="
call :log "Project directory: %PROJECT_DIR%"

if not exist "%PROJECT_DIR%\\app.py" (
  call :log "ERROR: app.py not found"
  echo app.py not found. Make sure this file is next to the .bat file.
  goto fail
)

cd /d "%PROJECT_DIR%" || goto fail_cd

call :log "Step 1) Resolve Python"
if exist "%VENV_DIR%\\Scripts\\python.exe" (
  set "PYTHON_EXE=%VENV_DIR%\\Scripts\\python.exe"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      call :log "ERROR: Python 3 not found"
      echo Python 3 is not found on PATH.
      echo Install Python 3 and re-run.
      goto fail
    )
    set "PYTHON_EXE=python"
  )
)

call :log "Use python: %PYTHON_EXE%"

if not exist "%VENV_DIR%\\Scripts\\python.exe" (
  call :log "Step 2) Create virtual environment"
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if errorlevel 1 goto fail_venv
)

set "PYTHON_EXE=%VENV_DIR%\\Scripts\\python.exe"
if not exist "%PYTHON_EXE%" goto fail_venv_bin

call :log "Step 3) Install dependencies"
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_pip
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\\requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_requirements

call :log "Step 4) Locate OSTIR (optional)"
if defined OSTIR_BIN if exist "%OSTIR_BIN%" (
  call :log "OSTIR_BIN (user env): %OSTIR_BIN%"
) else (
  for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fP"
  if defined OSTIR_BIN (
    call :log "OSTIR found: %OSTIR_BIN%"
  ) else (
    call :log "WARNING: OSTIR not found. Web server starts, but prediction will fail."
  )
)

call :log "Step 5) Find free port (8000~8010)"
set "PORT_SEARCH=%PORT%"
:port_scan
if %PORT_SEARCH% gtr %MAX_PORT% goto fail_port
netstat -ano | findstr ":%PORT_SEARCH% " >nul 2>&1
if not errorlevel 1 (
  set /a PORT_SEARCH=%PORT_SEARCH%+1
  goto port_scan
)
set "PORT=%PORT_SEARCH%"
set "URL=http://%HOST%:%PORT%"

call :log "Start URL: %URL%"
echo.
echo RBS_cal WebUI will run on: %URL%
echo Logs: %LOG_FILE%
echo.

call :log "Step 6) Start Flask"
start "" /B powershell -NoProfile -WindowStyle Hidden -Command "$ok=0; for($i=0;$i -lt 90;$i++){ try { $c=New-Object System.Net.Sockets.TcpClient; $c.Connect('%HOST%',[int]'%PORT%'); $c.Close(); $ok=1; break } catch { Start-Sleep -Milliseconds 250 } }; if($ok -eq 1){ Start-Process '%URL%' }"

set "HOST=%HOST%"
set "PORT=%PORT%"
"%PYTHON_EXE%" "%PROJECT_DIR%\\app.py" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_flask

goto done

:fail_cd
call :log "ERROR: cannot change directory"
goto fail

:fail_venv
call :log "ERROR: failed to create virtual environment"
goto fail

:fail_venv_bin
call :log "ERROR: virtualenv python not found"
goto fail

:fail_pip
call :log "ERROR: failed to upgrade pip"
goto fail

:fail_requirements
call :log "ERROR: requirements install failed"
goto fail

:fail_port
call :log "ERROR: no free port between 8000 and 8010"
goto fail

:fail_flask
call :log "ERROR: Flask execution failed. see %LOG_FILE%"
goto fail

:fail
type "%LOG_FILE%"
echo.
echo.
echo 실행 실패. 위 로그를 확인하세요.
pause
exit /b 1

:done
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
