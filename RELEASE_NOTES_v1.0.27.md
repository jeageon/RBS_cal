# RBS_cal v1.0.27

## What changed
- Added explicit Windows binary bundle workflow for ViennaRNA CLI tools.
- Added `bin/README.md` documenting drop-in packaging of `RNAfold.exe`, `RNAsubopt.exe`, `RNAeval.exe`.
- Updated README with release-bundle guidance so releases can include `bin`-level executables.

## Why this release
- Runtime still needs ViennaRNA binaries on Windows (`RNAfold`, `RNAsubopt`, `RNAeval`).
- This version clarifies and formalizes the local-bundle path (`PROJECT_DIR\\bin`) that the launcher uses before conda/PyPI fallback.
