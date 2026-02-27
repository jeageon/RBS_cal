# RBS_cal Release Notes

## v1.1.09 (현재 릴리즈)

### 주요 변경
- `OSTIR` 예측 결과 CSV 파서의 헤더 검사 규칙을 강화했습니다.
  - `start_codon`과 `start_position` 헤더가 모두 있을 때만 결과 행을 파싱하도록 변경
  - 기존처럼 헤더가 부분적으로 누락되어도 과도하게 채택되던 오동작 방지
- CSV 파싱 예외 메시지를 보수적으로 정리하여 잘못된 형식 입력 시 조기 종료되도록 개선
- 변경 이력 동기화를 위해 상단 릴리즈 노트를 즉시 갱신

## v1.1.08

### 주요 변경
- Windows 배포 가이드와 런처 메시지의 버전을 `1.1.08`로 정렬.
- `README`의 ViennaRNA 로컬 번들 안내를 `bin` 표기에서 `libs` 중심으로 통합.
- `libs\\RNAfold/RNAsubopt/RNAeval` 우선 정책을 문서와 런처 동작이 일치하도록 정리.

## v1.1.07

- Windows 런처의 ViennaRNA 기본 탐색 경로를 `libs` 루트 중심으로 통합.
- `RNAfold`, `RNAsubopt`, `RNAeval` 3개 CLI 바이너리 시작 시 명시적 사전 점검 추가.
- 배포 노트 분할 정리 정합성 개선.

## v1.1.06

- RBS Designer 비동기 처리 안정화.
- `POST /design` 후 백그라운드 Task 시작 및 `/tasks/<task_id>` 완료/실패 상태 플로우 정합성 개선.

## v1.1.05

- macOS 자동 브라우저 오픈 UX 강화.
- Flask 실행 상태 확인/오류 노출 흐름 정비.

---

기타 기존 변경 사항과 자세한 내역은 `CHANGELOG.md`를 참고하세요.
