"""Unit tests for the digest CLI command and run --no-push integration."""
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.main import app
from src.models.artifact import ReportArtifact
from src.models.analysis import ContestAnalysis
from src.models.contest import ContestInfo


runner = CliRunner()


def make_contest(cid="ck_001", d_day=30) -> ContestInfo:
    return ContestInfo(
        id=cid,
        platform="contestkorea",
        title="테스트 공모전",
        url="https://example.com/1",
        organizer="테스트기관",
        deadline=date(2026, 12, 31),
        start_date=date(2026, 1, 1),
        prize="상금 300만원",
        prize_amount=3_000_000,
        eligibility_raw="누구나",
        eligibility_tags=["누구나"],
        submission_format="PDF",
        category="데이터분석",
        description="테스트",
        status="접수중",
        d_day=d_day,
        scraped_at=datetime(2026, 4, 20),
    )


def make_analysis(cid="ck_001") -> ContestAnalysis:
    return ContestAnalysis(
        contest_id=cid,
        contest_type="데이터분석",
        difficulty="MEDIUM",
        is_eligible=True,
        eligibility_reason="누구나",
        roi_score=7.5,
        roi_breakdown={"prize": 2.0, "difficulty": 2.0, "deadline": 2.0, "type_fit": 1.5},
        required_deliverables=["보고서"],
        suggested_approach="공공데이터 분석",
        relevant_public_data=["국가통계포털"],
        keywords=["AI"],
        ai_restriction="없음",
        analyzed_at=datetime(2026, 4, 20),
    )


def make_artifact(cid="ck_001", status="done") -> ReportArtifact:
    return ReportArtifact(
        contest_id=cid,
        report_type="analysis_report",
        file_path=Path("/tmp/report.pdf"),
        markdown_path=Path("/tmp/report.md"),
        title="테스트 보고서",
        sections=["요약"],
        data_sources=[],
        visualizations=[],
        word_count=500,
        generated_at=datetime(2026, 4, 20),
        generation_duration_sec=10.0,
        status=status,
    )


class TestDigestCommand:
    def test_digest_exits_when_no_telegram_config(self):
        with patch("src.main._get_storage") as mock_storage, \
             patch("src.config.settings") as mock_settings:
            mock_settings.telegram_bot_token = None
            mock_settings.telegram_chat_id = None
            storage = MagicMock()
            storage.load_contests.return_value = [make_contest()]
            storage.load_analyses_sorted_by_roi.return_value = [make_analysis()]
            storage.load_artifacts.return_value = []
            mock_storage.return_value = storage

            result = runner.invoke(app, ["digest"])
            assert result.exit_code != 0

    def test_digest_exits_when_no_contests(self):
        with patch("src.main._get_storage") as mock_storage, \
             patch("src.config.settings") as mock_settings:
            mock_settings.telegram_bot_token = "tok"
            mock_settings.telegram_chat_id = "123"
            mock_settings.min_preparation_days = 7
            storage = MagicMock()
            storage.load_contests.return_value = []
            mock_storage.return_value = storage

            result = runner.invoke(app, ["digest"])
            assert result.exit_code != 0

    def test_digest_calls_send_digest_with_top_n(self):
        contest = make_contest()
        analysis = make_analysis()
        artifact = make_artifact()

        with patch("src.main._get_storage") as mock_storage, \
             patch("src.config.settings") as mock_settings, \
             patch("src.notifiers.telegram.TelegramNotifier.send_digest", new_callable=AsyncMock) as mock_digest, \
             patch("src.notifiers.deadline_notifier.DeadlineNotifier.check_deadlines", return_value=[]):
            mock_settings.telegram_bot_token = "tok"
            mock_settings.telegram_chat_id = "123"
            mock_settings.min_preparation_days = 7
            storage = MagicMock()
            storage.load_contests.return_value = [contest]
            storage.load_analyses_sorted_by_roi.return_value = [analysis]
            storage.load_artifacts.return_value = [artifact]
            mock_storage.return_value = storage
            mock_digest.return_value = True

            result = runner.invoke(app, ["digest", "--top", "3"])
            assert result.exit_code == 0
            mock_digest.assert_called_once()
            call_kwargs = mock_digest.call_args.kwargs
            assert call_kwargs["top_n"] == 3

    def test_digest_passes_alert_messages(self):
        contest = make_contest(d_day=2)
        analysis = make_analysis()

        alert = MagicMock()
        alert.days_remaining = 2
        alert.contest_title = "테스트 공모전"

        with patch("src.main._get_storage") as mock_storage, \
             patch("src.config.settings") as mock_settings, \
             patch("src.notifiers.telegram.TelegramNotifier.send_digest", new_callable=AsyncMock) as mock_digest, \
             patch("src.notifiers.deadline_notifier.DeadlineNotifier.check_deadlines", return_value=[alert]):
            mock_settings.telegram_bot_token = "tok"
            mock_settings.telegram_chat_id = "123"
            mock_settings.min_preparation_days = 7
            storage = MagicMock()
            storage.load_contests.return_value = [contest]
            storage.load_analyses_sorted_by_roi.return_value = [analysis]
            storage.load_artifacts.return_value = []
            mock_storage.return_value = storage
            mock_digest.return_value = True

            result = runner.invoke(app, ["digest"])
            assert result.exit_code == 0
            call_kwargs = mock_digest.call_args.kwargs
            assert "[D-2] 테스트 공모전" in call_kwargs["alerts"]


class TestRunNoPushFlag:
    def test_run_help_includes_no_push(self):
        result = runner.invoke(app, ["run", "--help"])
        assert "--no-push" in result.output

    def test_run_no_push_sends_zero_telegram_messages(self):
        """--no-push 플래그 시 sendMessage 호출 0회 (텔레그램 푸시 전체 차단)."""
        from unittest.mock import AsyncMock, patch as _patch

        contest = make_contest()
        analysis = make_analysis()

        with _patch("src.main._get_storage") as mock_storage, \
             _patch("src.config.settings") as mock_settings, \
             _patch("src.collectors.contestkorea.ContestKoreaCollector.discover", new_callable=AsyncMock, return_value=[contest]), \
             _patch("src.collectors.wevity.WevityCollector.discover", new_callable=AsyncMock, return_value=[]), \
             _patch("src.collectors.filters.apply_all_filters", return_value=[contest]), \
             _patch("src.analyzers.pipeline.AnalysisPipeline.run", new_callable=AsyncMock, return_value=[analysis]), \
             _patch("src.generators.report_generator.ReportGenerator.generate", new_callable=AsyncMock) as mock_gen, \
             _patch("src.notifiers.deadline_notifier.DeadlineNotifier.check_deadlines", return_value=[]), \
             _patch("src.notifiers.telegram.TelegramNotifier.send", new_callable=AsyncMock) as mock_send, \
             _patch("src.notifiers.telegram.TelegramNotifier.send_digest", new_callable=AsyncMock) as mock_digest:

            mock_settings.telegram_bot_token = "tok"
            mock_settings.telegram_chat_id = "123"
            mock_settings.min_preparation_days = 7
            storage = MagicMock()
            storage.load_contests.return_value = [contest]
            storage.load_analyses.return_value = [analysis]
            storage.load_analyses_sorted_by_roi.return_value = [analysis]
            storage.load_artifacts.return_value = []
            storage.save_contests.return_value = 1
            storage.save_analysis.return_value = None
            mock_storage.return_value = storage

            artifact = make_artifact()
            mock_gen.return_value = artifact

            result = runner.invoke(app, ["run", "--no-push"])
            assert result.exit_code == 0
            mock_send.assert_not_called()
            mock_digest.assert_not_called()
