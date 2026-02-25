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

> "%LOG_FILE%" echo [%date% %time%] RBS_cal WebUI start

if exist "%VENV_DIR%\Scripts\python.exe" (
  set "PY_CMD=%VENV_DIR%\Scripts\python.exe"
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Python 3이 없습니다. Python을 설치하고 PATH를 확인하세요.
      pause
      exit /b 1
    )
    set "PY_CMD=python"
  ) else (
    set "PY_CMD=py"
    set "PY_ARGS=-3"
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY_CMD% %PY_ARGS% -m venv "%VENV_DIR%" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo ERROR: 가상환경 생성 실패
    type "%LOG_FILE%"
    pause
    exit /b 1
  )
)

set "PY_CMD=%VENV_DIR%\Scripts\python.exe"
if not exist "%PY_CMD%" (
  echo ERROR: 가상환경 python.exe를 찾지 못했습니다.
  pause
  exit /b 1
)

echo [%date% %time%] pip 업그레이드... >> "%LOG_FILE%"
"%PY_CMD%" -m pip install --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: pip 업그레이드 실패
  type "%LOG_FILE%"
  pause
  exit /b 1
)

echo [%date% %time%] requirements 설치... >> "%LOG_FILE%"
"%PY_CMD%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
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
if not defined FOUND_OSTIR if exist "%USERPROFILE%\.local\vienna\bin\ostir" set "FOUND_OSTIR=%USERPROFILE%\.local\vienna\bin\ostir"
if not defined FOUND_OSTIR if exist "%USERPROFILE%\AppData\Roaming\Python\Python*\Scripts\ostir.exe" (
  for %%P in ("%USERPROFILE%\AppData\Roaming\Python\Python*\Scripts\ostir.exe") do set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR if exist "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe" (
  for %%P in ("%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir.exe") do set "FOUND_OSTIR=%%~fP"
)
if not defined FOUND_OSTIR (
  where ostir >nul 2>nul
  if not errorlevel 1 (
    for /f "usebackq delims=" %%P in (`where ostir`) do if not defined FOUND_OSTIR set "FOUND_OSTIR=%%P"
  )
)

if defined FOUND_OSTIR (
  set "OSTIR_BIN=%FOUND_OSTIR%"
  echo [%date% %time%] OSTIR: %OSTIR_BIN% >> "%LOG_FILE%"
) else (
  echo [%date% %time%] 경고: OSTIR을 찾지 못했습니다. 예측 실행 시 실패할 수 있습니다. >> "%LOG_FILE%"
  echo 경고: OSTIR을 찾지 못했습니다. OSTIR이 없으면 예측/설계가 동작하지 않습니다.
  echo OSTIR_BIN를 지정하거나 PATH에 설치 경로를 등록해 주세요.
)

set "PORT="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$selected = -1; for ($p = %DEFAULT_PORT%; $p -le %MAX_PORT%; $p++) { $listeners = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue; if (-not $listeners) { $selected = $p; break } }; Write-Output $selected"`) do set "PORT=%%P"
if "%PORT%"=="-1" (
  echo ERROR: 사용 가능한 포트를 찾지 못했습니다 (%DEFAULT_PORT%~%MAX_PORT%).
  pause
  exit /b 1
)

set "HOST=%HOST%"
set "PORT=%PORT%"
set "URL=http://%HOST%:%PORT%"
echo [%date% %time%] Starting Flask on %URL% >> "%LOG_FILE%"

start "" /B "%PY_CMD%" "%PROJECT_DIR%\app.py" >> "%LOG_FILE%" 2>&1

set "READY="
for /L %%I in (1,1,30) do (
  timeout /t 1 >nul
  powershell -NoProfile -Command "try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('%HOST%',[int]'%PORT%'); $c.Close(); Write-Output OK } catch { Write-Output NG }" | findstr /i /c:"OK" >nul
  if !errorlevel! equ 0 (
    set "READY=1"
    goto :open_browser
  )
)

:open_browser
if not defined READY (
  echo [%date% %time%] 서버 준비 대기 시간 초과 -> 브라우저를 직접 열어주세요. >> "%LOG_FILE%"
)

echo [%date% %time%] opening browser: %URL% >> "%LOG_FILE%"
start "" "%URL%"
exit /b 0
