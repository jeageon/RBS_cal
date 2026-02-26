# RBS_cal v1.0.32

## What changed
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
