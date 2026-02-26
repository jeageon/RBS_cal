# bin/ 폴더 (Windows 번들용)

이 폴더에 ViennaRNA CLI 실행 파일을 넣으면 `RBS_cal-WebUI.bat`에서 자동으로 우선 사용합니다.

- `RNAfold.exe`
- `RNAsubopt.exe`
- `RNAeval.exe`

### 배치 파일 탐색 규칙
- `RBS_cal-WebUI.bat`은 시작 시 `bin` 경로를 PATH 앞에 추가합니다.
- `bin`에 위 3개 바이너리가 존재하면 별도 설치 없이 바로 탐색됩니다.
- 누락되면 `libs\ViennaRNA-*.whl` 설치 후 CLI 가능 여부를 검증합니다.

### 권장 동작
- 배포 시에는 각 `.exe`의 버전/해시를 함께 문서화하세요.
- 바이너리 제거 시에도 `libs\` 폴더에 wheel이 준비되어 있으면 자동 설치/실행이 가능합니다.
