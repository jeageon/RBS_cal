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
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "CONDA_EXE="
set "RUNTIME_MODE=venv"

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

call :detect_conda
if defined CONDA_EXE (
  echo [RUNTIME] conda detected: %CONDA_EXE%
  call :init_conda_runtime
  if errorlevel 1 (
    echo [RUNTIME] conda bootstrap failed. Falling back to venv mode.
    set "RUNTIME_MODE=venv"
  ) else (
    set "RUNTIME_MODE=conda"
  )
)

if "%RUNTIME_MODE%"=="venv" (
  call :init_venv_runtime
  if errorlevel 1 goto fail
)

if not exist "%PYTHON_EXE%" (
  echo ERROR: Python not found.
  goto fail
)

if "%RUNTIME_MODE%"=="conda" (
  echo [RUNTIME] using conda env: %CONDA_ENV_DIR%
) else (
  echo [RUNTIME] using venv: %VENV_DIR%
)

echo install base libs...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%\requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto fail

call :log "Check OSTIR"
call :find_ostir
if not defined OSTIR_BIN (
  echo OSTIR not found. Try install from PyPI...
  "%PYTHON_EXE%" -m pip install ostir >>"%LOG_FILE%" 2>&1
  if errorlevel 1 goto fail
  call :find_ostir
)
if defined OSTIR_BIN (
  echo OSTIR=%OSTIR_BIN%
) else (
  echo WARNING: OSTIR not found.
  echo.
  echo Please install ostir manually:
  echo   %VENV_DIR%\Scripts\python.exe -m pip install ostir
  goto fail
)

echo Check ViennaRNA (RNA) module...
call :check_vienna_runtime
if errorlevel 1 goto fail

echo ---
echo [ViennaRNA command path check after runtime probe]
call :diagnose_vienna_path
echo ---

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

:detect_conda
where conda 2>nul | findstr "." >nul
if errorlevel 1 (
  set "CONDA_EXE="
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
  ) do (
    if exist "%%~P" if not defined CONDA_EXE set "CONDA_EXE=%%~P"
  )
  if not defined CONDA_EXE (
    exit /b 1
  )
  exit /b 0
)
for /f "delims=" %%p in ('where conda 2^>nul') do if not defined CONDA_EXE set "CONDA_EXE=%%~fp"
exit /b 0

:init_conda_runtime
if not defined CONDA_EXE exit /b 1
if not exist "%CONDA_ENV_DIR%\python.exe" (
  echo create conda env (runtime)...
  "%CONDA_EXE%" create -y -p "%CONDA_ENV_DIR%" python=3.11 >>"%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo ERROR: conda environment create failed.
    exit /b 1
  )
)
if not exist "%CONDA_ENV_DIR%\python.exe" (
  echo ERROR: conda environment not found after create: %CONDA_ENV_DIR%
  exit /b 1
)

set "PYTHON_EXE=%CONDA_ENV_DIR%\python.exe"
if exist "%CONDA_ENV_DIR%\Scripts" set "PATH=%CONDA_ENV_DIR%\Scripts;%PATH%"
if exist "%CONDA_ENV_DIR%\Library\bin" set "PATH=%CONDA_ENV_DIR%\Library\bin;%PATH%"
if not exist "%PYTHON_EXE%" exit /b 1
exit /b 0

:init_venv_runtime
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
      exit /b 1
    )
    set "PYTHON_EXE=python"
  )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo create venv.
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
)

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
set "VIENNARNA_MISSING="
if "%RUNTIME_MODE%"=="conda" set "VN_BASE=%CONDA_ENV_DIR%"

echo.
echo [ViennaRNA] checking local runtime and command-line executables...
call :activate_local_vienna_bin

for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if errorlevel 1 (
    set "VIENNARNA_MISSING=1"
  )
)

if not defined VIENNARNA_MISSING (
  echo ViennaRNA command-line dependencies are already available.
  exit /b 0
)

echo [ViennaRNA] required CLI not found in PATH. Checking ViennaRNA Python module/ wheel...
where RNAfold 2>nul | findstr "." >nul
if errorlevel 1 (
  "%PYTHON_EXE%" -c "import RNA" >nul 2>&1
  if errorlevel 1 (
    echo RNA module not found. Trying local ViennaRNA wheel...
    call :install_vienna_wheel_local
    if errorlevel 1 (
      echo [WARN] No local wheel installation succeeded for ViennaRNA.
    )
  ) else (
    echo RNA module already installed.
  )
) else (
  echo RNA command-line binary found on PATH.
)

for %%b in (RNAfold RNAsubopt RNAeval) do (
  call :ensure_vienna_command %%b
  if errorlevel 1 (
    set "VIENNARNA_MISSING=1"
  )
)

if defined VIENNARNA_MISSING if "%RUNTIME_MODE%"=="conda" (
  echo [ViennaRNA] still missing. trying conda install in %CONDA_ENV_DIR%...
  call :install_vienna_conda
  if errorlevel 1 (
    set "VIENNARNA_MISSING=1"
  ) else (
    set "VIENNARNA_MISSING="
    for %%b in (RNAfold RNAsubopt RNAeval) do (
      call :ensure_vienna_command %%b
      if errorlevel 1 (
        set "VIENNARNA_MISSING=1"
      )
    )
  )
)

if defined VIENNARNA_MISSING (
  echo ERROR: One or more required ViennaRNA command-line tools are missing.
  echo See above for each command and location.
  exit /b 1
)
echo ViennaRNA dependency check passed.
exit /b 0

:activate_local_vienna_bin
if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAfold" (
  if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAsubopt" (
    if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval.exe" if not exist "%LOCAL_VIENNA_BIN_DIR%\RNAeval" exit /b 0
  )
)
set "PATH=%LOCAL_VIENNA_BIN_DIR%;%PATH%"
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
  set "PATH=%FOUND_DIR%;%PATH%"
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
if exist "%CONDA_ENV_DIR%\Library\bin" set "PATH=%CONDA_ENV_DIR%\Library\bin;%PATH%"
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
