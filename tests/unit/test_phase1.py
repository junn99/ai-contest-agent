"""Phase 1 verification tests — no DB connection required."""
import pytest

pytest.skip("archived: db/state_machine moved to archive/", allow_module_level=True)

from datetime import date, datetime

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.models.guide import SubmissionGuide
from src.models.enums import ContestState, ComplianceLevel, ContestType, Difficulty
from src.models.db import Base, ContestDB, AnalysisDB, ArtifactDB, StateTransitionDB
from src.core.state_machine import StateMachine, InvalidTransitionError
from src.collectors.filters import filter_by_keywords, filter_by_eligibility, filter_by_deadline
from src.config import Settings


# ── Helpers ─────────────────────────────────────────────────────────────────

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


# ── Pydantic Models ──────────────────────────────────────────────────────────

class TestContestInfo:
    def test_serialise_round_trip(self):
        c = make_contest()
        assert ContestInfo.model_validate_json(c.model_dump_json()) == c

    def test_optional_fields_none(self):
        c = make_contest(deadline=None, prize=None, description=None)
        assert c.deadline is None
        assert c.prize is None


class TestContestAnalysis:
    def test_basic(self):
        a = ContestAnalysis(
            contest_id="ck_202603180064",
            contest_type="데이터분석",
            difficulty="MEDIUM",
            is_eligible=True,
            eligibility_reason="누구나 참여 가능",
            roi_score=7.5,
            roi_breakdown={"prize": 4.0, "difficulty": 3.5},
            required_deliverables=["보고서", "발표자료"],
            suggested_approach="공공데이터 API 활용",
            relevant_public_data=["국가통계포털"],
            keywords=["AI", "데이터"],
            ai_restriction="없음",
            analyzed_at=datetime(2026, 3, 30),
        )
        assert a.roi_score == 7.5
        assert ContestAnalysis.model_validate_json(a.model_dump_json()) == a


class TestReportArtifact:
    def test_path_fields(self):
        from pathlib import Path
        art = ReportArtifact(
            contest_id="ck_202603180064",
            report_type="analysis_report",
            file_path=Path("/tmp/report.pdf"),
            markdown_path=Path("/tmp/report.md"),
            title="AI 데이터 분석 보고서",
            sections=["서론", "본론", "결론"],
            data_sources=["국가통계포털"],
            visualizations=[],
            word_count=3000,
            generated_at=datetime(2026, 3, 30),
            generation_duration_sec=45.2,
        )
        assert art.file_path == Path("/tmp/report.pdf")


class TestSubmissionGuide:
    def test_basic(self):
        g = SubmissionGuide(
            contest_id="ck_202603180064",
            contest_title="AI 공모전",
            deadline=date(2026, 12, 31),
            days_remaining=275,
            submission_url="https://example.com/submit",
            submission_method="온라인 접수",
            required_documents=["보고서"],
            file_format="PDF",
            max_file_size="10MB",
            additional_notes=[],
            checklist=[{"item": "보고서 작성", "done": False}],
            artifacts=["art_001"],
        )
        assert g.contest_id == "ck_202603180064"


# ── Enums ────────────────────────────────────────────────────────────────────

class TestEnums:
    def test_contest_state_values(self):
        assert ContestState.DISCOVERED == "discovered"
        assert ContestState.COMPLETED == "completed"

    def test_contest_type_korean(self):
        assert ContestType.REPORT == "보고서"
        assert ContestType.DATA_ANALYSIS == "데이터분석"

    def test_difficulty(self):
        assert Difficulty.LOW == "LOW"
        assert Difficulty.HIGH == "HIGH"

    def test_compliance_level(self):
        assert ComplianceLevel.GREEN == "green"


# ── State Machine ────────────────────────────────────────────────────────────

class TestStateMachine:
    def setup_method(self):
        self.sm = StateMachine()

    def test_valid_transition_discovered_to_filtering(self):
        result = self.sm.transition(
            ContestState.DISCOVERED, "start_filter", ContestState.FILTERING
        )
        assert result == ContestState.FILTERING

    def test_valid_chain(self):
        sm = self.sm
        cid = "ck_001"
        s = ContestState.DISCOVERED
        s = sm.transition(s, "filter", ContestState.FILTERING, contest_id=cid)
        s = sm.transition(s, "analyze", ContestState.ANALYZING, contest_id=cid)
        s = sm.transition(s, "generate", ContestState.GENERATING, contest_id=cid)
        s = sm.transition(s, "ready", ContestState.REVIEW_READY, contest_id=cid)
        s = sm.transition(s, "submit", ContestState.SUBMITTED, contest_id=cid)
        s = sm.transition(s, "track", ContestState.TRACKING, contest_id=cid)
        s = sm.transition(s, "complete", ContestState.COMPLETED, contest_id=cid)
        assert s == ContestState.COMPLETED

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransitionError):
            self.sm.transition(
                ContestState.DISCOVERED, "bad", ContestState.COMPLETED
            )

    def test_retry_max_exceeded(self):
        with pytest.raises(InvalidTransitionError):
            self.sm.transition(
                ContestState.ANALYZING, "retry", ContestState.RETRY,
                retry_count=3, contest_id="ck_002"
            )

    def test_retry_within_limit(self):
        result = self.sm.transition(
            ContestState.ANALYZING, "retry", ContestState.RETRY,
            retry_count=2, contest_id="ck_003"
        )
        assert result == ContestState.RETRY

    def test_terminal_state_detection(self):
        assert StateMachine.is_terminal(ContestState.COMPLETED)
        assert StateMachine.is_terminal(ContestState.SKIPPED)
        assert StateMachine.is_terminal(ContestState.EXPIRED)
        assert not StateMachine.is_terminal(ContestState.ANALYZING)

    def test_transition_log(self):
        self.sm.transition(
            ContestState.DISCOVERED, "filter", ContestState.FILTERING, contest_id="ck_log"
        )
        log = self.sm.get_log()
        assert len(log) == 1
        assert log[0]["from_state"] == "discovered"
        assert log[0]["to_state"] == "filtering"
        assert log[0]["contest_id"] == "ck_log"

    def test_failed_to_retry(self):
        result = self.sm.transition(
            ContestState.FAILED, "retry", ContestState.RETRY, retry_count=0
        )
        assert result == ContestState.RETRY

    def test_skipped_is_terminal_no_outgoing(self):
        allowed = StateMachine.allowed_targets(ContestState.SKIPPED)
        assert len(allowed) == 0


# ── Filters ──────────────────────────────────────────────────────────────────

class TestFilterByKeywords:
    def test_matches_ai_keyword(self):
        c = make_contest(title="AI 활용 공모전", description="")
        assert filter_by_keywords(c) is True

    def test_matches_data_in_description(self):
        c = make_contest(title="일반 공모전", description="빅데이터를 활용하세요", category="기타")
        assert filter_by_keywords(c) is True

    def test_no_match(self):
        c = make_contest(title="미술 공모전", description="그림을 그리세요", category="예술")
        assert filter_by_keywords(c) is False

    def test_matches_category(self):
        c = make_contest(title="공모전", description="", category="데이터분석")
        assert filter_by_keywords(c) is True


class TestFilterByEligibility:
    def test_eligible_tag_누구나(self):
        c = make_contest(eligibility_tags=["누구나"])
        assert filter_by_eligibility(c) is True

    def test_eligible_tag_일반인(self):
        c = make_contest(eligibility_tags=["일반인", "재직자"])
        assert filter_by_eligibility(c) is True

    def test_ineligible_student_only(self):
        c = make_contest(eligibility_tags=["대학생", "대학원생"])
        assert filter_by_eligibility(c) is False

    def test_ambiguous_no_tags(self):
        c = make_contest(eligibility_tags=[])
        assert filter_by_eligibility(c) is None

    def test_ambiguous_unknown_tag(self):
        c = make_contest(eligibility_tags=["청소년"])
        assert filter_by_eligibility(c) is None


class TestFilterByDeadline:
    def test_far_deadline_passes(self):
        c = make_contest(deadline=date(2026, 12, 31))
        assert filter_by_deadline(c, today=date(2026, 3, 30)) is True

    def test_deadline_exactly_min_days(self):
        c = make_contest(deadline=date(2026, 4, 6))
        assert filter_by_deadline(c, min_days=7, today=date(2026, 3, 30)) is True

    def test_deadline_too_close(self):
        c = make_contest(deadline=date(2026, 4, 5))
        assert filter_by_deadline(c, min_days=7, today=date(2026, 3, 30)) is False

    def test_no_deadline_passes(self):
        c = make_contest(deadline=None)
        assert filter_by_deadline(c) is True

    def test_past_deadline_fails(self):
        c = make_contest(deadline=date(2025, 1, 1))
        assert filter_by_deadline(c, today=date(2026, 3, 30)) is False


# ── Config ───────────────────────────────────────────────────────────────────

class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert "postgresql" in s.database_url
        assert s.crawl_interval_hours == 24
        assert s.min_preparation_days == 7
        assert s.roi_threshold == 3.0


# ── DB Models (structure only) ───────────────────────────────────────────────

class TestDBModels:
    def test_base_metadata_has_tables(self):
        table_names = set(Base.metadata.tables.keys())
        assert "contests" in table_names
        assert "analyses" in table_names
        assert "artifacts" in table_names
        assert "state_transitions" in table_names

    def test_contest_db_columns(self):
        cols = {c.name for c in ContestDB.__table__.columns}
        assert "id" in cols
        assert "state" in cols
        assert "retry_count" in cols
        assert "deadline" in cols
