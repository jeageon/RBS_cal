# Changelog

## v1.1.04

- 런타임 성능/안정성 우선순위 패치:
  - `/run`과 `/design` 백그라운드 처리 시 기본적으로 비동기 모드를 적용할 수 있도록 `RBS_DEFAULT_ASYNC` 제어 플래그 추가.
  - 긴 입력(요청 길이 기반)은 동기 처리에서 자동으로 비동기 큐로 전환되어 `Running (xx%)` 진행률 기반 UX가 더 잘 동작하도록 반영.
  - `traceback` 노출을 제한하는 에러 포맷으로 정리되어, 클라이언트에는 내부 스택 없이 간단한 에러만 전달.
  - 설계/추론 공통 경로에서 작업 상태 조회(`/tasks/<task_id>`)의 에러 상세를 비디버그 모드에서는 `error_detail` 없이 보호.
- Windows 런처 안정화:
  - `:wait_for_server`에서 `/health` 핑을 통해 실제 서버 응답 확인 후 브라우저 자동 오픈을 진행.
  - 자동 오픈 실패율을 낮추기 위해 Python `webbrowser`부터 `rundll32`, `explorer`, PowerShell, `cmd start`까지 다단계 폴백으로 정비.
  - 배치 스크립트 진입점/로그 표시 기준 버전 문자열을 `v1.1.04`로 업데이트.

## v1.1.03

- RBS Designer 탐색 기본 동작을 성능/정확도 균형 관점에서 조정:
  - pre-sequence/CDS 1차 스크리닝 창을 각각 `RBS_DESIGN_PRESEQ_MAX_BP=50`, `RBS_DESIGN_CDS_MAX_BP=50` 기본값으로 축소.
  - truncation 발생 시 상위 후보 `topN × 2`(기본 multiplier=2)만 full-length 서열 기준으로 재평가.
  - 환경 변수 `RBS_DESIGN_FULL_REFINEMENT_MULTIPLIER`로 재평가 배수를 제어 가능.
  - API 응답 `full_refinement`에 `requested_candidates`, `refinement_multiplier`를 포함해 실제 재평가 대상량을 명시.

- 검증 체크:
  1. 긴 입력에서 `pre_length_input / cds_length_input`이 50 이상인 경우 트렁케이션 경고가 표시되는지 확인.
  2. truncation 시 `full_refinement.requested_candidates`와 `diagnostics.refinement.requested`가 기대치(`topN × multiplier`)로 산정되는지 확인.
  3. topN보다 큰 경우에도 full-length 재평가 대상이 상한(`topN × 2`)으로 제한되는지 확인.

## v1.0.15

- Stabilize ViennaRNA runtime integration (Windows):
  - Add pre-flight dependency injection/check in `app.py` so missing `RNAfold`, `RNAsubopt`, `RNAeval` can be detected before running OSTIR.
- Improve OSTIR error normalization to convert ViennaRNA PATH/module errors into actionable messages.
- Improve Windows launcher (`RBS_cal-WebUI.bat`):
  - Add ViennaRNA runtime check after dependency install.
  - Detect ViennaRNA binaries from `env/site-packages/RNA/bin` and add the directory to PATH when missing.
  - Fail with explicit diagnostics when required binaries are missing.
- Add launcher-side diagnostics output for each required ViennaRNA command (`[FOUND]/[MISSING]`) with resolved executable paths.
- Documentation update (`README.md`) with Windows runtime dependency checklist:
  - `RNA`, `RNAfold`, `RNAsubopt`, `RNAeval`.

---

## v1.0.16

- Hardened Windows ViennaRNA command discovery in `RBS_cal-WebUI.bat`:
  - Added fallback discovery that scans common venv and ViennaRNA candidate directories for `RNAfold`, `RNAsubopt`, `RNAeval`.
  - Added per-command recovery path so each missing command is traced and resolved independently.
  - Added explicit diagnostics showing which fallback directories were checked.
- Improved ViennaRNA guidance when startup still fails:
  - Keeps error text actionable with the fallback path suggestions and conda install hint.

---

## v1.0.17

- Windows launcher hardening for true one-click UX:
  - Added local ViennaRNA bundle support in `RBS_cal-WebUI.bat`.
  - Uses `<repo>\bin` first for `RNAfold`, `RNAsubopt`, `RNAeval`.
  - Uses `<repo>\libs\ViennaRNA-*.whl` as local wheel bootstrap fallback.
  - Falls back to conda install when local bundle is absent and conda is available.
  - Keeps startup diagnostics for each required ViennaRNA command and failure reasons.
- Improved ViennaRNA discovery consistency:
  - `app.py` now expands ViennaRNA candidate search paths to include project-local `bin/` and `libs/` folders.
  - Error messages now include explicit guidance for missing CLI binaries and conda PATH fixes.
- Windows runtime compatibility:
  - Re-ordered and clarified bootstrap flow to prefer conda/runtime-aware dependency installation first, then legacy `pip` path checks.
  - Reduced immediate `OSTIR` execution failures due to missing ViennaRNA command dependencies.

## Notes for users
- For best Windows 1-click reliability, place ViennaRNA executables in:
  - `bin\RNAfold(.exe)`
  - `bin\RNAsubopt(.exe)`
  - `bin\RNAeval(.exe)`
- Optional bundled wheel bootstrap:
  - `libs\ViennaRNA-<version>-cp*.whl`
- If binaries are bundled, the launcher uses them before conda/PyPI installation attempts.

---

## v1.0.20

- Windows launcher format hardening:
  - Rewrote `RBS_cal-WebUI.bat` with strict CRLF line endings.
  - Removed BOM and non-breaking spaces from the batch file.
  - Kept script text plain ASCII for CMD compatibility.

## Why this release
- This fixes environments where batch interpreter reports lines/commands as "not internal or external command" due to cross-platform text encoding/line-ending corruption.

---

## v1.0.21

- Windows launcher format hardening:
  - Rewrote `RBS_cal-WebUI.bat` with strict CRLF line endings.
  - Removed BOM and non-breaking spaces from the batch file.
  - Kept script text plain ASCII for CMD compatibility.

## Why this release
- This fixes environments where batch interpreter reports lines/commands as "not internal or external command" due to cross-platform text encoding/line-ending corruption.

---

## v1.0.22

- Windows launcher format hardening:
  - Rewrote `RBS_cal-WebUI.bat` with strict CRLF line endings.
  - Removed BOM and non-breaking spaces from the batch file.
  - Kept script text plain ASCII for CMD compatibility.

## Why this release
- This fixes environments where batch interpreter reports lines/commands as "not internal or external command" due to cross-platform text encoding/line-ending corruption.

---

## v1.0.24

- Windows launcher hardening (`RBS_cal-WebUI.bat`)
  - Reorganized startup flow to avoid unstable conditional parsing in cmd environments.
  - Fixed conda-vs-venv runtime selection branch so bootstrap failures gracefully fall back to `.venv`.
  - Kept PATH and environment setup explicit after each runtime mode.
  - Preserved dependency checks for `ostir` and `ViennaRNA` and improved recovery checks.
- Maintained CRLF-only line endings and ASCII-safe command text to avoid "expected command" parse errors under Windows CMD.
- Added deterministic failure branches for missing prerequisites (`app.py`, Python, OSTIR, ViennaRNA CLI/module checks).

## Why this release
- Previous launcher versions could fail immediately on Windows with tokenized parse errors during CMD execution. This patch makes `.bat` execution deterministic for one-click launching scenarios.

---

## v1.0.25

- Windows batch hardening update:
  - Changed PATH prepend operations from `%PATH%` to `!PATH!` in `RBS_cal-WebUI.bat` for delayed expansion safety.
  - This fixes CMD parse errors triggered by path segments containing parentheses (예: `Program Files (x86)`), especially in branches where PATH is rebuilt dynamically.
- Kept CRLF/ASCII-safe batch format.

## Why this release
- Prevents `...은(는) 예상되지 않았습니다.` / `is not recognized` style syntax breakage when launching from Windows cmd due to early PATH expansion with `%PATH%`.

---

## v1.0.26

- Improve Windows crash diagnosability and startup reliability:
  - Added explicit ViennaRNA runtime dependency precheck in `app.py` startup (`_check_viennarna_dependencies`).
  - If required RNA CLI binaries are missing, the app exits immediately with a clear `Startup dependency check failed:` message.
- Fix Windows batch log capture behavior for Flask launch:
  - Switched Flask launch command to `start /B cmd /c ...` with in-command redirection so app stdout/stderr is written into `.rbs_cal_web.log`.
  - Added startup wait-loop shortcut: if dependency check failure is detected in the log, launcher exits immediately instead of waiting 60 seconds.

## Why this release
- On Windows, missing `RNAfold.exe`, `RNAsubopt.exe`, or `RNAeval.exe` can cause silent startup-like failures where the launcher times out. This release makes those failures visible and deterministic.

---

## v1.0.27

- Added explicit Windows binary bundle workflow for ViennaRNA CLI tools.
- Added `bin/README.md` documenting drop-in packaging of `RNAfold.exe`, `RNAsubopt.exe`, `RNAeval.exe`.
- Updated README with release-bundle guidance so releases can include `bin`-level executables.

## Why this release
- Runtime still needs ViennaRNA binaries on Windows (`RNAfold`, `RNAsubopt`, `RNAeval`).
- This version clarifies and formalizes the local-bundle path (`PROJECT_DIR\\bin`) that the launcher uses before conda/PyPI fallback.

---

## v1.0.28

- Added explicit Windows executable bundle support flow and documentation.
- Added `bin/` bundle guidance so users can place `RNAfold.exe`, `RNAsubopt.exe`, `RNAeval.exe` and run without re-installing ViennaRNA.
- Added batch diagnostics for partial ViennaRNA bundles (`3/3` required binaries)
  and clearer runtime startup messaging.

## Why this release
- Makes Windows one-click usage more deterministic when distributing self-contained binaries.

---

## v1.0.29

- Hardened `RBS_cal-WebUI.bat` startup validation for OSTIR and ViennaRNA in Windows.
- Added missing `:log_ostir_binary` subroutine to avoid unresolved label failure and provide full OSTIR discovery diagnostics.
- Added detailed ViennaRNA path diagnostics (`:diagnose_vienna_path`) with:
  - command lookup results for `RNAfold`, `RNAsubopt`, `RNAeval`
  - local bundle / wheel presence checks
  - candidate runtime directories
  - path prefix dump helper (`:log_runtime_path_prefix`)
- Added stronger runtime context logs for easier crash analysis (`CONDA_PREFIX`, `PYTHON_ARGS`, top PATH entries).
- Added startup validation in Python (`app.py`) that prints candidate ViennaRNA PATH roots and missing-command hints to `stderr` when dependencies are unresolved.

## Why this release
- Windows one-click launch previously failed in environments where PATH quoting/scan context differed.
- This patch improves diagnosability and prevents script flow from halting on missing diagnostic labels while aligning Windows CLI detection behavior with user-reported edge cases.

---

## v1.0.30

- Fixed Windows startup failure where ViennaRNA module was present but CLI tools (`RNAfold`, `RNAsubopt`, `RNAeval`) were not found in PATH.
- Extended ViennaRNA candidate-scan paths in `app.py` to include:
  - `...\\Library\\bin`
  - `CONDA_PREFIX`, `CONDA_ENV_DIR`, `RBS_CAL_CONDA_ENV`, `RBS_CAL_VENV` based candidate roots
  - richer `RNA` module-relative fallback locations
- Improved `RBS_cal-WebUI.bat` runtime context:
  - always sets `RBS_CAL_VENV` for Python-side diagnostics
  - in venv mode, also checks conda env `Scripts/Library\\bin/bin` as fallback scan candidates
- Added additional startup diagnostics in logs to simplify missing ViennaRNA-CLI troubleshooting on Windows.

## Why this release
- Previous builds could report “module ok, but CLI missing” on Windows when executables were located in conda-style `Library\\bin`.
- This update closes that gap by broadening discovery order and reducing false negatives.

---

## v1.0.31

- Added support for explicit Conda environment targeting in Windows launcher (`RBS_cal-WebUI.bat`).
- New environment variable inputs are recognized in this order:
  - `RBS_CAL_CONDA_ENV`
  - `OSTIR_CONDA_ENV`
  - `CONDA_ENV_PATH`
- When one of the above is set, the launcher:
  - uses that env as `CONDA_ENV_DIR` directly,
  - validates env exists and contains `python.exe`,
  - skips fallback to local `.venv` mode,
  - writes runtime context to log for easy troubleshooting.
- Added stronger startup logging for forced mode:
  - `FORCE_CONDA_RUNTIME`
  - `FORCED_CONDA_ENV`

## Why this release
- In prior releases, Windows launcher behavior was always centered on project-local `.conda_venv`/`.venv`, which made it hard to run against a prebuilt/managed Conda env containing OSTIR + ViennaRNA.
- This release lets you run RBS_cal WebUI directly inside an already configured env, improving reproducibility in Windows deployment workflows.

---

## v1.0.32

- Fixed Windows launcher browser opening flow when `start` command/desktop defaults are unreliable.
- Added a resilient `open` routine in `RBS_cal-WebUI.bat` with fallback order:
  - PowerShell `Start-Process`
  - Python `webbrowser.open`
  - legacy `start` fallback
- Always print explicit URL before auto-open so users can copy/paste manually:
  - `Use this URL: ...`
- Preserved all existing runtime diagnostics and ViennaRNA discovery checks.

## Why this release
- Previous versions could start Flask successfully but leave no browser window open depending on environment.
- This release makes the launch path deterministic and user-verifiable while keeping startup behavior intact.

---

## v1.0.33

- Hardened Windows browser auto-open flow in `RBS_cal-WebUI.bat` when startup is successful.
- Added multiple fallback launch methods:
  - `explorer` -> `PowerShell Start-Process` -> Python `webbrowser` -> `start`.
- Added explicit user guidance when auto-open fails and ensures URL is always shown.

## Why this release
- Addresses cases where Windows environment blocks one browser launch path (or it is silent-failing) while Flask itself is already running normally.

---

## v1.0.34

- Windows launcher (`RBS_cal-WebUI.bat`):
  - Strengthened browser auto-open fallback path by prioritizing the system URL handler (`rundll32 url.dll,FileProtocolHandler`) before explorer/powershell/python fallbacks.
  - This improves reliability in Windows environments where default `start`/`explorer` behavior is inconsistent.

## Verification
- If server starts successfully, URL is now attempted to open via multiple launchers with explicit logs for success/failure.
- If it still does not open automatically, manual open is still available via printed URL.

## Notes
- This release does not change calculation logic in `/run` or `/design`; it only updates Windows launch behavior for the one-click `.bat` entry point.

---

## v1.0.35


- Windows launcher (`RBS_cal-WebUI.bat`):
  - 기본 실행 방식을 **로컬 우선 모드**로 전환했습니다.
    - 기본값: `RBS_CAL_ALLOW_CONDA=0` (콘다 자동 탐지 비활성화)
    - `RBS_CAL_ALLOW_CONDA=1` 설정 시에만 기존 콘다 탐색 경로로 복귀
  - `bin\`/`libs\` 패키지 폴더를 ViennaRNA 우선 소스로 사용하도록 정리했습니다.
  - 콘다 강제 모드(`FORCED_CONDA`/`RBS_CAL_CONDA_ENV`)가 아닌 경우, 의존성 설치 후 ViennaRNA가 여전히 없으면 더 이상 콘다 복구로 내려가지 않고 즉시 실패하도록 변경했습니다.
  - venv 런타임에서 기존 `.conda_venv` 경로를 PATH 우선권에 포함하지 않도록 수정해 런타임 충돌 가능성을 낮췄습니다.

## Why this change

- 이전 버전에서는 콘다 자동 탐지 때문에 불필요한 환경 구성/성능 오버헤드가 생기고, ViennaRNA CLI fallback 경로가 복잡해졌습니다.
- 1.0.10 동작 성격(가벼운 venv 중심 로컬 실행)을 유지하면서, 패키지 폴더(`bin`,`libs`)에 ViennaRNA를 넣으면 바로 동작하도록 정리했습니다.

## Verification

- `RBS_CAL_ALLOW_CONDA` 기본값을 비활성으로 두었을 때 콘다 탐지가 스킵되는지 로그 확인.
- `RBS_CAL_ALLOW_CONDA=0`에서 `bin\` 또는 `libs\`를 채운 뒤 배치 실행 시 ViennaRNA 체크가 통과되는지 확인.
- `RBS_CAL_ALLOW_CONDA=0`에서 로컬 리소스가 없을 경우 `ViennaRNA` 체크가 명시적으로 실패하고 종료되는지 확인.
- 여전히 콘다 고정 실행이 필요한 환경은 `RBS_CAL_CONDA_ENV` 또는 `RBS_CAL_ALLOW_CONDA=1`로 검증.


---

## v1.1.02

- RBS Designer 성능/정확도 균형 보강:
  - pre-sequence/cds 길이가 200 bp를 넘는 경우 탐색 구간을 각각 RBS 인접 200 bp / 시작코돈 이후 200 bp로 제한하여 계산 부하를 안정화.
  - Top candidates(`topN`)만 full-length 서열 기준으로 재평가해 최종 순위를 갱신.
  - `full-length` 재평가에서 통과/거절 집계와 truncation 경고를 API 응답으로 반환.
- 디자인 결과 화면에 truncation 및 full-length 재평가 상태 메시지를 표시.

## 실행/검증 체크

1. 긴 입력에서 `full_refinement.enabled`와 `requested/attempted/accepted/rejected` 수치가 적정하게 갱신되는지 확인.
2. `pre_length_input > 200` 또는 `cds_length_input > 200`인 경우에만 분석 창 길이 축소 경고가 표시되는지 확인.
3. `topN` 후보만 재평가되어야 하며, Top 후보 미달 시에도 안정적으로 정렬/출력되는지 확인.

---

## v1.1.01


- Windows Launcher (`RBS_cal-WebUI.bat`)를 macOS의 1.0.10 동작 스타일에 맞춘 **로컬 venv-only 실행 경로**로 정리했습니다.
- ViennaRNA 의존성 해결을 `bin/`(우선) + `libs/`(wheel bootstrap) 기반으로 고정했습니다.
- `start` 실행 라인을 정비해 Windows에서 앱이 즉시 백그라운드로 실행되도록 개선했습니다.
- Windows README/`bin`/`libs` 문서를 정리해 **로컬 패키지 폴더 기준 배포**를 명확히 했습니다.
- 로그/메시지에서 현재 버전(`1.1.01`)과 순서를 표기해 의존성 원인 추적을 빠르게 했습니다.
- RBS Designer에서 상위 N개(topN) 후보만 추려 전체 길이 서열 기준으로 재평가하도록 변경했습니다.
- Pre-sequence/CDS가 200 bp를 넘는 경우 분석 창은 각 측면 인접 200 bp만 사용하고,
  검색 후보는 `topN`개만 full-length 재평가해 정확도/속도의 균형을 맞췄습니다.

## 버전 정책

- 이번 버전은 기존 1.0.x에서 사용하던 로컬 기반 실행 UX를 유지하면서,
  `RBS_cal-WebUI.bat`의 의존성 탐색 규칙을 단순화한 패치입니다.

## 실행/검증 가이드

1. `RBS_cal-WebUI.bat` 더블 클릭
2. 콘솔/로그에서 순차적으로 확인
   - `[RUNTIME] using local venv mode for RBS_cal v1.1.01`
   - `[ViennaRNA] trying local wheel install from ...\libs`
   - `ViennaRNA command-line dependencies are ready.`
   - `Running on http://127.0.0.1:PORT`
3. 브라우저 자동 오픈 동작 확인
4. 실패 시 `.rbs_cal_web.log`에서 `[MISSING]`/`ERROR` 메시지 확인

---
