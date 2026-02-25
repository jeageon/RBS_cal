@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "HOST=127.0.0.1"
set "PORT=8000"
set "MAX_PORT=8010"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%LOG_FILE%" del "%LOG_FILE%" >nul 2>&1

echo [RBS_cal] start
call :log "== RBS_cal WebUI start =="
call :log "Project directory: %PROJECT_DIR%"

if not exist "%PROJECT_DIR%\app.py" (
  call :log "ERROR: app.py not found"
  echo app.py not found. Place the .bat beside app.py.
  goto fail
)

cd /d "%PROJECT_DIR%" || goto fail_cd

if exist "%VENV_DIR%\Scripts\python.exe" (
  set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
  call :log "Use venv python"
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
      goto fail
    )
    set "PYTHON_EXE=python"
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  call :log "Create virtual environment"
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if errorlevel 1 goto fail_venv
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" goto fail_venv_bin

call :log "Install dependencies"
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_pip
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_requirements

call :log "Find OSTIR"
if defined OSTIR_BIN if exist "%OSTIR_BIN%" (
  call :log "OSTIR_BIN set: %OSTIR_BIN%"
) else (
  for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fP"
  if defined OSTIR_BIN (
    call :log "OSTIR found: %OSTIR_BIN%"
  ) else (
    call :log "WARNING: OSTIR not found. Server starts, prediction may fail."
  )
)

call :log "Find free port"
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
echo RBS_cal WebUI will run at: %URL%
echo Logs: %LOG_FILE%
echo.

start "" "%URL%"

"%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail_flask

goto done

:fail_cd
call :log "ERROR: cannot change directory"
goto fail

:fail_venv
call :log "ERROR: failed to create virtual environment"
goto fail

:fail_venv_bin
call :log "ERROR: venv python not found"
goto fail

:fail_pip
call :log "ERROR: failed to upgrade pip"
goto fail

:fail_requirements
call :log "ERROR: requirements install failed"
goto fail

:fail_port
call :log "ERROR: no free port in range %PORT%-%MAX_PORT%"
goto fail

:fail_flask
call :log "ERROR: Flask execution failed. check log: %LOG_FILE%"
goto fail

:fail
type "%LOG_FILE%"
echo.
echo.
echo [RBS_cal] 실행 실패. 위 로그를 확인하세요.
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
