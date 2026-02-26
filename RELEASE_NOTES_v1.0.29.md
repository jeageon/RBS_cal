# RBS_cal v1.0.29

## What changed
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
