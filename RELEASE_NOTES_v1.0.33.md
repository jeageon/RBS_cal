# RBS_cal v1.0.33

## What changed
- Hardened Windows browser auto-open flow in `RBS_cal-WebUI.bat` when startup is successful.
- Added multiple fallback launch methods:
  - `explorer` -> `PowerShell Start-Process` -> Python `webbrowser` -> `start`.
- Added explicit user guidance when auto-open fails and ensures URL is always shown.

## Why this release
- Addresses cases where Windows environment blocks one browser launch path (or it is silent-failing) while Flask itself is already running normally.
