"""Phase 3 unit tests — analyzer, ROI scorer, pipeline."""
import asyncio
from datetime import date, datetime
from unittest.mock import MagicMock

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.analyzers.contest_analyzer import AnalysisStep1, AnalysisStep2, ContestAnalyzer
from src.analyzers.roi_scorer import ROIScorer
from src.analyzers.pipeline import AnalysisPipeline
from src.config import Settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_contest(**overrides) -> ContestInfo:
    defaults = dict(
        id="ck_202603180064",
        platform="contestkorea",
        title="AI 데이터 활용 공모전",
        url="https://example.com/contest/1",
        organizer="테스트기관",
        deadline=date(2026, 12, 31),
        start_date=date(2026, 1, 1),
        prize="상금 500만원",
        prize_amount=5_000_000,
        eligibility_raw="누구나 참여 가능",
        eligibility_tags=["누구나"],
        submission_format="PDF",
        category="데이터분석",
        description="공공데이터를 활용한 AI 솔루션 개발",
        status="접수중",
        d_day=100,
        scraped_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestInfo(**defaults)


def make_analysis(**overrides) -> ContestAnalysis:
    defaults = dict(
        contest_id="ck_202603180064",
        contest_type="데이터분석",
        difficulty="MEDIUM",
        is_eligible=True,
        eligibility_reason="누구나 참여 가능",
        roi_score=7.5,
        roi_breakdown={"prize": 3.5, "difficulty": 1.5, "deadline": 1.8, "type_fit": 1.05},
        required_deliverables=["보고서", "발표자료"],
        suggested_approach="공공데이터 API 활용",
        relevant_public_data=["국가통계포털"],
        keywords=["AI", "데이터"],
        ai_restriction="없음",
        analyzed_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestAnalysis(**defaults)


# ── AnalysisStep1 / AnalysisStep2 직렬화 ────────────────────────────────────

class TestAnalysisStepModels:
    def test_step1_round_trip(self):
        s1 = AnalysisStep1(
            contest_type="데이터분석",
            difficulty="MEDIUM",
            is_eligible_for_worker=True,
            eligibility_reason="누구나 가능",
            ai_restriction="없음",
            required_deliverables=["보고서"],
            keywords=["AI", "데이터"],
        )
        assert AnalysisStep1.model_validate_json(s1.model_dump_json()) == s1

    def test_step1_ai_restriction_none(self):
        s1 = AnalysisStep1(
            contest_type="기타",
            difficulty="LOW",
            is_eligible_for_worker=False,
            eligibility_reason="대학생 전용",
            ai_restriction=None,
            required_deliverables=[],
            keywords=[],
        )
        assert s1.ai_restriction is None

    def test_step2_round_trip(self):
        s2 = AnalysisStep2(
            suggested_approach="공공데이터를 활용하여 분석 보고서 작성",
            relevant_public_data=["국가통계포털 - kosis.kr", "공공데이터포털 - data.go.kr"],
        )
        assert AnalysisStep2.model_validate_json(s2.model_dump_json()) == s2

    def test_step2_empty_public_data(self):
        s2 = AnalysisStep2(
            suggested_approach="전략 없음",
            relevant_public_data=[],
        )
        assert s2.relevant_public_data == []


# ── ROIScorer ────────────────────────────────────────────────────────────────

class TestROIScorer:
    def setup_method(self):
        self.scorer = ROIScorer()

    # 가중치 합산 검증
    def test_weights_sum_to_one(self):
        total = sum(ROIScorer.WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    # 상금 스코어
    def test_prize_none_gives_midpoint(self):
        score = self.scorer._prize_score(None)
        assert score == 5.0

    def test_prize_over_1m(self):
        score = self.scorer._prize_score(1_000_000)
        assert 8.0 <= score <= 10.0

    def test_prize_500k_to_1m(self):
        score = self.scorer._prize_score(750_000)
        assert 6.0 <= score <= 8.0

    def test_prize_100k_to_500k(self):
        score = self.scorer._prize_score(300_000)
        assert 3.0 <= score <= 6.0

    def test_prize_under_100k(self):
        score = self.scorer._prize_score(50_000)
        assert 1.0 <= score <= 3.0

    def test_prize_zero(self):
        score = self.scorer._prize_score(0)
        assert score == 1.0

    def test_prize_very_large_capped(self):
        # 상금이 100억이어도 최대값 10 초과 안 함
        score = self.scorer._prize_score(100_000_000_000)
        assert score <= 10.0

    # 난이도 스코어
    def test_difficulty_low(self):
        assert self.scorer._difficulty_score("LOW") == 9.0

    def test_difficulty_medium(self):
        assert self.scorer._difficulty_score("MEDIUM") == 5.0

    def test_difficulty_high(self):
        assert self.scorer._difficulty_score("HIGH") == 2.0

    def test_difficulty_unknown_fallback(self):
        score = self.scorer._difficulty_score("UNKNOWN")
        assert score == 5.0

    # 마감 여유 스코어
    def test_deadline_30_days_or_more(self):
        assert self.scorer._deadline_score(30) == 9.0
        assert self.scorer._deadline_score(100) == 9.0

    def test_deadline_14_to_29_days(self):
        assert self.scorer._deadline_score(14) == 7.0
        assert self.scorer._deadline_score(29) == 7.0

    def test_deadline_7_to_13_days(self):
        assert self.scorer._deadline_score(7) == 4.0
        assert self.scorer._deadline_score(13) == 4.0

    def test_deadline_none_gives_midpoint(self):
        assert self.scorer._deadline_score(None) == 5.0

    def test_deadline_below_threshold(self):
        score = self.scorer._deadline_score(0)
        assert score == 1.0

    # 유형 적합도 스코어
    def test_type_fit_report(self):
        assert self.scorer._type_fit_score("보고서") == 9.0

    def test_type_fit_idea(self):
        assert self.scorer._type_fit_score("아이디어") == 9.0

    def test_type_fit_data_analysis(self):
        assert self.scorer._type_fit_score("데이터분석") == 7.0

    def test_type_fit_sw_dev(self):
        assert self.scorer._type_fit_score("SW개발") == 3.0

    def test_type_fit_other(self):
        assert self.scorer._type_fit_score("기타") == 5.0

    def test_type_fit_unknown_fallback(self):
        assert self.scorer._type_fit_score("영상") == 5.0

    # calculate() 반환값 구조
    def test_calculate_returns_tuple(self):
        analysis = make_analysis(contest_type="데이터분석", difficulty="LOW")
        contest = make_contest(prize_amount=5_000_000, d_day=50)
        roi_score, breakdown = self.scorer.calculate(analysis, contest)
        assert isinstance(roi_score, float)
        assert isinstance(breakdown, dict)
        assert set(breakdown.keys()) == {"prize", "difficulty", "deadline", "type_fit"}

    def test_calculate_score_in_range(self):
        analysis = make_analysis(contest_type="보고서", difficulty="LOW")
        contest = make_contest(prize_amount=10_000_000, d_day=60)
        roi_score, _ = self.scorer.calculate(analysis, contest)
        assert 0.0 <= roi_score <= 10.0

    def test_calculate_breakdown_matches_score(self):
        analysis = make_analysis(contest_type="아이디어", difficulty="MEDIUM")
        contest = make_contest(prize_amount=2_000_000, d_day=30)
        roi_score, breakdown = self.scorer.calculate(analysis, contest)
        expected = round(sum(breakdown.values()), 4)
        assert abs(roi_score - expected) < 1e-6

    def test_high_prize_high_score(self):
        analysis = make_analysis(contest_type="보고서", difficulty="LOW")
        contest = make_contest(prize_amount=50_000_000, d_day=60)
        roi_score, _ = self.scorer.calculate(analysis, contest)
        assert roi_score >= 7.0

    def test_no_prize_medium_score(self):
        analysis = make_analysis(contest_type="보고서", difficulty="LOW")
        contest = make_contest(prize_amount=None, d_day=60)
        roi_score, _ = self.scorer.calculate(analysis, contest)
        assert roi_score > 0.0


# ── ContestAnalyzer (mock Claude) ───────────────────────────────────────────

class TestContestAnalyzer:
    def _make_mock_cli(self) -> MagicMock:
        cli = MagicMock()
        step1 = AnalysisStep1(
            contest_type="데이터분석",
            difficulty="MEDIUM",
            is_eligible_for_worker=True,
            eligibility_reason="누구나 참여 가능",
            ai_restriction="없음",
            required_deliverables=["보고서", "발표자료"],
            keywords=["AI", "데이터"],
        )
        step2 = AnalysisStep2(
            suggested_approach="공공데이터 API 활용하여 분석",
            relevant_public_data=["국가통계포털 - kosis.kr"],
        )

        async def fake_call_json(prompt, model):
            if model is AnalysisStep1:
                return step1
            return step2

        cli.call_json = fake_call_json
        return cli

    def test_analyze_returns_contest_analysis(self):
        cli = self._make_mock_cli()
        analyzer = ContestAnalyzer(cli)
        contest = make_contest()
        result = asyncio.run(analyzer.analyze(contest))
        assert isinstance(result, ContestAnalysis)
        assert result.contest_id == contest.id
        assert result.contest_type == "데이터분석"
        assert result.difficulty == "MEDIUM"
        assert result.is_eligible is True
        assert result.ai_restriction == "없음"
        assert result.roi_score >= 0.0

    def test_analyze_calls_claude_twice(self):
        calls = []

        async def tracking_call_json(prompt, model):
            calls.append(model)
            if model is AnalysisStep1:
                return AnalysisStep1(
                    contest_type="보고서",
                    difficulty="LOW",
                    is_eligible_for_worker=True,
                    eligibility_reason="누구나",
                    ai_restriction=None,
                    required_deliverables=["보고서"],
                    keywords=[],
                )
            return AnalysisStep2(
                suggested_approach="전략",
                relevant_public_data=[],
            )

        cli = MagicMock()
        cli.call_json = tracking_call_json
        analyzer = ContestAnalyzer(cli)
        asyncio.run(analyzer.analyze(make_contest()))
        assert len(calls) == 2
        assert calls[0] is AnalysisStep1
        assert calls[1] is AnalysisStep2

    def test_classify_compliance_returns_ai_restriction(self):
        cli = self._make_mock_cli()
        analyzer = ContestAnalyzer(cli)
        result = asyncio.run(analyzer.classify_compliance(make_contest()))
        assert result == "없음"

    def test_classify_compliance_none_returns_불명확(self):
        async def call_json(prompt, model):
            if model is AnalysisStep1:
                return AnalysisStep1(
                    contest_type="기타",
                    difficulty="MEDIUM",
                    is_eligible_for_worker=True,
                    eligibility_reason="누구나",
                    ai_restriction=None,
                    required_deliverables=[],
                    keywords=[],
                )
            return AnalysisStep2(suggested_approach="전략", relevant_public_data=[])

        cli = MagicMock()
        cli.call_json = call_json
        analyzer = ContestAnalyzer(cli)
        result = asyncio.run(analyzer.classify_compliance(make_contest()))
        assert result == "불명확"

    def test_calculate_roi_returns_score(self):
        cli = self._make_mock_cli()
        analyzer = ContestAnalyzer(cli)
        analysis = make_analysis(roi_score=7.5)
        result = asyncio.run(analyzer.calculate_roi(analysis))
        assert result == 7.5


# ── AnalysisPipeline (mock analyzer) ────────────────────────────────────────

class TestAnalysisPipeline:
    def _make_pipeline(self, analyses: list[ContestAnalysis]) -> AnalysisPipeline:
        """파이프라인 + 목 analyzer (고정 분석 결과 반환)."""
        scorer = ROIScorer()
        settings = Settings()

        call_count = {"n": 0}

        async def fake_analyze(contest: ContestInfo) -> ContestAnalysis:
            idx = call_count["n"] % len(analyses)
            call_count["n"] += 1
            return analyses[idx]

        analyzer = MagicMock(spec=ContestAnalyzer)
        analyzer.analyze = fake_analyze
        return AnalysisPipeline(analyzer=analyzer, scorer=scorer, settings=settings)

    def test_keyword_filter_removes_irrelevant(self):
        """키워드 미해당 공모전 제거 확인"""
        contests = [
            make_contest(id="c1", title="AI 데이터 공모전", description=""),
            make_contest(id="c2", title="미술 공모전", description="그림 그리기", category="예술"),
        ]
        analysis = make_analysis(contest_id="c1", roi_score=7.0)
        pipeline = self._make_pipeline([analysis])
        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 1

    def test_deadline_filter_removes_expired(self):
        """마감 임박 공모전 제거 확인"""
        contests = [
            make_contest(id="c1", title="AI 공모전", deadline=date(2026, 12, 31), d_day=100),
            make_contest(id="c2", title="빅데이터 공모전", deadline=date(2026, 4, 1), d_day=2),
        ]
        analysis = make_analysis(contest_id="c1", roi_score=7.0)
        pipeline = self._make_pipeline([analysis])
        results = asyncio.run(pipeline.run(contests))
        # c2 는 d_day=2 < min_preparation_days(7)이므로 필터링됨
        assert len(results) == 1

    def test_eligibility_filter_removes_student_only(self):
        """대학생 전용 공모전 제거 확인"""
        contests = [
            make_contest(id="c1", title="AI 공모전", eligibility_tags=["누구나"]),
            make_contest(id="c2", title="데이터 공모전", eligibility_tags=["대학생", "대학원생"]),
        ]
        analysis = make_analysis(contest_id="c1", roi_score=6.0)
        pipeline = self._make_pipeline([analysis])
        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 1

    def test_ambiguous_eligibility_passes_to_claude(self):
        """모호한 자격(해당자) — Claude 판정 위해 통과시킴"""
        contests = [
            make_contest(id="c1", title="AI 공모전", eligibility_tags=["해당자"]),
        ]
        analysis = make_analysis(contest_id="c1", roi_score=6.0)
        pipeline = self._make_pipeline([analysis])
        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 1

    def test_no_tags_ambiguous_passes_to_claude(self):
        """태그 없음 — Claude 판정 위해 통과시킴"""
        contests = [
            make_contest(id="c1", title="AI 공모전", eligibility_tags=[]),
        ]
        analysis = make_analysis(contest_id="c1", roi_score=5.0)
        pipeline = self._make_pipeline([analysis])
        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 1

    def test_results_sorted_by_roi_descending(self):
        """ROI 내림차순 정렬 확인"""
        contests = [
            make_contest(id="c1", title="AI 공모전 A", eligibility_tags=["누구나"]),
            make_contest(id="c2", title="데이터 공모전 B", eligibility_tags=["누구나"]),
            make_contest(id="c3", title="LLM 공모전 C", eligibility_tags=["누구나"]),
        ]
        analyses = [
            make_analysis(contest_id="c1", roi_score=5.0),
            make_analysis(contest_id="c2", roi_score=8.0),
            make_analysis(contest_id="c3", roi_score=6.5),
        ]

        scorer = ROIScorer()
        settings = Settings()

        call_idx = {"n": 0}

        async def fake_analyze(contest: ContestInfo) -> ContestAnalysis:
            idx = call_idx["n"]
            call_idx["n"] += 1
            return analyses[idx]

        analyzer = MagicMock(spec=ContestAnalyzer)
        analyzer.analyze = fake_analyze
        pipeline = AnalysisPipeline(analyzer=analyzer, scorer=scorer, settings=settings)

        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 3
        scores = [r.roi_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_input_returns_empty(self):
        pipeline = self._make_pipeline([make_analysis()])
        results = asyncio.run(pipeline.run([]))
        assert results == []

    def test_analysis_error_skips_contest(self):
        """분석 중 예외 발생 시 해당 공모전 건너뜀"""
        contests = [
            make_contest(id="c1", title="AI 공모전", eligibility_tags=["누구나"]),
            make_contest(id="c2", title="데이터 공모전", eligibility_tags=["누구나"]),
        ]

        call_idx = {"n": 0}
        good_analysis = make_analysis(contest_id="c2", roi_score=7.0)

        async def fake_analyze_with_error(contest: ContestInfo) -> ContestAnalysis:
            idx = call_idx["n"]
            call_idx["n"] += 1
            if idx == 0:
                raise RuntimeError("Claude error")
            return good_analysis

        analyzer = MagicMock(spec=ContestAnalyzer)
        analyzer.analyze = fake_analyze_with_error
        pipeline = AnalysisPipeline(
            analyzer=analyzer, scorer=ROIScorer(), settings=Settings()
        )
        results = asyncio.run(pipeline.run(contests))
        assert len(results) == 1
