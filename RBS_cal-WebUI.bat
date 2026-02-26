@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "LOCAL_VIENNA_WHEEL_DIR=%PROJECT_DIR%\libs"
set "LOCAL_VIENNA_BIN_DIR=%PROJECT_DIR%\bin"
set "HOST=127.0.0.1"
set "PORT=8000"
set "MAX_PORT=8010"
set "SERVER_READY_TIMEOUT=60"
set "RBS_VERSION=1.1.04"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "OSTIR_BIN="

if exist "%LOG_FILE%" del "%LOG_FILE%" >nul 2>&1

call :log "[RBS_cal] WebUI start =="
call :log "Project directory: %PROJECT_DIR%"
echo [RBS_cal] start
echo %LOG_FILE%

if not exist "%PROJECT_DIR%\app.py" goto :missing_app

cd /d "%PROJECT_DIR%" >nul 2>&1
if not "%errorlevel%"=="0" goto :fail

echo [RUNTIME] using local venv mode for RBS_cal v%RBS_VERSION%
echo [RUNTIME] ViennaRNA resolves in order: .\bin -> .\libs wheel -> venv module
call :init_venv_runtime
if not "%errorlevel%"=="0" goto :fail
call :runtime_path_venv
if not exist "%PYTHON_EXE%" goto :missing_python

echo install base libs...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if not "%errorlevel%"=="0" goto :fail

echo [ViennaRNA] trying local wheel install from %LOCAL_VIENNA_WHEEL_DIR% ...
call :install_vienna_wheel_local
if not "%errorlevel%"=="0" goto :fail

"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >>"%LOG_FILE%" 2>&1
if not "%errorlevel%"=="0" goto :fail

call :log "Check OSTIR"
call :find_ostir
if not defined OSTIR_BIN (
  echo OSTIR not found. Try install from PyPI...
  "%PYTHON_EXE%" -m pip install ostir >>"%LOG_FILE%" 2>&1
  if not "%errorlevel%"=="0" goto :fail
  call :find_ostir
)
if not defined OSTIR_BIN goto :missing_ostir
echo OSTIR=%OSTIR_BIN%
set "OSTIR_BIN=%OSTIR_BIN%"
call :log_ostir_binary

echo Check ViennaRNA (RNA) module...
call :check_vienna_runtime
if not "%errorlevel%"=="0" goto :fail

echo ---
echo [ViennaRNA command path check after startup probe]
call :diagnose_vienna_path
echo ---

set "PORT_SEARCH=%PORT%"
:find_port
if %PORT_SEARCH% gtr %MAX_PORT% goto :fail
netstat -ano | findstr ":%PORT_SEARCH% " >nul 2>&1
if not errorlevel 1 (
  set /a PORT_SEARCH=%PORT_SEARCH%+1
  goto find_port
)
set "PORT=%PORT_SEARCH%"
set "URL=http://%HOST%:%PORT%"
set "HEALTH_URL=%URL%/health"

echo URL=%URL%

echo Starting Flask app...
start "" /B "%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >> "%LOG_FILE%" 2>&1
if not "%errorlevel%"=="0" goto :fail

call :wait_for_server
if not "%errorlevel%"=="0" goto :fail

echo Server started on %URL%
echo Use this URL: %URL%
echo If browser does not open automatically, copy the URL and open it manually.
echo Open browser...
call :open_webui_browser "%URL%"
if not "%errorlevel%"=="0" echo NOTICE: Auto-open browser failed. Open URL manually from the line above.

goto done

:missing_app
echo ERROR: app.py not found.
goto fail

:missing_python
echo ERROR: Python 3 not found.
goto fail

:missing_ostir
echo WARNING: OSTIR not found.
echo.
echo Please install ostir manually:
echo   %VENV_DIR%\Scripts\python.exe -m pip install ostir
goto fail

:fail
if exist "%LOG_FILE%" type "%LOG_FILE%"
echo.
echo FAILED. Keep this window open.
pause
exit /b 1

:done
call :log "Flask app launch sequence complete"
echo DONE.
pause
exit /b 0

:wait_for_server
set "WAIT_ATTEMPT=0"
:wait_for_server_loop
set /a WAIT_ATTEMPT+=1
if %WAIT_ATTEMPT% gtr %SERVER_READY_TIMEOUT% (
  echo ERROR: Flask app did not start within %SERVER_READY_TIMEOUT% seconds.
  echo.
  echo Last log output:
  if exist "%LOG_FILE%" type "%LOG_FILE%"
  exit /b 1
)

if exist "%LOG_FILE%" (
  findstr /C:"Startup dependency check failed" "%LOG_FILE%" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo ERROR: Flask exited on startup due dependency check failure.
    echo.
    type "%LOG_FILE%"
    exit /b 1
  )
  findstr /C:"Running on http://%HOST%:%PORT%" "%LOG_FILE%" >nul 2>&1
  if not errorlevel 1 exit /b 0
)

"%PYTHON_EXE%" -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1).read(1)" "%HEALTH_URL%" >nul 2>&1
if "%errorlevel%"=="0" exit /b 0
ping -n 2 127.0.0.1 >nul
goto wait_for_server_loop

:log
set "TS=%date% %time%"
echo [%TS%] %~1>>"%LOG_FILE%"
exit /b 0

:log_runtime_context
call :log "  RUNTIME_MODE=venv"
call :log "  PROJECT_DIR=%PROJECT_DIR%"
call :log "  VENV_DIR=%VENV_DIR%"
call :log "  PYTHON_ARGS=%PYTHON_ARGS%"
call :log "  PYTHON_EXE=%PYTHON_EXE%"
call :log "  PATH sample:"
setlocal EnableDelayedExpansion
for /f "tokens=1-10 delims=;" %%A in ("!PATH!") do (
  if "%%A" neq "" call :log "    PATH[1]=%%A"
  if "%%B" neq "" call :log "    PATH[2]=%%B"
  if "%%C" neq "" call :log "    PATH[3]=%%C"
  if "%%D" neq "" call :log "    PATH[4]=%%D"
  if "%%E" neq "" call :log "    PATH[5]=%%E"
  if "%%F" neq "" call :log "    PATH[6]=%%F"
  if "%%G" neq "" call :log "    PATH[7]=%%G"
  if "%%H" neq "" call :log "    PATH[8]=%%H"
  if "%%I" neq "" call :log "    PATH[9]=%%I"
  if "%%J" neq "" call :log "    PATH[10]=%%J"
)
endlocal
exit /b 0

:log_ostir_binary
call :log "  OSTIR_BIN=%OSTIR_BIN%"
if defined OSTIR_BIN (
  if exist "%OSTIR_BIN%" (
    echo OSTIR binary exists: %OSTIR_BIN%
  ) else (
    echo OSTIR path exists in variable but file missing: %OSTIR_BIN%
  )
) else (
  echo OSTIR binary was not resolved.
)
where ostir 2>nul | findstr "." >nul
if "%errorlevel%"=="0" (
  echo where ostir => output:
  where ostir
) else (
  echo where ostir => not found in PATH
)
echo.
exit /b 0

:runtime_path_venv
if exist "%VENV_DIR%\Scripts" set "PATH=%VENV_DIR%\Scripts;!PATH!"
call :log "[RUNTIME] using venv: %VENV_DIR%"
call :log_runtime_context
exit /b 0

:init_venv_runtime
set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%VENV_DIR%\Scripts\python.exe" set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not defined PYTHON_EXE (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  )
)
if not defined PYTHON_EXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  echo ERROR: Python 3 not found.
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo create venv.
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if not "%errorlevel%"=="0" exit /b 1
)

set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" exit /b 1
exit /b 0

:find_ostir
if defined OSTIR_BIN if exist "%OSTIR_BIN%" exit /b 0
set "OSTIR_BIN="

if exist "%VENV_DIR%\Scripts\ostir.exe" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir.exe"
if not defined OSTIR_BIN if exist "%VENV_DIR%\Scripts\ostir" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir"
if not defined OSTIR_BIN if exist "%VENV_DIR%\Scripts\ostir-script.py" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir-script.py"

if not defined OSTIR_BIN for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fP"

if defined OSTIR_BIN exit /b 0
exit /b 1

:check_vienna_runtime
if not exist "%PYTHON_EXE%" exit /b 1
set "VN_BASE=%VENV_DIR%"
call :log "[ViennaRNA] VN_BASE=%VN_BASE%"
set "VIENNARNA_MISSING="

echo.
echo [ViennaRNA] checking local runtime and command-line executables...
call :activate_local_vienna_bin

set "VIENNARNA_MISSING="
for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if not "%errorlevel%"=="0" set "VIENNARNA_MISSING=1"
)
if not defined VIENNARNA_MISSING goto :viennarna_ok

echo [ViennaRNA] required CLI not found in PATH. Checking Python module...
"%PYTHON_EXE%" -c "import RNA" >nul 2>&1
if not "%errorlevel%"=="0" (
  echo ERROR: ViennaRNA Python module (RNA) not found.
  echo Install ViennaRNA wheel in .\libs first, then run again.
  goto :viennarna_failed
)

set "VIENNARNA_MISSING="
for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if not "%errorlevel%"=="0" set "VIENNARNA_MISSING=1"
)
if defined VIENNARNA_MISSING goto :viennarna_failed
goto :viennarna_ok

:viennarna_ok
echo ViennaRNA command-line dependencies are ready.
exit /b 0

:viennarna_failed
echo ERROR: One or more required ViennaRNA command-line tools are missing.
echo See above for each command and location.
exit /b 1

:activate_local_vienna_bin
if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold" (
  if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt" (
    if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval" exit /b 0
  )
)
set "VLB_RNAFOLD=0"
set "VLB_RNASUBOPT=0"
set "VLB_RNaeval=0"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold.exe" set "VLB_RNAFOLD=1"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold" set "VLB_RNAFOLD=1"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt.exe" set "VLB_RNASUBOPT=1"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt" set "VLB_RNASUBOPT=1"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval.exe" set "VLB_RNaeval=1"
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval" set "VLB_RNaeval=1"

set "VLB_SUM=0"
set /a VLB_SUM=%VLB_RNAFOLD%+%VLB_RNASUBOPT%+%VLB_RNaeval%
if "%VLB_SUM%"=="3" (
  echo [ViennaRNA] local bin bundle complete: 3/3 binaries present in %LOCAL_VIENNA_BIN_DIR%
) else (
  echo [ViennaRNA] local bin bundle partial: %VLB_SUM%/3 binaries present in %LOCAL_VIENNA_BIN_DIR%
  echo [ViennaRNA] Missing:
  if "%VLB_RNAFOLD%"=="0" echo [MISSING] RNAfold
  if "%VLB_RNASUBOPT%"=="0" echo [MISSING] RNAsubopt
  if "%VLB_RNaeval%"=="0" echo [MISSING] RNAeval
)
set "PATH=%LOCAL_VIENNA_BIN_DIR%;!PATH!"
echo Added local ViennaRNA binary directory: %LOCAL_VIENNA_BIN_DIR%
exit /b 0

:install_vienna_wheel_local
if not exist "%LOCAL_VIENNA_WHEEL_DIR%\*" (
  echo [WARN] local ViennaRNA package folder not found: %LOCAL_VIENNA_WHEEL_DIR%
  exit /b 0
)
set "VN_WHEEL="
for %%W in ("%LOCAL_VIENNA_WHEEL_DIR%\ViennaRNA-*.whl") do (
  if not defined VN_WHEEL set "VN_WHEEL=%%~fW"
)
if not defined VN_WHEEL (
  echo [WARN] No ViennaRNA wheel found under: %LOCAL_VIENNA_WHEEL_DIR%
  exit /b 0
)
echo [ViennaRNA] installing local wheel: %VN_WHEEL%
"%PYTHON_EXE%" -m pip install "%VN_WHEEL%" --upgrade >>"%LOG_FILE%" 2>&1
if not "%errorlevel%"=="0" (
  echo [ERROR] local ViennaRNA wheel install failed.
  exit /b 1
)
exit /b 0

:ensure_vienna_command
where %1 2>nul | findstr "." >nul
if errorlevel 1 (
  echo [MISSING] %1
  exit /b 1
)
echo [FOUND]  %1
for /f "delims=" %%p in ('where %1 2^>nul') do echo     %%p
exit /b 0

:diagnose_vienna_path
echo Required command-line tools (RNAfold / RNAsubopt / RNAeval):
call :ensure_vienna_command RNAfold
call :ensure_vienna_command RNAsubopt
call :ensure_vienna_command RNAeval
echo.
echo ViennaRNA runtime diagnostics:
if exist "%LOCAL_VIENNA_WHEEL_DIR%" (
  if exist "%LOCAL_VIENNA_WHEEL_DIR%\ViennaRNA-*.whl" (
    echo   ViennaRNA wheels:
    dir /b "%LOCAL_VIENNA_WHEEL_DIR%\ViennaRNA-*.whl"
  ) else (
    echo   [MISSING] ViennaRNA wheel file under: %LOCAL_VIENNA_WHEEL_DIR%
  )
) else (
  echo   [MISSING] ViennaRNA wheel directory: %LOCAL_VIENNA_WHEEL_DIR%
)
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold.exe" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAfold.exe
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt.exe" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAsubopt.exe
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval.exe" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAeval.exe
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAfold
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAsubopt
if exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval" echo   local bin: %LOCAL_VIENNA_BIN_DIR%\RNAeval
echo   VN_BASE=%VN_BASE%
if exist "%VENV_DIR%\Scripts" echo   candidate: %VENV_DIR%\Scripts
echo.
exit /b 0

:open_webui_browser
setlocal EnableExtensions EnableDelayedExpansion
set "OPEN_URL=%~1"
if not defined OPEN_URL (
  endlocal
  exit /b 1
)

echo [Browser] trying to open: %OPEN_URL%

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -c "import sys,webbrowser; sys.exit(0 if webbrowser.open(sys.argv[1], new=2) else 1)" "%OPEN_URL%" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo [Browser] opened via Python webbrowser.
    endlocal
    exit /b 0
  )
)

if exist "%WINDIR%\System32\rundll32.exe" (
  start "" "%WINDIR%\System32\rundll32.exe" url.dll,FileProtocolHandler "%OPEN_URL%" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo [Browser] opened via rundll32 URL handler.
    endlocal
    exit /b 0
  )
)

rem Modern fallback: direct command shell open
where explorer 2>nul | findstr "." >nul
if "%errorlevel%"=="0" (
  start "" explorer "%OPEN_URL%" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo [Browser] opened via explorer.
    endlocal
    exit /b 0
  )
)

where powershell 2>nul | findstr "." >nul
if "%errorlevel%"=="0" (
  powershell -NoProfile -Command "Start-Process -FilePath '%OPEN_URL%'" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo [Browser] opened via PowerShell.
    endlocal
    exit /b 0
  )
)

if exist "%COMSPEC%" (
  "%COMSPEC%" /c start "" "%OPEN_URL%" >nul 2>&1
  if "%errorlevel%"=="0" (
    echo [Browser] opened via COMSPEC start.
    endlocal
    exit /b 0
  )
)

rem Final fallback: keep command simple and robust for localized shells
start "" "%OPEN_URL%" >nul 2>&1
if "%errorlevel%"=="0" (
  echo [Browser] opened via CMD start.
  endlocal
  exit /b 0
)

echo [Browser] auto-open failed for: %OPEN_URL%
endlocal
exit /b 1
