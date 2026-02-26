# RBS_cal v1.0.34

## What's Changed
- Windows launcher (`RBS_cal-WebUI.bat`):
  - Strengthened browser auto-open fallback path by prioritizing the system URL handler (`rundll32 url.dll,FileProtocolHandler`) before explorer/powershell/python fallbacks.
  - This improves reliability in Windows environments where default `start`/`explorer` behavior is inconsistent.

## Verification
- If server starts successfully, URL is now attempted to open via multiple launchers with explicit logs for success/failure.
- If it still does not open automatically, manual open is still available via printed URL.

## Notes
- This release does not change calculation logic in `/run` or `/design`; it only updates Windows launch behavior for the one-click `.bat` entry point.
