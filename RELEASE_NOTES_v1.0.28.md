# RBS_cal v1.0.28

## What changed
- Added explicit Windows executable bundle support flow and documentation.
- Added `bin/` bundle guidance so users can place `RNAfold.exe`, `RNAsubopt.exe`, `RNAeval.exe` and run without re-installing ViennaRNA.
- Added batch diagnostics for partial ViennaRNA bundles (`3/3` required binaries)
  and clearer runtime startup messaging.

## Why this release
- Makes Windows one-click usage more deterministic when distributing self-contained binaries.
