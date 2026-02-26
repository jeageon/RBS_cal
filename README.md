# RBS_cal (v1.1.02)

RBS expression estimation and RBS design web UI powered by OSTIR.

## Features
- RBS Calculator: sequence/file input -> OSTIR prediction and table/graph output.
- RBS Designer: target expression 기반 RBS 후보군 추천.
- 입력 서열이 매우 길어도 처리 안정성을 위해 Pre-sequence는 RBS 인접 50 bp,
  CDS는 start codon 기준으로 50 bp까지만 탐색에 사용되며,
  상위 후보 `topN × 2`개만 최종적으로 전체 길이 서열에서 재평가합니다.
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
- 버전: `v1.1.03`
- 로컬 `.venv` 기반 실행입니다. (`.conda_venv` 자동 생성/실행은 사용하지 않음)
- ViennaRNA는 우선순위로 다음을 사용합니다.
  1) `bin\` 폴더의 CLI (`RNAfold`, `RNAsubopt`, `RNAeval`, 확장자 `.exe` 포함)
  2) `libs\` 폴더의 `ViennaRNA-*.whl` 자동 설치 및 모듈/CLI 검증
  3) 기본 `requirements.txt` 의존성 설치
- 8000~8010 범위에서 사용 가능한 포트를 찾아 자동으로 실행합니다.
- 성공 시 기본 브라우저가 자동 오픈되며, URL은 `.rbs_cal_web.log` 또는 콘솔에 출력됩니다.
- 실행 로그는 `.rbs_cal_web.log`에 남습니다.

### ViennaRNA 로컬 번들 사용 가이드
릴리즈의 핵심 규칙:
1. 먼저 `bin\` 폴더에서 CLI 바이너리를 확인합니다.
2. 없으면 `libs\ViennaRNA-*.whl`를 설치해 Python 모듈 및 CLI를 검증합니다.
3. 검증 실패 시 실행을 중단하고 원인 메시지를 로그에 출력합니다.

권장 구조(패키지에 포함):
- `bin\RNAfold(.exe)`
- `bin\RNAsubopt(.exe)`
- `bin\RNAeval(.exe)`
- 또는 `libs\ViennaRNA-*.whl` 1개 이상

원클릭으로 wheel만 먼저 받아 두려면:
```bat
python -m pip download ViennaRNA>=2.6.4 -d libs --only-binary=:all:
```

> 참고: `requirements.txt`에는 `ViennaRNA>=2.6.4`가 남아 있습니다. 그러나 실행은 `bin\`/`libs` 우선 정책으로 통제합니다.

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
- The launcher checks `bin\` and `libs\` first, then validates CLI availability and aborts on missing runtime.

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
- Consolidated release history is maintained in `CHANGELOG.md`.
