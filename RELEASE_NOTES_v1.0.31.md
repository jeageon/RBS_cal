# RBS_cal v1.0.31

## What changed
- Added support for explicit Conda environment targeting in Windows launcher (`RBS_cal-WebUI.bat`).
- New environment variable inputs are recognized in this order:
  - `RBS_CAL_CONDA_ENV`
  - `OSTIR_CONDA_ENV`
  - `CONDA_ENV_PATH`
- When one of the above is set, the launcher:
  - uses that env as `CONDA_ENV_DIR` directly,
  - validates env exists and contains `python.exe`,
  - skips fallback to local `.venv` mode,
  - writes runtime context to log for easy troubleshooting.
- Added stronger startup logging for forced mode:
  - `FORCE_CONDA_RUNTIME`
  - `FORCED_CONDA_ENV`

## Why this release
- In prior releases, Windows launcher behavior was always centered on project-local `.conda_venv`/`.venv`, which made it hard to run against a prebuilt/managed Conda env containing OSTIR + ViennaRNA.
- This release lets you run RBS_cal WebUI directly inside an already configured env, improving reproducibility in Windows deployment workflows.
