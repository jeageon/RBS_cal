# RBS_cal

RBS expression estimation and RBS design web UI powered by OSTIR.

## Features
- RBS Calculator: sequence/file input -> OSTIR prediction and table/graph output.
- RBS Designer: target expression 기반 RBS 후보군 추천.
- Result export, command logging, and web visualization.

## Recommended environment
- Python 3.10+ (or newer)
- `ostir` executable installed and accessible.
- On Windows, `ostir` requires both the ViennaRNA Python module (`RNA`) and ViennaRNA CLI tools (`RNAfold`, `RNAsubopt`, `RNAeval`) in PATH.

## Quick start (macOS)
```bash
cd /Users/jg/Documents/RBS_cal
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:8000`.

## One-click launch (macOS desktop shortcut)
Use the mac shortcut script:
- `~/Desktop/RBS_cal-WebUI.command`

This script creates/uses `.venv`, installs required packages, selects an available port (8000~8010), starts Flask, and opens your browser.

## One-click launch (Windows)
Windows launcher is included:
- `RBS_cal-WebUI.bat`

Run this `.bat` file by double-clicking.

Behavior:
- Uses existing `.venv\Scripts\python.exe` if present, otherwise creates `.venv` and installs dependencies.
- Selects an available port in 8000~8010.
- Starts Flask server in background.
- Opens default browser to `http://127.0.0.1:8000` (or selected port).
- Writes logs to `.rbs_cal_web.log`.

If OSTIR is not auto-discovered, set explicitly:
```bat
set OSTIR_BIN=C:\path\to\ostir.exe
RBS_cal-WebUI.bat
```

If startup returns `ModuleNotFoundError: No module named 'RNA'`, install ViennaRNA in the launcher venv:
```bat
%VENV_DIR%\Scripts\python.exe -m pip install ViennaRNA
```

If startup succeeds but `OSTIR` still fails with `ViennaRNA is not properly installed or in PATH`, make sure one of the following is true:
- `where RNAfold` returns a valid path.
- `where RNAsubopt` returns a valid path.
- `where RNAeval` returns a valid path.
- If missing, add the ViennaRNA bin folder to the launcher environment PATH (the bat file now tries:
  `<VENV_DIR>\\Lib\\site-packages\\RNA\\bin`).

또한 배치파일 실행 시 아래 진단 로그를 같이 확인할 수 있습니다.
- `[FOUND] RNAfold` / `[MISSING] RNAfold` 형식으로 각 바이너리 존재 여부 출력
- 누락이 있으면 바로 실패 사유를 표시합니다.

If installation fails, use the ViennaRNA install method that matches your Windows environment (binary/conda path) and run the launcher again.

## Project structure
```text
.
├── app.py
├── templates/
├── static/
├── requirements.txt
├── README.md
├── RBS_cal-WebUI.bat
```

## Notes
- If OSTIR output is not usable, the web UI still starts; only prediction/design requests fail until `ostir` becomes available.
- For macOS system Python restrictions, always use a virtual environment as above or the provided shortcut.

## Versioning and release
- Tag naming: `vX.Y.Z`
- Keep this repository as the source of record for release artifacts and installation scripts.
