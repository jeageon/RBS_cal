# RBS_cal v1.0.26

## What changed
- Improve Windows crash diagnosability and startup reliability:
  - Added explicit ViennaRNA runtime dependency precheck in `app.py` startup (`_check_viennarna_dependencies`).
  - If required RNA CLI binaries are missing, the app exits immediately with a clear `Startup dependency check failed:` message.
- Fix Windows batch log capture behavior for Flask launch:
  - Switched Flask launch command to `start /B cmd /c ...` with in-command redirection so app stdout/stderr is written into `.rbs_cal_web.log`.
  - Added startup wait-loop shortcut: if dependency check failure is detected in the log, launcher exits immediately instead of waiting 60 seconds.

## Why this release
- On Windows, missing `RNAfold.exe`, `RNAsubopt.exe`, or `RNAeval.exe` can cause silent startup-like failures where the launcher times out. This release makes those failures visible and deterministic.
