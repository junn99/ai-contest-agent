#!/usr/bin/env bash
# 매일 자동 실행: 수집 → 분석 → 보고서 → 알림
#
# [cron 정책]
# - 이 스크립트는 `run` 명령만 호출한다. `run`은 내부에서 자동으로 다이제스트 카드를 push한다.
# - `digest` 명령은 수동 트리거 전용이다. cron에 등록하면 다이제스트가 2회 전송된다.
# - 권장 cron 예시 (매일 08:00):
#     0 8 * * * /home/jun99/claude/infoke/scripts/daily_run.sh >> /home/jun99/claude/infoke/logs/cron.log 2>&1
# - 중복 실행 방지: flock 사용 권장
#     0 8 * * * flock -n /tmp/infoke.lock /home/jun99/claude/infoke/scripts/daily_run.sh
set -euo pipefail

PROJECT_DIR="/home/jun99/claude/infoke"
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/run_${TIMESTAMP}.log"

cd "$PROJECT_DIR"

echo "=== infoke 자동 실행 시작: $(date) ===" | tee "$LOG_FILE"

/home/jun99/.local/bin/uv run python -m src.main run 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

# webapp/data/ 동기화 (GitHub Pages 배포용)
bash "${PROJECT_DIR}/scripts/build_webapp.sh" 2>&1 | tee -a "$LOG_FILE" || true

echo "=== 실행 완료: $(date) (exit: $EXIT_CODE) ===" | tee -a "$LOG_FILE"

# 7일 이상 된 로그 자동 정리
find "$LOG_DIR" -name "run_*.log" -mtime +7 -delete 2>/dev/null || true

exit $EXIT_CODE
