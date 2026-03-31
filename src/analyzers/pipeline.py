"""Analysis pipeline: filter → Claude analysis → ROI scoring."""
import structlog

from src.analyzers.contest_analyzer import ContestAnalyzer
from src.analyzers.roi_scorer import ROIScorer
from src.collectors.filters import (
    filter_by_deadline,
    filter_by_eligibility,
    filter_by_keywords,
)
from src.config import Settings
from src.models.analysis import ContestAnalysis
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


class AnalysisPipeline:
    """수집된 공모전 → 필터링 → Claude 분석 → ROI 스코어링 전체 파이프라인"""

    def __init__(
        self,
        analyzer: ContestAnalyzer,
        scorer: ROIScorer,
        settings: Settings,
    ) -> None:
        self.analyzer = analyzer
        self.scorer = scorer
        self.settings = settings

    async def run(self, contests: list[ContestInfo]) -> list[ContestAnalysis]:
        """
        1. 키워드 필터 적용
        2. 마감일 필터 적용
        3. 자격 필터 적용 (모호한 경우 Claude가 analyze에서 판정)
        4. 통과한 공모전에 대해 Claude 분석 실행
        5. ROI 스코어 계산
        6. ROI 기준 정렬
        7. 결과 반환
        """
        log = logger.bind(total_input=len(contests))
        log.info("pipeline_start")

        # 1. 키워드 필터
        after_keyword = [c for c in contests if filter_by_keywords(c)]
        log.info("keyword_filter_done", remaining=len(after_keyword))

        # 2. 마감일 필터
        after_deadline = [
            c
            for c in after_keyword
            if filter_by_deadline(c, min_days=self.settings.min_preparation_days)
        ]
        log.info("deadline_filter_done", remaining=len(after_deadline))

        # 3. 자격 필터 (False 이면 제외, True 또는 None 이면 통과시켜 Claude 판정)
        after_eligibility: list[ContestInfo] = []
        for c in after_deadline:
            result = filter_by_eligibility(c)
            if result is False:
                log.debug("eligibility_excluded", contest_id=c.id)
            else:
                after_eligibility.append(c)
        log.info("eligibility_filter_done", remaining=len(after_eligibility))

        # 4 & 5. Claude 분석 + ROI 계산 (sequential to respect semaphore)
        analyses: list[ContestAnalysis] = []
        for contest in after_eligibility:
            try:
                analysis = await self.analyzer.analyze(contest)
                analyses.append(analysis)
            except Exception as exc:
                logger.error(
                    "analysis_failed",
                    contest_id=contest.id,
                    error=str(exc),
                )

        # 6. ROI 기준 내림차순 정렬
        analyses.sort(key=lambda a: a.roi_score, reverse=True)
        log.info("pipeline_complete", analyzed=len(analyses))
        return analyses
