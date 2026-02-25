# RBS_cal v1.0.16

## What changed
- Hardened Windows ViennaRNA command discovery in `RBS_cal-WebUI.bat`:
  - Added fallback discovery that scans common venv and ViennaRNA candidate directories for `RNAfold`, `RNAsubopt`, `RNAeval`.
  - Added per-command recovery path so each missing command is traced and resolved independently.
  - Added explicit diagnostics showing which fallback directories were checked.
- Improved ViennaRNA guidance when startup still fails:
  - Keeps error text actionable with the fallback path suggestions and conda install hint.
