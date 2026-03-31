"""ROI scorer — pure calculation, no Claude calls."""
import structlog

from src.models.analysis import ContestAnalysis
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)

# Days-remaining score lookup
_DEADLINE_SCORES: list[tuple[int, float]] = [
    (30, 9.0),
    (14, 7.0),
    (7, 4.0),
    (0, 1.0),
]

# Difficulty score lookup
_DIFFICULTY_SCORES: dict[str, float] = {
    "LOW": 9.0,
    "MEDIUM": 5.0,
    "HIGH": 2.0,
}

# Type-fit score lookup
_TYPE_FIT_SCORES: dict[str, float] = {
    "보고서": 9.0,
    "아이디어": 9.0,
    "데이터분석": 7.0,
    "SW개발": 3.0,
    "기타": 5.0,
}


class ROIScorer:
    """ROI 스코어 계산기 (Claude 호출 없음)"""

    WEIGHTS: dict[str, float] = {
        "prize": 0.35,
        "difficulty": 0.30,
        "deadline": 0.20,
        "type_fit": 0.15,
    }

    def calculate(
        self, analysis: ContestAnalysis, contest: ContestInfo
    ) -> tuple[float, dict]:
        """ROI 스코어 (0~10) + breakdown dict 반환"""
        prize_score = self._prize_score(contest.prize_amount)
        difficulty_score = self._difficulty_score(analysis.difficulty)
        deadline_score = self._deadline_score(contest.d_day)
        type_fit_score = self._type_fit_score(analysis.contest_type)

        breakdown = {
            "prize": round(prize_score * self.WEIGHTS["prize"], 4),
            "difficulty": round(difficulty_score * self.WEIGHTS["difficulty"], 4),
            "deadline": round(deadline_score * self.WEIGHTS["deadline"], 4),
            "type_fit": round(type_fit_score * self.WEIGHTS["type_fit"], 4),
        }

        roi_score = round(sum(breakdown.values()), 4)
        # Clamp to [0, 10]
        roi_score = max(0.0, min(10.0, roi_score))

        logger.debug(
            "roi_calculated",
            contest_id=contest.id,
            roi_score=roi_score,
            breakdown=breakdown,
        )
        return roi_score, breakdown

    def _prize_score(self, prize_amount: int | None) -> float:
        """상금 기반 스코어 (0~10)."""
        if prize_amount is None:
            return 5.0
        if prize_amount >= 1_000_000:
            # 100만원 이상: 8~10 (선형 보간, 최대 1억으로 cap)
            capped = min(prize_amount, 100_000_000)
            return 8.0 + 2.0 * (capped - 1_000_000) / (100_000_000 - 1_000_000)
        if prize_amount >= 500_000:
            # 50~100만원: 6~8
            return 6.0 + 2.0 * (prize_amount - 500_000) / (1_000_000 - 500_000)
        if prize_amount >= 100_000:
            # 10~50만원: 3~6
            return 3.0 + 3.0 * (prize_amount - 100_000) / (500_000 - 100_000)
        # 10만원 미만: 1~3
        return 1.0 + 2.0 * (prize_amount / 100_000)

    def _difficulty_score(self, difficulty: str) -> float:
        """난이도 역수 스코어."""
        return _DIFFICULTY_SCORES.get(difficulty, 5.0)

    def _deadline_score(self, d_day: int | None) -> float:
        """마감 여유 기반 스코어."""
        if d_day is None:
            return 5.0
        for threshold, score in _DEADLINE_SCORES:
            if d_day >= threshold:
                return score
        return 1.0

    def _type_fit_score(self, contest_type: str) -> float:
        """유형 적합도 스코어."""
        return _TYPE_FIT_SCORES.get(contest_type, 5.0)
