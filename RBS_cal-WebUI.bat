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

if exist "%LOG_FILE%" del "%LOG_FILE%" >nul 2>&1

call :log "== RBS_cal WebUI start =="
call :log "Project directory: %PROJECT_DIR%"

echo [RBS_cal] start

echo %LOG_FILE%

if not exist "%PROJECT_DIR%\app.py" (
  echo ERROR: app.py not found.
  goto fail
)

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
  echo ERROR: cannot change directory.
  goto fail
)

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
      echo ERROR: Python 3 not found.
      goto fail
    )
    set "PYTHON_EXE=python"
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo create venv.
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if errorlevel 1 goto fail
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" goto fail

echo install base libs...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail

call :log "Check OSTIR"
if defined OSTIR_BIN if exist "%OSTIR_BIN%" (
  echo OSTIR_BIN=%OSTIR_BIN%
) else (
  for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fP"
  if defined OSTIR_BIN (
    echo OSTIR=%OSTIR_BIN%
  ) else (
    echo WARNING: OSTIR not found.
  )
)

set "PORT_SEARCH=%PORT%"
:find_port
if %PORT_SEARCH% gtr %MAX_PORT% goto fail
netstat -ano | findstr ":%PORT_SEARCH% " >nul 2>&1
if not errorlevel 1 (
  set /a PORT_SEARCH=%PORT_SEARCH%+1
  goto find_port
)
set "PORT=%PORT_SEARCH%"
set "URL=http://%HOST%:%PORT%"

echo URL=%URL%

echo Open browser...
start "" "%URL%"

echo Run app.py ...
"%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail

goto done

:fail
if exist "%LOG_FILE%" type "%LOG_FILE%"
echo.
echo FAILED. Keep this window open.
pause
exit /b 1

goto :eof

:done
call :log "Server stopped"
echo DONE.
pause
exit /b 0

:log
set "TS=%date% %time%"
echo [%TS%] %~1>>"%LOG_FILE%"
exit /b 0
