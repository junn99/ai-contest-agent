# 공모전 에이전트 (codename: infoke)

한국 공공 AI 공모전을 자동으로 수집, 분석, 보고서 생성까지 해주는 CLI 도구 + 텔레그램 봇 + 웹 대시보드.

## 뭘 하는 건가요?

```
콘테스트코리아 + 위비티 크롤링
  → AI/데이터 공모전 필터링
  → 직장인 참가 가능 여부 확인
  → Claude로 분석 + ROI 스코어링
  → 보고서(PDF) 자동 생성
  → 제출 가이드 + 마감 알림
  → 텔레그램 다이제스트 카드 전송
  → WebApp 대시보드 (GitHub Pages)
```

정부/공공 AI 공모전 중 **전문적이지 않은 것들**을 찾아서, ROI 상위 3-5개에 집중하여 보고서를 자동 생성합니다.

## WebApp 대시보드

GitHub Pages로 배포되는 정적 웹 대시보드:

- 공모전 카드 (D-day, ROI, 난이도)
- 마감 필터, ROI 정렬, 키워드 검색
- 텔레그램 봇 인라인 버튼 연동

배포 URL: `https://<your-github-username>.github.io/<repo-name>/`

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

# 환경변수 설정 (.env)
cp .env.example .env
# ANTHROPIC_API_KEY, INFOKE_TELEGRAM_BOT_TOKEN, INFOKE_TELEGRAM_CHAT_ID 설정
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

# 5. 전체 파이프라인 자동 실행
uv run python -m src.main run

# 6. 텔레그램 봇 실행
uv run python -m src.main bot

# 7. WebApp 데이터 빌드 (webapp/data/ 동기화)
bash scripts/build_webapp.sh
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

### 알림
- 마감 D-14, D-7, D-3, D-1 알림
- 텔레그램 다이제스트 카드 (ROI 상위 N개)
- 제출 가이드 자동 생성

### GitHub Pages 자동 배포
- push to main 또는 매일 09:00 KST에 CI 실행
- `scripts/build_webapp.sh` → `webapp/data/` 동기화 → Pages 배포

## 프로젝트 구조

```
src/
├── main.py              # CLI 엔트리포인트 (typer)
├── config.py             # 설정 (pydantic-settings)
├── core/                 # 상태 머신, 저장소, Claude CLI
├── models/               # Pydantic 데이터 모델
├── collectors/            # 크롤러 (콘테스트코리아, 위비티)
├── analyzers/             # Claude 분석 + ROI 스코어링
├── generators/            # 보고서 생성 + PDF 변환
├── notifiers/             # 텔레그램 알림 + 뷰 포맷터
├── bot/                   # 텔레그램 봇 (long polling)
└── dashboard/             # Rich CLI 대시보드
webapp/                    # GitHub Pages 정적 사이트
scripts/
├── build_webapp.sh        # data/*.json → webapp/data/ 동기화
└── daily_run.sh           # cron 자동 실행 스크립트
.github/workflows/
└── webapp-deploy.yml      # GitHub Pages CI/CD
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
| 저장소 | JSON 파일 |
| 봇 | Telegram Bot API (long polling) |
| WebApp | Vanilla JS + GitHub Pages |
| 테스트 | pytest |

## 테스트

```bash
uv run pytest tests/unit/ -v
```

## License

MIT
