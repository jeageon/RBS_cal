# RBS_cal

RBS expression estimation and RBS design web UI powered by OSTIR.

## Features
- RBS Calculator: sequence/file input -> OSTIR prediction and table/graph output.
- RBS Designer: target expression 기반 RBS 후보군 추천.
- Result export, command logging, and web visualization.

## Recommended environment
- Python 3.10+ (or newer)
- `ostir` executable installed and accessible.
- ViennaRNA Python module (`RNA`) and ViennaRNA CLI tools (`RNAfold`, `RNAsubopt`, `RNAeval`) in PATH.

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
- `conda`가 감지되면 우선 프로젝트 폴더의 `.conda_venv`를 사용해 실행 환경을 구성합니다.
- conda 모드에서는 `conda` 환경에 `python`, `ostir`, `ViennaRNA`를 설치하고, `Library\bin`을 PATH에 반영해 `RNAfold`, `RNAsubopt`, `RNAeval`를 자동으로 찾습니다.
- conda가 없으면 기존 동작처럼 `.venv\Scripts\python.exe`를 사용하고, 없으면 생성 후 의존성 설치를 진행합니다.
- Selects an available port in 8000~8010.
- Starts Flask server and opens default browser to `http://127.0.0.1:8000` (or selected port).
- Writes logs to `.rbs_cal_web.log`.

If OSTIR is not auto-discovered, set explicitly:
```bat
set OSTIR_BIN=C:\path\to\ostir.exe
RBS_cal-WebUI.bat
```

If startup logs show missing ViennaRNA CLI, check:
- `where RNAfold`
- `where RNAsubopt`
- `where RNAeval`

If you ship bundled ViennaRNA runtime files with this repository:
- put `ViennaRNA-*.whl` into `libs\` (wheel bootstrap), and/or
- put `RNAfold`, `RNAsubopt`, `RNAeval` into `bin\`.
- The launcher checks `bin\` and `libs\` first, then tries conda/PyPI fallback.

The launcher logs each check as:
- `[FOUND] RNAfold` / `[MISSING] RNAfold`

If CLI installation continues to fail in conda mode:
```bat
conda activate "%~dp0.conda_venv"
conda install -c conda-forge -c bioconda viennarna
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
