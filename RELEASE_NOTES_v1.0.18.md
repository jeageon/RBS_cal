# RBS_cal v1.0.18

## What changed
- Windows launcher format hardening:
  - Rewrote `RBS_cal-WebUI.bat` with strict CRLF line endings.
  - Removed BOM and non-breaking spaces from the batch file.
  - Kept script text plain ASCII for CMD compatibility.

## Why this release
- This fixes environments where batch interpreter reports lines/commands as "not internal or external command" due to cross-platform text encoding/line-ending corruption.
