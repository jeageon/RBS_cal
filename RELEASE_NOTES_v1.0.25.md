# RBS_cal v1.0.25

## What changed
- Windows batch hardening update:
  - Changed PATH prepend operations from `%PATH%` to `!PATH!` in `RBS_cal-WebUI.bat` for delayed expansion safety.
  - This fixes CMD parse errors triggered by path segments containing parentheses (예: `Program Files (x86)`), especially in branches where PATH is rebuilt dynamically.
- Kept CRLF/ASCII-safe batch format.

## Why this release
- Prevents `...은(는) 예상되지 않았습니다.` / `is not recognized` style syntax breakage when launching from Windows cmd due to early PATH expansion with `%PATH%`.
