@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "HOST=127.0.0.1"
set "DEFAULT_PORT=8000"
set "MAX_PORT=8010"

if not exist "%PROJECT_DIR%\app.py" (
  echo ERROR: 프로젝트 루트를 찾을 수 없습니다: %PROJECT_DIR%
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%" || (
  echo ERROR: 프로젝트 폴더로 이동할 수 없습니다.
  pause
  exit /b 1
)

> "%LOG_FILE%" echo [%date% %time%] RBS_cal WebUI start

if exist "%VENV_DIR%\Scripts\python.exe" (
  set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Python 3이 설치되어 있지 않습니다.
      pause
      exit /b 1
    )
    set "PYTHON_EXE=python"
  ) else (
    set "PYTHON_EXE=py"
    set "PY_ARGS=-3"
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Create virtual environment...
  echo [%date% %time%] Creating venv at %VENV_DIR% >> "%LOG_FILE%"
  %PYTHON_EXE% %PY_ARGS% -m venv "%VENV_DIR%" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo ERROR: 가상환경 생성 실패
    type "%LOG_FILE%"
    pause
    exit /b 1
  )
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo ERROR: 가상환경 Python을 찾지 못했습니다: %PYTHON_EXE%
  pause
  exit /b 1
)

echo [%date% %time%] Update pip/setuptools/wheel... >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: pip 업그레이드 실패
  type "%LOG_FILE%"
  pause
  exit /b 1
)

echo [%date% %time%] Install requirements... >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: requirements.txt 설치 실패
  type "%LOG_FILE%"
  pause
  exit /b 1
)

set "FOUND_OSTIR="
if defined OSTIR_BIN if exist "%OSTIR_BIN%" set "FOUND_OSTIR=%OSTIR_BIN%"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir.exe" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir.exe"
if not defined FOUND_OSTIR if exist "%VENV_DIR%\Scripts\ostir" set "FOUND_OSTIR=%VENV_DIR%\Scripts\ostir"
if not defined FOUND_OSTIR if exist "%USERPROFILE%\.local\bin\ostir" set "FOUND_OSTIR=%USERPROFILE%\.local\bin\ostir"
if not defined FOUND_OSTIR if defined ProgramW6432 if exist "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%P in ('dir /b /s "%ProgramW6432%\Python\Python*\Scripts\ostir.exe" 2^>nul ^| findstr /r /c:".*\\\\ostir\\.exe$"') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" (
  for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" 2^>nul ^| findstr /r /c:".*\\\\ostir\\.exe$"') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR (
  where ostir >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%P"
  )
)

if defined FOUND_OSTIR (
  set "OSTIR_BIN=%FOUND_OSTIR%"
  echo [%date% %time%] Using OSTIR: %OSTIR_BIN% >> "%LOG_FILE%"
) else (
  echo [%date% %time%] 경고: OSTIR을 찾지 못했습니다. 예측/설계 실행 시 실패할 수 있습니다. >> "%LOG_FILE%"
  echo 경고: OSTIR이 없으면 실행이 되지 않습니다.
  echo OSTIR_BIN를 지정하거나 PATH에 추가하세요.
)

call :find_free_port
if errorlevel 1 (
  echo ERROR: 사용 가능한 포트를 찾지 못했습니다 (%DEFAULT_PORT%~%MAX_PORT%)
  pause
  exit /b 1
)

set "URL=http://%HOST%:%PORT%"
echo [%date% %time%] Launching Flask on %URL% >> "%LOG_FILE%"

start "" /B "%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: Flask 실행 시작 실패
  type "%LOG_FILE%"
  pause
  exit /b 1
)

set "READY="
for /L %%I in (1,1,30) do (
  powershell -NoProfile -Command "try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('%HOST%',[int]'%PORT%'); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    set "READY=1"
    goto :open_browser
  )
  timeout /t 1 >nul
)

:open_browser
if defined READY (
  echo [%date% %time%] Server ready: %URL% >> "%LOG_FILE%"
) else (
  echo [%date% %time%] Warning: server ready wait timed out. opening browser anyway. >> "%LOG_FILE%"
)

start "" "%URL%"
exit /b 0

:find_free_port
for /f "delims=" %%P in ('powershell -NoProfile -Command "$selected = -1; for ($p=%DEFAULT_PORT%; $p -le %MAX_PORT%; $p++) { $listeners = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue; if (-not $listeners) { $selected = $p; break } }; Write-Output $selected"') do set "PORT=%%P"
if "%PORT%"=="" set "PORT=-1"
if "%PORT%"=="-1" exit /b 1
exit /b 0
