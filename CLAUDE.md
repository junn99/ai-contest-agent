# 공모전 에이전트 (codename: infoke) — AI 공모전 자동 수집/분석 시스템

## 프로젝트 개요
한국 공공 AI 공모전을 자동 수집, 분석, 보고서 생성하는 CLI 도구 + 텔레그램 봇 + GitHub Pages 웹 대시보드.
데이터는 `data/` 폴더에 JSON으로 저장됨. `scripts/build_webapp.sh`로 webapp/data/ 동기화.

## 텔레그램 채널 규칙
텔레그램 메시지가 들어오면 반드시 아래 순서를 따를 것:

1. **즉시 수신 확인 메시지를 보낸다** — 요청을 받았고 작업 중임을 알린다. 예: "확인! 공모전 수집 중..." / "잠깐만, 분석 돌리는 중..."
2. 작업을 수행한다.
3. 작업이 오래 걸리면 (30초 이상) 중간 진행 상황을 `edit_message`로 업데이트한다. 예: "수집 완료, 분석 시작..."
4. 완료되면 최종 결과를 보낸다.

## CLI 명령어
- `uv run python -m src.main collect` — 공모전 크롤링
- `uv run python -m src.main analyze` — Claude 분석 + ROI 스코어링
- `uv run python -m src.main run` — 전체 파이프라인 실행
- `uv run python -m src.main status` — 현황 대시보드
- `uv run python -m src.main generate <id>` — 보고서 생성

## 데이터 경로
- `data/contests.json` — 수집된 공모전
- `data/analyses.json` — 분석 결과
- `data/artifacts.json` — 생성된 보고서 목록
