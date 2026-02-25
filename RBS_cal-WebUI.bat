@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "HOST=127.0.0.1"
set "DEFAULT_PORT=8000"
set "MAX_PORT=8010"

if not exist "%PROJECT_DIR%\app.py" (
  echo ERROR: RBS project directory is invalid: %PROJECT_DIR%
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
  echo ERROR: Failed to change working directory.
  pause
  exit /b 1
)

> "%LOG_FILE%" echo [%date% %time%] RBS_cal WebUI start

echo [%date% %time%] Resolve python interpreter >> "%LOG_FILE%"
if exist "%VENV_DIR%\Scripts\python.exe" (
  set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
  set "PY_ARGS="
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PY_ARGS=-3"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Python 3 not found in PATH.
      pause
      exit /b 1
    )
    set "PYTHON_EXE=python"
    set "PY_ARGS="
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [%date% %time%] Create virtualenv: %VENV_DIR% >> "%LOG_FILE%"
  "%PYTHON_EXE%" %PY_ARGS% -m venv "%VENV_DIR%" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo ERROR: Failed to create venv.
    type "%LOG_FILE%"
    pause
    exit /b 1
  )
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo ERROR: Virtualenv python was not created.
  pause
  exit /b 1
)

echo [%date% %time%] Update pip packages >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: Failed to upgrade pip.
  type "%LOG_FILE%"
  pause
  exit /b 1
)

echo [%date% %time%] Install requirements >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: requirements.txt install failed.
  type "%LOG_FILE%"
  pause
  exit /b 1
)

set "FOUND_OSTIR="
if defined OSTIR_BIN if exist "%OSTIR_BIN%" set "FOUND_OSTIR=%OSTIR_BIN%"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir.exe" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir.exe"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir"
if not defined FOUND_OSTIR if exist "%USERPROFILE%\.local\bin\ostir" set "FOUND_OSTIR=%USERPROFILE%\.local\bin\ostir"
if not defined FOUND_OSTIR if exist "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%P in ('dir /b /s "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" 2^>nul') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR if exist "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" 2^>nul') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR where ostir >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('where ostir') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fP"
)

if defined FOUND_OSTIR (
  set "OSTIR_BIN=%FOUND_OSTIR%"
  echo [%date% %time%] Using OSTIR=%OSTIR_BIN% >> "%LOG_FILE%"
) else (
  echo [%date% %time%] OSTIR binary not found. Run will fail for estimation/design if OSTIR is not installed. >> "%LOG_FILE%"
  echo WARNING: OSTIR was not found. Set OSTIR_BIN explicitly.
)

set "PORT="
for /L %%P in (%DEFAULT_PORT%,1,%MAX_PORT%) do (
  if not defined PORT (
    for /f "delims=" %%F in ('powershell -NoProfile -Command "try { $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, %%P); $listener.Start(); $listener.Stop(); Write-Output %%P } catch { Write-Output 0 }"') do (
      if not "%%F"=="0" if not defined PORT set "PORT=%%F"
    )
  )
)

if not defined PORT (
  echo ERROR: No available port in range %DEFAULT_PORT% to %MAX_PORT%.
  pause
  exit /b 1
)

set "URL=http://%HOST%:%PORT%"
echo [%date% %time%] Launch on %URL% >> "%LOG_FILE%"

echo [%date% %time%] Waiting for server then opening browser... >> "%LOG_FILE%"
start "" /B powershell -NoProfile -Command "for($i=0; $i -lt 120; $i++){ try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('%HOST%',[int]'%PORT%'); $c.Close(); Start-Process '%URL%'; break } catch { Start-Sleep -Milliseconds 500 } }"

set "HOST=%HOST%"
set "PORT=%PORT%"
"%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: Flask failed to start. See log: %LOG_FILE%
  type "%LOG_FILE%"
  pause
  exit /b 1
)

echo [%date% %time%] Server stopped. Log: %LOG_FILE% >> "%LOG_FILE%"
pause
exit /b 0
