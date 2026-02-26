# RBS_cal v1.0.30

## What changed
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
