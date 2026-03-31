"""Phase 6 unit tests — JSONStorage, CLIDashboard, CLI commands."""
import json
import tempfile
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from src.core.storage import JSONStorage
from src.dashboard.cli_dashboard import CLIDashboard
from src.main import app
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_contest(**overrides) -> ContestInfo:
    defaults = dict(
        id="ck_test_001",
        platform="contestkorea",
        title="AI 공공데이터 활용 공모전",
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
        description="공공데이터를 활용한 AI 솔루션",
        status="접수중",
        d_day=90,
        scraped_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestInfo(**defaults)


def make_analysis(**overrides) -> ContestAnalysis:
    defaults = dict(
        contest_id="ck_test_001",
        contest_type="데이터분석",
        difficulty="MEDIUM",
        is_eligible=True,
        eligibility_reason="누구나 참여 가능",
        roi_score=7.5,
        roi_breakdown={"prize": 3.5, "difficulty": 1.5, "deadline": 1.8, "type_fit": 0.7},
        required_deliverables=["보고서", "발표자료"],
        suggested_approach="공공데이터 API 활용",
        relevant_public_data=["국가통계포털"],
        keywords=["AI", "데이터"],
        ai_restriction="없음",
        analyzed_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestAnalysis(**defaults)


def make_artifact(**overrides) -> ReportArtifact:
    defaults = dict(
        contest_id="ck_test_001",
        report_type="analysis_report",
        file_path=Path("data/reports/ck_test_001/report.pdf"),
        markdown_path=Path("data/reports/ck_test_001/report.md"),
        title="AI 공공데이터 활용 공모전",
        sections=["서론", "분석", "결론"],
        data_sources=["국가통계포털"],
        visualizations=[],
        word_count=5000,
        generated_at=datetime(2026, 3, 30),
        generation_duration_sec=45.0,
    )
    defaults.update(overrides)
    return ReportArtifact(**defaults)


# ── JSONStorage ────────────────────────────────────────────────────────────────

class TestJSONStorage:
    def test_save_and_load_contests(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest()
        new_count = storage.save_contests([contest])
        assert new_count == 1

        loaded = storage.load_contests()
        assert len(loaded) == 1
        assert loaded[0].id == contest.id
        assert loaded[0].title == contest.title

    def test_upsert_contests_no_duplicate(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest()
        storage.save_contests([contest])
        new_count = storage.save_contests([contest])
        assert new_count == 0  # already exists

        loaded = storage.load_contests()
        assert len(loaded) == 1

    def test_upsert_contests_updates_existing(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest()
        storage.save_contests([contest])

        updated = make_contest(title="수정된 제목")
        storage.save_contests([updated])

        loaded = storage.load_contests()
        assert len(loaded) == 1
        assert loaded[0].title == "수정된 제목"

    def test_save_multiple_contests(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        c1 = make_contest(id="ck_001", title="공모전 A")
        c2 = make_contest(id="ck_002", title="공모전 B")
        new_count = storage.save_contests([c1, c2])
        assert new_count == 2

        loaded = storage.load_contests()
        assert len(loaded) == 2

    def test_load_contests_empty(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        loaded = storage.load_contests()
        assert loaded == []

    def test_load_contests_state_filter(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        c1 = make_contest(id="ck_001", status="접수중")
        c2 = make_contest(id="ck_002", status="마감")
        storage.save_contests([c1, c2])

        active = storage.load_contests(state="접수중")
        assert len(active) == 1
        assert active[0].id == "ck_001"

        closed = storage.load_contests(state="마감")
        assert len(closed) == 1
        assert closed[0].id == "ck_002"

    def test_save_and_load_analysis(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        analysis = make_analysis()
        storage.save_analysis(analysis)

        loaded = storage.load_analyses()
        assert len(loaded) == 1
        assert loaded[0].contest_id == analysis.contest_id
        assert loaded[0].roi_score == analysis.roi_score

    def test_save_analysis_upsert(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        analysis = make_analysis(roi_score=5.0)
        storage.save_analysis(analysis)

        updated = make_analysis(roi_score=8.0)
        storage.save_analysis(updated)

        loaded = storage.load_analyses()
        assert len(loaded) == 1
        assert loaded[0].roi_score == 8.0

    def test_save_and_load_artifact(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        artifact = make_artifact()
        storage.save_artifact(artifact)

        loaded = storage.load_artifacts()
        assert len(loaded) == 1
        assert loaded[0].contest_id == artifact.contest_id
        assert loaded[0].report_type == artifact.report_type

    def test_load_artifacts_empty(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        loaded = storage.load_artifacts()
        assert loaded == []

    def test_update_state_success(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest(status="접수중")
        storage.save_contests([contest])

        result = storage.update_state("ck_test_001", "마감")
        assert result is True

        loaded = storage.load_contests()
        assert loaded[0].status == "마감"

    def test_update_state_not_found(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        result = storage.update_state("nonexistent_id", "마감")
        assert result is False

    def test_storage_creates_base_dir(self, tmp_path):
        new_dir = tmp_path / "nested" / "storage"
        storage = JSONStorage(base_dir=new_dir)
        assert new_dir.exists()

    def test_contests_file_is_valid_json(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest()
        storage.save_contests([contest])

        raw = (tmp_path / "contests.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_save_contest_with_none_fields(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        contest = make_contest(deadline=None, start_date=None, prize=None, prize_amount=None)
        new_count = storage.save_contests([contest])
        assert new_count == 1

        loaded = storage.load_contests()
        assert loaded[0].deadline is None


# ── CLIDashboard ───────────────────────────────────────────────────────────────

class TestCLIDashboard:
    def _make_console(self) -> Console:
        return Console(file=StringIO(), width=120)

    def test_show_status_renders_table(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        contests = [make_contest()]
        analyses = [make_analysis()]
        artifacts = []

        dashboard.show_status(contests, analyses, artifacts)
        text = output.getvalue()
        assert "AI 공공데이터 활용 공모전" in text

    def test_show_status_no_analysis(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        dashboard.show_status([make_contest()], [], [])
        text = output.getvalue()
        assert "ck_test_001" in text

    def test_show_status_with_artifact(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        dashboard.show_status([make_contest()], [make_analysis()], [make_artifact()])
        text = output.getvalue()
        assert "O" in text  # artifact marker

    def test_show_summary_renders_stats(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        stats = {"total": 10, "analyzed": 5, "generated": 3, "submitted": 1}
        dashboard.show_summary(stats)
        text = output.getvalue()
        assert "10" in text
        assert "5" in text
        assert "3" in text
        assert "1" in text

    def test_show_summary_missing_keys(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        # Should not raise with missing keys
        dashboard.show_summary({})
        text = output.getvalue()
        assert "0" in text

    def test_show_roi_ranking_top5(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        analyses = [
            make_analysis(contest_id=f"ck_{i:03}", roi_score=float(i))
            for i in range(1, 8)
        ]
        contests = [
            make_contest(id=f"ck_{i:03}", title=f"공모전 {i}")
            for i in range(1, 8)
        ]
        dashboard.show_roi_ranking(analyses, contests=contests)
        text = output.getvalue()
        # Top 5 should appear (roi_scores 7, 6, 5, 4, 3)
        assert "공모전 7" in text
        assert "7.0" in text

    def test_show_roi_ranking_no_contests(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        analyses = [make_analysis()]
        dashboard.show_roi_ranking(analyses)
        text = output.getvalue()
        assert "7.5" in text  # roi_score from make_analysis default

    def test_show_deadlines_critical(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        alert = MagicMock()
        alert.urgency = "critical"
        alert.message = "마감 1일 전!"
        dashboard.show_deadlines([alert])
        text = output.getvalue()
        assert "마감 1일 전!" in text

    def test_show_deadlines_warning(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)

        alert = MagicMock()
        alert.urgency = "warning"
        alert.message = "마감 3일 전"
        dashboard.show_deadlines([alert])
        text = output.getvalue()
        assert "마감 3일 전" in text

    def test_show_deadlines_empty(self):
        output = StringIO()
        console = Console(file=output, width=120)
        dashboard = CLIDashboard(console=console)
        # Should not raise
        dashboard.show_deadlines([])
        assert output.getvalue() == ""

    def test_dashboard_default_console(self):
        dashboard = CLIDashboard()
        assert dashboard.console is not None


# ── CLI commands ───────────────────────────────────────────────────────────────

runner = CliRunner()


class TestCLIStatus:
    def test_status_empty(self, tmp_path):
        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_status_with_data(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([make_contest()])
        storage.save_analysis(make_analysis())

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        # Rich wraps long titles — check for contest id and roi score instead
        assert "ck_test_001" in result.output
        assert "7.5" in result.output


class TestCLIListContests:
    def test_list_empty(self, tmp_path):
        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "없습니다" in result.output

    def test_list_with_state_filter(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([
            make_contest(id="ck_001", status="접수중"),
            make_contest(id="ck_002", status="마감"),
        ])

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["list", "--state", "접수중"])
        assert result.exit_code == 0
        assert "ck_001" in result.output


class TestCLIGuide:
    def test_guide_not_found(self, tmp_path):
        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)):
            result = runner.invoke(app, ["guide", "nonexistent"])
        assert result.exit_code == 1

    def test_guide_found(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([make_contest()])
        storage.save_analysis(make_analysis())

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["guide", "ck_test_001"])
        assert result.exit_code == 0
        assert "테스트기관" in result.output

    def test_guide_no_analysis(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([make_contest()])

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["guide", "ck_test_001"])
        assert result.exit_code == 0
        assert "AI 공공데이터 활용 공모전" in result.output


class TestCLICollect:
    def test_collect_mocked(self, tmp_path):
        mock_contests = [make_contest()]

        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)), \
             patch("src.collectors.contestkorea.ContestKoreaCollector.discover", new_callable=AsyncMock, return_value=mock_contests), \
             patch("src.collectors.wevity.WevityCollector.discover", new_callable=AsyncMock, return_value=[]):
            result = runner.invoke(app, ["collect"])
        assert result.exit_code == 0
        assert "수집" in result.output


class TestCLIAnalyze:
    def test_analyze_no_contests(self, tmp_path):
        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)):
            result = runner.invoke(app, ["analyze"])
        assert result.exit_code == 1

    def test_analyze_all_already_analyzed(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([make_contest()])
        storage.save_analysis(make_analysis())

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["analyze"])
        assert result.exit_code == 0
        assert "이미 분석" in result.output


class TestCLIGenerate:
    def test_generate_contest_not_found(self, tmp_path):
        with patch("src.main._get_storage", return_value=JSONStorage(base_dir=tmp_path)):
            result = runner.invoke(app, ["generate", "nonexistent"])
        assert result.exit_code == 1

    def test_generate_no_analysis(self, tmp_path):
        storage = JSONStorage(base_dir=tmp_path)
        storage.save_contests([make_contest()])

        with patch("src.main._get_storage", return_value=storage):
            result = runner.invoke(app, ["generate", "ck_test_001"])
        assert result.exit_code == 1
        assert "analyze" in result.output
