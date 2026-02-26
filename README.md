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

You can force the launcher to use one pre-existing Conda env instead of creating `.conda_venv`:
```bat
set "RBS_CAL_CONDA_ENV=C:\Users\...\envs\myenv"
RBS_cal-WebUI.bat
```
Notes:
- `python.exe` must exist in the forced env root (`<env>\\python.exe`).
- `RNAfold`, `RNAsubopt`, `RNAeval` must be available in PATH (or inside conda env `Library\\bin`).

If you ship bundled ViennaRNA runtime files with this repository:
- put `ViennaRNA-*.whl` into `libs\` (wheel bootstrap), and/or
- put `RNAfold`, `RNAsubopt`, `RNAeval` into `bin\`.
- The launcher checks `bin\` and `libs\` first, then tries conda/PyPI fallback.

### Windows 배포용 바이너리 번들링 (권장)
릴리즈 압축본에 실행 파일을 같이 넣으려면, 프로젝트 루트에 `bin` 폴더를 만들고 다음 파일을 그대로 넣으면 됩니다.

1. `RNAfold.exe`
2. `RNAsubopt.exe`
3. `RNAeval.exe`

동봉 시 `bin`은 자동으로 PATH 우선순위 상단에 추가되며, 배치 파일이 가장 먼저 `bin`의 바이너리를 사용합니다.

릴리즈 ZIP 생성 예시(현재 저장소 기준):
```bash
cd /Users/jg/Documents/RBS_cal
mkdir -p dist
zip -r "dist/RBS_cal-Windows-bundle.zip" \
  RBS_cal-WebUI.bat app.py requirements.txt templates README.md \
  bin libs
```

또는 단순하게 현재 폴더 전체를 압축하되, `.venv`/`.rbs_cal_web.log`/`.DS_Store`만 제외하면 됩니다.

주의:
- `bin` 내부 바이너리는 라이선스/배포 조건을 확인한 뒤 넣어주세요.
- 바이너리 용량이 크다면 GitHub 릴리즈 업로드 용량 정책(일반적으로 2GB)을 확인하세요.
- 기존처럼 별도 설치 환경에서 동작시키려면 `bin`을 비워두고 동작합니다.

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
