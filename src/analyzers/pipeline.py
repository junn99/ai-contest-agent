"""Analysis pipeline: filter → Claude analysis → ROI scoring."""
import asyncio
import structlog

from src.analyzers.contest_analyzer import ContestAnalyzer
from src.analyzers.roi_scorer import ROIScorer
from src.collectors.filters import apply_all_filters
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
        """필터링 → Claude 병렬 분석 (semaphore=3) → ROI 정렬."""
        log = logger.bind(total_input=len(contests))
        log.info("pipeline_start")

        filtered = apply_all_filters(
            contests,
            min_preparation_days=self.settings.min_preparation_days,
        )
        log.info("filters_applied", remaining=len(filtered))

        async def _safe_analyze(contest: ContestInfo) -> ContestAnalysis | None:
            try:
                return await self.analyzer.analyze(contest)
            except Exception as exc:
                logger.error(
                    "analysis_failed",
                    contest_id=contest.id,
                    error=str(exc),
                    exc_info=True,
                )
                return None

        results = await asyncio.gather(*[_safe_analyze(c) for c in filtered])
        analyses = [a for a in results if a is not None]

        analyses.sort(key=lambda a: a.roi_score, reverse=True)
        log.info("pipeline_complete", analyzed=len(analyses), failed=len(filtered) - len(analyses))
        return analyses
