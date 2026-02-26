@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "LOG_FILE=%PROJECT_DIR%\.rbs_cal_web.log"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "CONDA_ENV_DIR=%PROJECT_DIR%\.conda_venv"
set "LOCAL_VIENNA_WHEEL_DIR=%PROJECT_DIR%\libs"
set "LOCAL_VIENNA_BIN_DIR=%PROJECT_DIR%\bin"
set "HOST=127.0.0.1"
set "PORT=8000"
set "MAX_PORT=8010"
set "SERVER_READY_TIMEOUT=60"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "CONDA_EXE="
set "RUNTIME_MODE=venv"
set "OSTIR_BIN="

if exist "%LOG_FILE%" del "%LOG_FILE%" >nul 2>&1

call :log "== RBS_cal WebUI start =="
call :log "Project directory: %PROJECT_DIR%"
echo [RBS_cal] start
echo %LOG_FILE%

if not exist "%PROJECT_DIR%\app.py" goto :missing_app
cd /d "%PROJECT_DIR%" >nul 2>&1
if not "%errorlevel%"=="0" goto :fail

call :detect_conda
if not defined CONDA_EXE goto :skip_conda

echo [RUNTIME] conda detected: %CONDA_EXE%
call :init_conda_runtime
if not "%errorlevel%"=="0" goto :conda_failed
set "RUNTIME_MODE=conda"
goto :runtime_path_conda

:conda_failed
echo [RUNTIME] conda bootstrap failed. Falling back to venv mode.

:skip_conda

set "RUNTIME_MODE=venv"
call :init_venv_runtime
if not "%errorlevel%"=="0" goto :fail
goto :runtime_path_venv

:runtime_path_conda
set "CONDA_PREFIX=%CONDA_ENV_DIR%"
set "RBS_CAL_CONDA_ENV=%CONDA_ENV_DIR%"
if exist "%CONDA_ENV_DIR%\Scripts" set "PATH=%CONDA_ENV_DIR%\Scripts;!PATH!"
if exist "%CONDA_ENV_DIR%\Library\bin" set "PATH=%CONDA_ENV_DIR%\Library\bin;!PATH!"
if exist "%CONDA_ENV_DIR%\bin" set "PATH=%CONDA_ENV_DIR%\bin;!PATH!"
echo [RUNTIME] using conda env: %CONDA_ENV_DIR%
goto :runtime_path_done

:runtime_path_venv
if exist "%VENV_DIR%\Scripts" set "PATH=%VENV_DIR%\Scripts;!PATH!"
echo [RUNTIME] using venv: %VENV_DIR%
goto :runtime_path_done

:runtime_path_done
if not exist "%PYTHON_EXE%" goto :missing_python

echo install base libs...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
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

echo Check ViennaRNA (RNA) module...
call :check_vienna_runtime
if not "%errorlevel%"=="0" goto :fail

echo ---
echo [ViennaRNA command path check after runtime probe]
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

echo URL=%URL%

echo Starting Flask app...
start "" /B cmd /c ""%PYTHON_EXE%" "%PROJECT_DIR%\app.py" >> "%LOG_FILE%" 2>&1"
if not "%errorlevel%"=="0" goto :fail
call :wait_for_server
if not "%errorlevel%"=="0" goto :fail

echo Open browser...
start "" "%URL%"

echo Server started on %URL%

goto done

:missing_app
echo ERROR: app.py not found.
goto fail

:missing_python
echo ERROR: Python not found.
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
ping -n 2 127.0.0.1 >nul
goto wait_for_server_loop

:log
set "TS=%date% %time%"
echo [%TS%] %~1>>"%LOG_FILE%"
exit /b 0

:detect_conda
set "CONDA_EXE="
where conda 2>nul | findstr "." >nul
if not "%errorlevel%"=="0" goto :detect_conda_scan
for /f "delims=" %%p in ('where conda 2^>nul') do if not defined CONDA_EXE set "CONDA_EXE=%%~fp"
if defined CONDA_EXE exit /b 0
exit /b 1

:detect_conda_scan
for %%P in (
  "%ProgramData%\miniconda3\Scripts\conda.exe"
  "%ProgramData%\Anaconda3\Scripts\conda.exe"
  "%ProgramFiles%\Miniconda3\Scripts\conda.exe"
  "%ProgramFiles%\Anaconda3\Scripts\conda.exe"
  "%LocalAppData%\Miniconda3\Scripts\conda.exe"
  "%LocalAppData%\Anaconda3\Scripts\conda.exe"
  "%USERPROFILE%\miniconda3\Scripts\conda.exe"
  "%USERPROFILE%\Anaconda3\Scripts\conda.exe"
  "%USERPROFILE%\anaconda3\Scripts\conda.exe"
  "%USERPROFILE%\AppData\Local\miniconda3\Scripts\conda.exe"
  "%USERPROFILE%\AppData\Local\Anaconda3\Scripts\conda.exe"
) do if not defined CONDA_EXE if exist "%%~P" set "CONDA_EXE=%%~P"

if defined CONDA_EXE exit /b 0
exit /b 1

:init_conda_runtime
if not defined CONDA_EXE exit /b 1
if not exist "%CONDA_ENV_DIR%\python.exe" goto :create_conda_runtime
set "PYTHON_EXE=%CONDA_ENV_DIR%\python.exe"
goto :conda_runtime_ready

:create_conda_runtime
echo create conda env (runtime)...
"%CONDA_EXE%" create -y -p "%CONDA_ENV_DIR%" python=3.11 >>"%LOG_FILE%" 2>&1
if not "%errorlevel%"=="0" (
  echo ERROR: conda environment create failed.
  exit /b 1
)

:conda_runtime_ready
if not exist "%CONDA_ENV_DIR%\python.exe" (
  echo ERROR: conda environment not found after create: %CONDA_ENV_DIR%
  exit /b 1
)
set "PYTHON_EXE=%CONDA_ENV_DIR%\python.exe"
if not exist "%PYTHON_EXE%" exit /b 1
if exist "%CONDA_ENV_DIR%\Scripts" set "PATH=%CONDA_ENV_DIR%\Scripts;!PATH!"
if exist "%CONDA_ENV_DIR%\Library\bin" set "PATH=%CONDA_ENV_DIR%\Library\bin;!PATH!"
if exist "%CONDA_ENV_DIR%\bin" set "PATH=%CONDA_ENV_DIR%\bin;!PATH!"
exit /b 0

:init_venv_runtime
set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%VENV_DIR%\Scripts\python.exe" set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not defined PYTHON_EXE where py >nul 2>nul
if not errorlevel 1 if not defined PYTHON_EXE (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
)
if not defined PYTHON_EXE where python >nul 2>nul
if not errorlevel 1 if not defined PYTHON_EXE set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
  echo ERROR: Python 3 not found.
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" goto :create_venv
goto :venv_runtime_done

:create_venv
echo create venv.
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
if not "%errorlevel%"=="0" exit /b 1

:venv_runtime_done
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" exit /b 1
exit /b 0

:find_ostir
if defined OSTIR_BIN if exist "%OSTIR_BIN%" exit /b 0
set "OSTIR_BIN="

if "%RUNTIME_MODE%"=="conda" (
  if exist "%CONDA_ENV_DIR%\Scripts\ostir.exe" set "OSTIR_BIN=%CONDA_ENV_DIR%\Scripts\ostir.exe"
  if not defined OSTIR_BIN if exist "%CONDA_ENV_DIR%\Scripts\ostir" set "OSTIR_BIN=%CONDA_ENV_DIR%\Scripts\ostir"
  if not defined OSTIR_BIN if exist "%CONDA_ENV_DIR%\Scripts\ostir-script.py" set "OSTIR_BIN=%CONDA_ENV_DIR%\Scripts\ostir-script.py"
  if not defined OSTIR_BIN if exist "%CONDA_ENV_DIR%\ostir.exe" set "OSTIR_BIN=%CONDA_ENV_DIR%\ostir.exe"
  if not defined OSTIR_BIN if exist "%CONDA_ENV_DIR%\ostir" set "OSTIR_BIN=%CONDA_ENV_DIR%\ostir"
  if not defined OSTIR_BIN if exist "%CONDA_ENV_DIR%\ostir-script.py" set "OSTIR_BIN=%CONDA_ENV_DIR%\ostir-script.py"
)

if not defined OSTIR_BIN (
  if exist "%VENV_DIR%\Scripts\ostir.exe" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir.exe"
)
if not defined OSTIR_BIN if exist "%VENV_DIR%\Scripts\ostir" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir"
if not defined OSTIR_BIN if exist "%VENV_DIR%\Scripts\ostir-script.py" set "OSTIR_BIN=%VENV_DIR%\Scripts\ostir-script.py"

if not defined OSTIR_BIN if defined ProgramW6432 if exist "%ProgramW6432%\Python\Python*\Scripts\ostir*" (
  for /f "delims=" %%p in ('dir /b /s "%ProgramW6432%\Python\Python*\Scripts\ostir*" 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fp"
)

if not defined OSTIR_BIN if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir*" (
  for /f "delims=" %%p in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python*\Scripts\ostir*" 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fp"
)

if not defined OSTIR_BIN if exist "%USERPROFILE%\.local\Programs\Python\Python*\Scripts\ostir*" (
  for /f "delims=" %%p in ('dir /b /s "%USERPROFILE%\.local\Programs\Python\Python*\Scripts\ostir*" 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fp"
)

if not defined OSTIR_BIN for /f "delims=" %%P in ('where ostir 2^>nul') do if not defined OSTIR_BIN set "OSTIR_BIN=%%~fP"

if defined OSTIR_BIN exit /b 0
exit /b 1

:check_vienna_runtime
if not exist "%PYTHON_EXE%" exit /b 1
set "VN_BASE=%VENV_DIR%"
if "%RUNTIME_MODE%"=="conda" set "VN_BASE=%CONDA_ENV_DIR%"
set "VIENNARNA_MISSING="
echo.
echo [ViennaRNA] checking local runtime and command-line executables...
call :activate_local_vienna_bin

for %%b in (RNAfold RNAsubopt RNAeval) do call :ensure_vienna_command %%b

set "VIENNARNA_MISSING="
for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if not "%errorlevel%"=="0" set "VIENNARNA_MISSING=1"
)

if not defined VIENNARNA_MISSING goto :viennarna_ok

echo [ViennaRNA] required CLI not found in PATH. Checking ViennaRNA Python module/ wheel...
where RNAfold 2>nul | findstr "." >nul
if not "%errorlevel%"=="0" goto :viennarna_needs_module_check
echo RNA command-line binary found on PATH.
goto :viennarna_command_recheck

:viennarna_needs_module_check
"%PYTHON_EXE%" -c "import RNA" >nul 2>&1
if "%errorlevel%"=="0" goto :viennarna_command_recheck
echo RNA module not found. Trying local ViennaRNA wheel...
call :install_vienna_wheel_local
if not "%errorlevel%"=="0" echo [WARN] No local wheel installation succeeded for ViennaRNA.

:viennarna_command_recheck
set "VIENNARNA_MISSING="
for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if not "%errorlevel%"=="0" set "VIENNARNA_MISSING=1"
)

if defined VIENNARNA_MISSING if "%RUNTIME_MODE%"=="conda" goto :viennarna_conda_retry
if defined VIENNARNA_MISSING goto :viennarna_failed
goto :viennarna_ok

:viennarna_conda_retry
echo [ViennaRNA] still missing. trying conda install in %CONDA_ENV_DIR%...
call :install_vienna_conda
if not "%errorlevel%"=="0" goto :viennarna_failed

set "VIENNARNA_MISSING="
for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if not "%errorlevel%"=="0" set "VIENNARNA_MISSING=1"
)
if defined VIENNARNA_MISSING goto :viennarna_failed

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
  echo [ViennaRNA] local bundle complete: 3/3 binaries present in %LOCAL_VIENNA_BIN_DIR%
) else (
  echo [ViennaRNA] partial local bundle: %VLB_SUM%/3 binaries present in %LOCAL_VIENNA_BIN_DIR%
  echo [ViennaRNA] Missing:
  if "%VLB_RNAFOLD%"=="0" echo [MISSING] RNAfold
  if "%VLB_RNASUBOPT%"=="0" echo [MISSING] RNAsubopt
  if "%VLB_RNaeval%"=="0" echo [MISSING] RNAeval
)
set "PATH=%LOCAL_VIENNA_BIN_DIR%;!PATH!"
echo Added local ViennaRNA binary directory: %LOCAL_VIENNA_BIN_DIR%
exit /b 0

:install_vienna_wheel_local
if not exist "%LOCAL_VIENNA_WHEEL_DIR%\*" exit /b 1
set "VN_WHEEL="
for %%W in ("%LOCAL_VIENNA_WHEEL_DIR%\ViennaRNA-*.whl") do (
  if not defined VN_WHEEL set "VN_WHEEL=%%~fW"
)
if not defined VN_WHEEL (
  echo [ViennaRNA] No local ViennaRNA wheel found under: %LOCAL_VIENNA_WHEEL_DIR%
  exit /b 1
)
echo [ViennaRNA] installing ViennaRNA from local wheel: %VN_WHEEL%
"%PYTHON_EXE%" -m pip install "%VN_WHEEL%" --upgrade >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo [ViennaRNA] local wheel install failed.
  exit /b 1
)
exit /b 0

:detect_viennabin
setlocal EnableExtensions EnableDelayedExpansion
set "base=%~1"
if exist "%base%\RNAfold.exe" set "VENN_DIR=%base%"
if exist "%base%\RNAfold" set "VENN_DIR=%base%"
if exist "%base%\RNAsubopt.exe" set "VENN_DIR=%base%"
if exist "%base%\RNAsubopt" set "VENN_DIR=%base%"
if exist "%base%\RNAeval.exe" set "VENN_DIR=%base%"
if exist "%base%\RNAeval" set "VENN_DIR=%base%"
endlocal & set "VENN_DIR=%VENN_DIR%"
exit /b 0

:ensure_vienna_command
set "cmd=%~1"
call :check_vienna_command "%cmd%"
if errorlevel 0 exit /b 0

set "FOUND_DIR="
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Scripts" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Scripts\RNA" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Lib\site-packages\RNA\bin" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Lib\site-packages\RNA\Scripts" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Lib\site-packages\RNA" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\Lib\site-packages" "%cmd%"
if defined VN_BASE if not defined FOUND_DIR call :find_vienna_command_dir "%VN_BASE%\bin" "%cmd%"
if defined CONDA_PREFIX if not defined FOUND_DIR call :find_vienna_command_dir "%CONDA_PREFIX%\Library\bin" "%cmd%"
if defined CONDA_PREFIX if not defined FOUND_DIR call :find_vienna_command_dir "%CONDA_PREFIX%\Scripts" "%cmd%"
if defined FOUND_DIR (
  set "PATH=%FOUND_DIR%;!PATH!"
  echo Added fallback ViennaRNA directory for %cmd%: %FOUND_DIR%
  call :check_vienna_command "%cmd%"
  exit /b %errorlevel%
)

echo [MISSING] %cmd% (not found in fallback scan)
echo Tried locating in:
if defined VN_BASE echo   %VN_BASE%\Scripts
if defined VN_BASE echo   %VN_BASE%\Scripts\RNA
if defined VN_BASE echo   %VN_BASE%\Lib\site-packages\RNA\bin
if defined VN_BASE echo   %VN_BASE%\Lib\site-packages\RNA\Scripts
if defined VN_BASE echo   %VN_BASE%\Lib\site-packages\RNA
if defined VN_BASE echo   %VN_BASE%\Lib\site-packages
if defined VN_BASE echo   %VN_BASE%\bin
if defined CONDA_PREFIX echo   %CONDA_PREFIX%\Library\bin
if defined CONDA_PREFIX echo   %CONDA_PREFIX%\Scripts
exit /b 1

:find_vienna_command_dir
setlocal EnableExtensions EnableDelayedExpansion
set "scan_root=%~1"
set "cmd=%~2"
set "found="
if not exist "%scan_root%" (
  endlocal & set "FOUND_DIR="
  exit /b 1
)

for /f "delims=" %%p in ('dir /b /s /a "%scan_root%\%cmd%.exe" 2^>nul') do (
  set "found=%%~dpp"
  goto :scan_found
)
for /f "delims=" %%p in ('dir /b /s /a "%scan_root%\%cmd%.bat" 2^>nul') do (
  set "found=%%~dpp"
  goto :scan_found
)
for /f "delims=" %%p in ('dir /b /s /a "%scan_root%\%cmd%.cmd" 2^>nul') do (
  set "found=%%~dpp"
  goto :scan_found
)
:scan_found
endlocal & set "FOUND_DIR=%found%"
if defined found exit /b 0
exit /b 1

:check_vienna_command
where %1 2>nul | findstr "." >nul
if errorlevel 1 (
  echo [MISSING] %1
  exit /b 1
)
echo [FOUND]  %1
for /f "delims=" %%p in ('where %1 2^>nul') do echo     %%p
exit /b 0

:install_vienna_conda
if "%RUNTIME_MODE%" neq "conda" exit /b 1
if not defined CONDA_EXE exit /b 1
if not exist "%CONDA_ENV_DIR%\python.exe" (
  echo ERROR: conda env not found for ViennaRNA install: %CONDA_ENV_DIR%
  exit /b 1
)
echo [ViennaRNA] install ViennaRNA from conda-forge/bioconda...
"%CONDA_EXE%" install -y -p "%CONDA_ENV_DIR%" -c conda-forge -c bioconda viennarna >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: conda install viennarna failed.
  echo You can run manually:
  echo   %CONDA_EXE% install -y -p "%CONDA_ENV_DIR%" -c conda-forge -c bioconda viennarna
  exit /b 1
)
if exist "%CONDA_ENV_DIR%\Library\bin" set "PATH=%CONDA_ENV_DIR%\Library\bin;!PATH!"
exit /b 0

:diagnose_vienna_path
echo Required command-line tools (RNAfold / RNAsubopt / RNAeval):
call :check_vienna_command RNAfold
call :check_vienna_command RNAsubopt
call :check_vienna_command RNAeval
echo.
echo PATH prefix sample:
echo   %PATH%
exit /b 0
