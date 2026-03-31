"""Claude CLI-based contest analyzer."""
from datetime import datetime

import structlog
from pydantic import BaseModel

from src.core.claude_cli import ClaudeCLI
from src.models.analysis import ContestAnalysis
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


class AnalysisStep1(BaseModel):
    contest_type: str
    difficulty: str
    is_eligible_for_worker: bool
    eligibility_reason: str
    ai_restriction: str | None
    required_deliverables: list[str]
    keywords: list[str]


class AnalysisStep2(BaseModel):
    suggested_approach: str
    relevant_public_data: list[str]


class ContestAnalyzer:
    """Claude CLI 기반 공모전 분석기"""

    def __init__(self, claude_cli: ClaudeCLI) -> None:
        self.claude = claude_cli

    async def analyze(self, contest: ContestInfo) -> ContestAnalysis:
        """공모전 종합 분석 — Claude 호출 최대 2회로 통합"""
        log = logger.bind(contest_id=contest.id, title=contest.title)
        log.info("analyzing_contest")

        # 1회차: 유형 분류 + 난이도 + 참가자격 정밀 판정 + AI 제한 확인
        prompt1 = (
            f"다음 공모전을 분석하세요.\n\n"
            f"제목: {contest.title}\n"
            f"설명: {contest.description or '없음'}\n"
            f"참가자격: {contest.eligibility_raw}\n"
            f"제출형식: {contest.submission_format or '없음'}\n"
            f"주최: {contest.organizer}\n\n"
            f"다음 JSON으로 응답하세요:\n"
            f'{{\n'
            f'  "contest_type": "보고서|아이디어|SW개발|데이터분석|기타",\n'
            f'  "difficulty": "LOW|MEDIUM|HIGH",\n'
            f'  "is_eligible_for_worker": true/false,\n'
            f'  "eligibility_reason": "판단 근거",\n'
            f'  "ai_restriction": "없음|AI 활용 금지|AI 활용 권장|불명확",\n'
            f'  "required_deliverables": ["보고서", "발표자료", ...],\n'
            f'  "keywords": ["AI", "데이터", ...]\n'
            f'}}'
        )

        step1 = await self.claude.call_json(prompt1, AnalysisStep1)
        log.info("step1_complete", contest_type=step1.contest_type, difficulty=step1.difficulty)

        # 2회차: 접근 전략 + 공공데이터 추천
        prompt2 = (
            f"다음 공모전에 참가하려 합니다.\n\n"
            f"제목: {contest.title}\n"
            f"유형: {step1.contest_type}\n"
            f"설명: {contest.description or '없음'}\n\n"
            f"1. 입상을 위한 접근 전략을 200자 이내로 제안하세요.\n"
            f"2. 활용 가능한 공공데이터(data.go.kr)를 3개 이내로 추천하세요.\n\n"
            f"JSON으로 응답:\n"
            f'{{\n'
            f'  "suggested_approach": "...",\n'
            f'  "relevant_public_data": ["데이터셋 이름 - URL 또는 설명", ...]\n'
            f'}}'
        )

        step2 = await self.claude.call_json(prompt2, AnalysisStep2)
        log.info("step2_complete", approach_length=len(step2.suggested_approach))

        # ROI 스코어 계산
        from src.analyzers.roi_scorer import ROIScorer

        scorer = ROIScorer()
        # Assemble partial analysis to compute ROI
        partial = ContestAnalysis(
            contest_id=contest.id,
            contest_type=step1.contest_type,
            difficulty=step1.difficulty,
            is_eligible=step1.is_eligible_for_worker,
            eligibility_reason=step1.eligibility_reason,
            roi_score=0.0,
            roi_breakdown={},
            required_deliverables=step1.required_deliverables,
            suggested_approach=step2.suggested_approach,
            relevant_public_data=step2.relevant_public_data,
            keywords=step1.keywords,
            ai_restriction=step1.ai_restriction,
            analyzed_at=datetime.utcnow(),
        )
        roi_score, roi_breakdown = scorer.calculate(partial, contest)

        analysis = ContestAnalysis(
            contest_id=contest.id,
            contest_type=step1.contest_type,
            difficulty=step1.difficulty,
            is_eligible=step1.is_eligible_for_worker,
            eligibility_reason=step1.eligibility_reason,
            roi_score=roi_score,
            roi_breakdown=roi_breakdown,
            required_deliverables=step1.required_deliverables,
            suggested_approach=step2.suggested_approach,
            relevant_public_data=step2.relevant_public_data,
            keywords=step1.keywords,
            ai_restriction=step1.ai_restriction,
            analyzed_at=datetime.utcnow(),
        )
        log.info("analysis_complete", roi_score=roi_score)
        return analysis

    async def classify_compliance(self, contest: ContestInfo) -> str:
        """AI 활용 규정 확인 — analyze() 결과의 ai_restriction 필드 활용"""
        analysis = await self.analyze(contest)
        return analysis.ai_restriction or "불명확"

    async def calculate_roi(self, analysis: ContestAnalysis) -> float:
        """ROI 스코어 반환 (Claude 호출 없음, 순수 계산)"""
        return analysis.roi_score
