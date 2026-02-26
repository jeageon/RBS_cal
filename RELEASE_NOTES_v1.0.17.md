# RBS_cal v1.0.17

## What changed
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
