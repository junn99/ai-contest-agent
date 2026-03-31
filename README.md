# AI Contest Agent

한국 공공 AI 공모전을 자동으로 수집, 분석, 보고서 생성까지 해주는 CLI 도구입니다.

## 뭘 하는 건가요?

```
콘테스트코리아 + 위비티 크롤링
  → AI/데이터 공모전 필터링
  → 직장인 참가 가능 여부 확인
  → Claude로 분석 + ROI 스코어링
  → 보고서(PDF) 자동 생성
  → 제출 가이드 + 마감 알림
```

정부/공공 AI 공모전 중 **전문적이지 않은 것들**을 찾아서, ROI 상위 3-5개에 집중하여 보고서를 자동 생성합니다.

## 수집 대상

| 플랫폼 | URL | 수집 카테고리 |
|--------|-----|-------------|
| 콘테스트코리아 | contestkorea.com | IT/과학 |
| 위비티 | wevity.com | 웹/모바일/IT, 과학/공학, 기획/아이디어 |

## 설치

```bash
# Python 3.12+ 필요
git clone https://github.com/junn99/ai-contest-agent.git
cd ai-contest-agent

# 의존성 설치
uv sync

# Claude Code CLI 필요 (구독)
# https://claude.ai/claude-code
```

## 사용법

```bash
# 1. 공모전 수집
uv run python -m src.main collect

# 2. Claude 분석 + ROI 스코어링
uv run python -m src.main analyze

# 3. 현황 대시보드
uv run python -m src.main status

# 4. ROI 상위 공모전 보고서 생성
uv run python -m src.main generate <contest_id>

# 5. 데이터 파일 지정하여 보고서 생성
uv run python -m src.main generate <contest_id> --data-path data.csv

# 6. 제출 가이드 확인
uv run python -m src.main guide <contest_id>

# 7. 공모전 목록
uv run python -m src.main list
```

## 파이프라인 상세

### 수집 (collect)
- 콘테스트코리아 IT/과학 카테고리 최대 5페이지 순회
- 위비티 3개 카테고리 x 3페이지 순회
- AI/데이터 키워드 자동 필터링
- 직장인 참가 가능 여부 판정 (대학생 전용 제외)
- 마감 7일 미만 제외

### 분석 (analyze)
- Claude CLI로 공모전 유형 분류 (보고서/아이디어/SW개발/데이터분석)
- 난이도 평가 (LOW/MEDIUM/HIGH)
- AI 활용 규정 확인
- ROI 스코어링 (상금 35% + 난이도 30% + 마감여유 20% + 유형적합도 15%)

### 보고서 생성 (generate)
- 공모전 요구사항 자동 파싱
- CSV/Excel 데이터 분석 (UTF-8/EUC-KR 자동 감지)
- matplotlib 시각화 (bar, heatmap, line, pie)
- Jinja2 템플릿 기반 Markdown 작성
- weasyprint로 PDF 변환 (한글 지원)
- 템플릿: 분석보고서, 아이디어제안서

### 알림
- 마감 D-14, D-7, D-3, D-1 알림
- 제출 가이드 자동 생성 (제출방법, 필요서류, 체크리스트)

## 프로젝트 구조

```
src/
├── main.py              # CLI 엔트리포인트 (typer)
├── config.py             # 설정 (pydantic-settings)
├── core/
│   ├── claude_cli.py     # Claude CLI subprocess wrapper
│   ├── state_machine.py  # 공모전 상태 관리
│   ├── storage.py        # JSON 파일 저장소
│   └── protocols.py      # ABC/Protocol 인터페이스
├── models/               # Pydantic 데이터 모델
├── collectors/            # 크롤러 (콘테스트코리아, 위비티)
├── analyzers/             # Claude 분석 + ROI 스코어링
├── generators/            # 보고서 생성 + PDF 변환
│   └── templates/         # Jinja2 보고서 템플릿
├── notifiers/             # 마감 알림 + 제출 가이드
└── dashboard/             # Rich CLI 대시보드
```

## 기술 스택

| 영역 | 기술 |
|------|------|
| 크롤링 | httpx + BeautifulSoup4 |
| LLM | Claude CLI subprocess (구독) |
| 데이터 분석 | pandas, matplotlib |
| PDF 생성 | weasyprint |
| CLI | typer + rich |
| 템플릿 | Jinja2 |
| 저장소 | JSON 파일 (PostgreSQL 선택적) |
| 테스트 | pytest (281 tests) |

## 테스트

```bash
uv run pytest tests/unit/ -v
```

## 향후 계획

- **추가 플랫폼**: 소통24, 공공데이터포털, 링커리어
- **PPT 생성**: python-pptx 기반 발표자료
- **웹 대시보드**: Streamlit
- **자동 스케줄링**: cron 기반 매일 수집

## License

MIT
