# libs/ (Windows 로컬 ViennaRNA 번들)

`RBS_cal-WebUI.bat`은 다음 우선순위로 ViennaRNA 런타임을 준비합니다.

1. `bin\` 폴더의 CLI 바이너리(`RNAfold`, `RNAsubopt`, `RNAeval`) 사용
2. `libs\ViennaRNA-*.whl` 설치 후 CLI 재검증

## 패키지 파일 규격

- `ViennaRNA-<ver>-cp<pyver>-cp<pyver>-<platform>.whl`
  - 예: `ViennaRNA-2.7.2-cp311-cp311-win_amd64.whl`

## 사용 가이드

1. 해당 파일을 `libs\` 에 한 개 이상 둡니다.
2. `RBS_cal-WebUI.bat`을 실행합니다.
3. 배치가 설치를 시도하고 CLI 위치(`RNAfold`, `RNAsubopt`, `RNAeval`)를 확인합니다.

## 참고

- wheel은 OS/파이썬 버전이 맞아야 합니다.
- CLI가 `bin\`에 함께 있으면 wheel이 없어도 실행이 더 빠르게 시작됩니다.
