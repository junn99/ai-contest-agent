"""Phase 5 unit tests — SubmissionGuideGenerator, DeadlineNotifier."""
import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo
from src.models.guide import SubmissionGuide
from src.notifiers.deadline_notifier import DeadlineAlert, DeadlineNotifier
from src.notifiers.submission_guide import SubmissionGuideGenerator, _GuideResponse


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_contest(**overrides) -> ContestInfo:
    defaults = dict(
        id="ck_test_001",
        platform="contestkorea",
        title="AI 공공데이터 활용 공모전",
        url="https://example.com/contest/1",
        organizer="테스트기관",
        deadline=date(2026, 12, 31),
        start_date=date(2026, 1, 1),
        prize="상금 300만원",
        prize_amount=3_000_000,
        eligibility_raw="누구나",
        eligibility_tags=["누구나"],
        submission_format="PDF",
        category="데이터분석",
        description="공공데이터를 활용한 AI 솔루션",
        status="접수중",
        d_day=90,
        scraped_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestInfo(**defaults)


def make_artifact(tmp_path: Path, contest_id: str = "ck_test_001") -> ReportArtifact:
    pdf = tmp_path / "report.pdf"
    md = tmp_path / "report.md"
    pdf.touch()
    md.touch()
    return ReportArtifact(
        contest_id=contest_id,
        report_type="analysis_report",
        file_path=pdf,
        markdown_path=md,
        title="테스트 보고서",
        sections=["서론", "결론"],
        data_sources=["공공데이터"],
        visualizations=[],
        word_count=500,
        generated_at=datetime(2026, 3, 31),
        generation_duration_sec=5.0,
    )


def make_guide_response() -> _GuideResponse:
    return _GuideResponse(
        submission_method="온라인",
        required_documents=["보고서", "참가신청서"],
        file_format="PDF",
        max_file_size="10MB",
        additional_notes=["파일명에 팀명 포함"],
        checklist=[
            {"item": "보고서 PDF 변환 완료", "done": False},
            {"item": "참가신청서 작성", "done": False},
        ],
    )


def make_mock_cli(response: _GuideResponse | None = None) -> MagicMock:
    cli = MagicMock()
    guide_resp = response or make_guide_response()

    async def fake_call_json(prompt, model):
        return guide_resp

    cli.call_json = fake_call_json
    return cli


def make_settings() -> Settings:
    return Settings()


# ── SubmissionGuideGenerator ───────────────────────────────────────────────────

class TestSubmissionGuideGenerator:
    def test_generate_returns_submission_guide(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        contest = make_contest()
        artifacts = [make_artifact(tmp_path)]
        guide = asyncio.run(gen.generate(contest, artifacts))
        assert isinstance(guide, SubmissionGuide)

    def test_guide_contest_id_matches(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        contest = make_contest(id="ck_abc_123")
        guide = asyncio.run(gen.generate(contest, []))
        assert guide.contest_id == "ck_abc_123"

    def test_guide_contest_title_matches(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        contest = make_contest(title="환경부 공모전")
        guide = asyncio.run(gen.generate(contest, []))
        assert guide.contest_title == "환경부 공모전"

    def test_guide_submission_url_is_contest_url(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        contest = make_contest(url="https://example.com/contest/42")
        guide = asyncio.run(gen.generate(contest, []))
        assert guide.submission_url == "https://example.com/contest/42"

    def test_guide_submission_method_from_claude(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert guide.submission_method == "온라인"

    def test_guide_required_documents_from_claude(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert "보고서" in guide.required_documents
        assert "참가신청서" in guide.required_documents

    def test_guide_file_format_from_claude(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert guide.file_format == "PDF"

    def test_guide_checklist_generated(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert len(guide.checklist) == 2
        assert guide.checklist[0]["item"] == "보고서 PDF 변환 완료"
        assert guide.checklist[0]["done"] is False

    def test_guide_artifacts_contains_artifact_paths(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        artifact = make_artifact(tmp_path)
        guide = asyncio.run(gen.generate(make_contest(), [artifact]))
        assert str(artifact.file_path) in guide.artifacts

    def test_guide_days_remaining_computed(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        future = date.today() + timedelta(days=30)
        contest = make_contest(deadline=future)
        guide = asyncio.run(gen.generate(contest, []))
        assert guide.days_remaining == 30

    def test_guide_deadline_none_days_remaining_none(self, tmp_path):
        cli = make_mock_cli()
        gen = SubmissionGuideGenerator(cli)
        contest = make_contest(deadline=None)
        guide = asyncio.run(gen.generate(contest, []))
        assert guide.deadline is None
        assert guide.days_remaining is None

    def test_guide_calls_claude_once(self, tmp_path):
        call_count = {"n": 0}
        base_resp = make_guide_response()

        async def counted_call_json(prompt, model):
            call_count["n"] += 1
            return base_resp

        cli = MagicMock()
        cli.call_json = counted_call_json
        gen = SubmissionGuideGenerator(cli)
        asyncio.run(gen.generate(make_contest(), []))
        assert call_count["n"] == 1

    def test_guide_max_file_size_from_claude(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert guide.max_file_size == "10MB"

    def test_guide_additional_notes_from_claude(self, tmp_path):
        resp = make_guide_response()
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert "파일명에 팀명 포함" in guide.additional_notes

    def test_guide_null_max_file_size_allowed(self, tmp_path):
        resp = _GuideResponse(
            submission_method="이메일",
            required_documents=["보고서"],
            file_format="HWP",
            max_file_size=None,
            additional_notes=[],
            checklist=[{"item": "보고서 완성", "done": False}],
        )
        cli = make_mock_cli(resp)
        gen = SubmissionGuideGenerator(cli)
        guide = asyncio.run(gen.generate(make_contest(), []))
        assert guide.max_file_size is None


# ── DeadlineNotifier ───────────────────────────────────────────────────────────

class TestDeadlineNotifierCheckDeadlines:
    def _make_contest_with_days(self, days: int, **overrides) -> ContestInfo:
        deadline = date.today() + timedelta(days=days)
        return make_contest(deadline=deadline, **overrides)

    def test_d_minus_14_triggers_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(14)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 14

    def test_d_minus_7_triggers_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(7)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 7

    def test_d_minus_3_triggers_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(3)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 3

    def test_d_minus_1_triggers_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(1)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 1
        assert alerts[0].days_remaining == 1

    def test_d_minus_5_no_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(5)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 0

    def test_d_minus_10_no_alert(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(10)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 0

    def test_deadline_none_skipped(self):
        notifier = DeadlineNotifier(make_settings())
        contest = make_contest(deadline=None)
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 0

    def test_past_deadline_no_alert(self):
        notifier = DeadlineNotifier(make_settings())
        # 이미 지난 마감일 — days = negative
        contest = make_contest(deadline=date.today() - timedelta(days=1))
        alerts = notifier.check_deadlines([contest])
        assert len(alerts) == 0

    def test_multiple_contests_multiple_alerts(self):
        notifier = DeadlineNotifier(make_settings())
        c1 = self._make_contest_with_days(7, id="c1")
        c2 = self._make_contest_with_days(3, id="c2")
        c3 = self._make_contest_with_days(5, id="c3")  # no alert
        alerts = notifier.check_deadlines([c1, c2, c3])
        assert len(alerts) == 2
        ids = {a.contest_id for a in alerts}
        assert "c1" in ids
        assert "c2" in ids

    def test_alert_message_format(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(7, title="환경부 공모전")
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].message == "[D-7] 환경부 공모전 마감 7일 전"

    def test_alert_contest_title(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(1, title="AI 공모전", id="ai_001")
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].contest_title == "AI 공모전"

    def test_alert_deadline_date_matches(self):
        notifier = DeadlineNotifier(make_settings())
        target = date.today() + timedelta(days=14)
        contest = make_contest(deadline=target)
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].deadline == target

    def test_empty_contest_list(self):
        notifier = DeadlineNotifier(make_settings())
        alerts = notifier.check_deadlines([])
        assert alerts == []


class TestDeadlineAlertUrgency:
    def _make_contest_with_days(self, days: int) -> ContestInfo:
        return make_contest(deadline=date.today() + timedelta(days=days))

    def test_d1_urgency_critical(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(1)
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].urgency == "critical"

    def test_d3_urgency_critical(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(3)
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].urgency == "critical"

    def test_d7_urgency_warning(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(7)
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].urgency == "warning"

    def test_d14_urgency_info(self):
        notifier = DeadlineNotifier(make_settings())
        contest = self._make_contest_with_days(14)
        alerts = notifier.check_deadlines([contest])
        assert alerts[0].urgency == "info"


class TestDeadlineAlertModel:
    def test_alert_model_fields(self):
        alert = DeadlineAlert(
            contest_id="ck_001",
            contest_title="테스트",
            deadline=date(2026, 12, 31),
            days_remaining=7,
            urgency="warning",
            message="[D-7] 테스트 마감 7일 전",
        )
        assert alert.contest_id == "ck_001"
        assert alert.days_remaining == 7
        assert alert.urgency == "warning"

    def test_alert_round_trip(self):
        alert = DeadlineAlert(
            contest_id="ck_002",
            contest_title="공모전",
            deadline=date(2026, 6, 15),
            days_remaining=3,
            urgency="critical",
            message="[D-3] 공모전 마감 3일 전",
        )
        restored = DeadlineAlert.model_validate_json(alert.model_dump_json())
        assert restored.contest_id == "ck_002"
        assert restored.urgency == "critical"


class TestDeadlineNotifierFormatAlert:
    def test_format_alert_contains_message(self):
        notifier = DeadlineNotifier(make_settings())
        alert = DeadlineAlert(
            contest_id="ck_001",
            contest_title="AI 공모전",
            deadline=date(2026, 12, 31),
            days_remaining=1,
            urgency="critical",
            message="[D-1] AI 공모전 마감 1일 전",
        )
        formatted = notifier.format_alert(alert)
        assert "[D-1] AI 공모전 마감 1일 전" in formatted

    def test_format_alert_contains_deadline(self):
        notifier = DeadlineNotifier(make_settings())
        alert = DeadlineAlert(
            contest_id="ck_001",
            contest_title="테스트",
            deadline=date(2026, 12, 31),
            days_remaining=7,
            urgency="warning",
            message="[D-7] 테스트 마감 7일 전",
        )
        formatted = notifier.format_alert(alert)
        assert "2026년 12월 31일" in formatted

    def test_format_alert_contains_urgency(self):
        notifier = DeadlineNotifier(make_settings())
        alert = DeadlineAlert(
            contest_id="ck_001",
            contest_title="테스트",
            deadline=date(2026, 6, 1),
            days_remaining=14,
            urgency="info",
            message="[D-14] 테스트 마감 14일 전",
        )
        formatted = notifier.format_alert(alert)
        assert "info" in formatted
