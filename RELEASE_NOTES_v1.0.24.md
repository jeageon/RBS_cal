# RBS_cal v1.0.24

## What changed
- Windows launcher hardening (`RBS_cal-WebUI.bat`)
  - Reorganized startup flow to avoid unstable conditional parsing in cmd environments.
  - Fixed conda-vs-venv runtime selection branch so bootstrap failures gracefully fall back to `.venv`.
  - Kept PATH and environment setup explicit after each runtime mode.
  - Preserved dependency checks for `ostir` and `ViennaRNA` and improved recovery checks.
- Maintained CRLF-only line endings and ASCII-safe command text to avoid "expected command" parse errors under Windows CMD.
- Added deterministic failure branches for missing prerequisites (`app.py`, Python, OSTIR, ViennaRNA CLI/module checks).

## Why this release
- Previous launcher versions could fail immediately on Windows with tokenized parse errors during CMD execution. This patch makes `.bat` execution deterministic for one-click launching scenarios.
