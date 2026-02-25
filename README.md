# RBS_cal

RBS expression estimation and RBS design web UI powered by OSTIR.

## Features
- RBS Calculator: sequence/file input -> OSTIR prediction and table/graph output.
- RBS Designer: target expression 기반 RBS 후보군 추천.
- Result export, command logging, and web visualization.

## Recommended environment
- Python 3.10+ (or newer)
- `ostir` executable installed and accessible.

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
