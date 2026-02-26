# bin/ 폴더 (Windows 번들용)

이 폴더에 ViennaRNA CLI 실행 파일을 넣으면 `RBS_cal-WebUI.bat`에서 자동으로 우선 사용합니다.

- `RNAfold.exe`
- `RNAsubopt.exe`
- `RNAeval.exe`

### 배치 파일 탐색 규칙
- `RBS_cal-WebUI.bat`은 시작 시 `bin` 경로를 PATH 앞에 추가합니다.
- `bin`에 위 3개 바이너리가 존재하면 별도 설치 없이 바로 탐색됩니다.
- 누락되면 기존 동작대로 런타임/conda 설치 경로를 차례로 검사합니다.

### 권장 동작
- 배포 시에는 각 `.exe`의 버전/해시를 함께 문서화하세요.
- 바이너리 제거 시 `bin` 폴더를 삭제해도 스크립트는 동작은 유지합니다(의존성 확인 단계에서 다시 설치 안내가 출력됨).
