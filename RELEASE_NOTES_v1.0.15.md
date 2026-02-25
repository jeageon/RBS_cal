# RBS_cal v1.0.15

## What changed
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
