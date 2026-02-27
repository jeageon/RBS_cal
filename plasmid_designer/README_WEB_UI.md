# Plasmid Insertion Planner Web UI

## 실행

```bash
python plasmid_web_ui.py
```

기본 주소: `http://127.0.0.1:7860`

## 요구 패키지

- Flask
- BioPython (기존 파이프라인 의존)

설치:

```bash
pip install flask biopython
```

## 동작

- GenBank 파일 업로드
- 모드/전략/제한 조건 입력
- 결과에서:
  - Safe-zone 목록
  - Top 후보 테이블(점수/리스크/거리/이유)
  - JSON 리포트 표시 및 복사
- API 사용:
  - `POST /run` (HTML form)
  - `POST /api/run` (multipart + form fields, JSON 응답)
  - `GET /api/sanity` (sanity 체크)

수동 태그는 textarea 한 줄당 `key=value` 형식으로 입력하세요.
