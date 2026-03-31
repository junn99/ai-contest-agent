"""Phase 4 unit tests — DataAnalyzer, PDFEngine, ReportGenerator, templates."""
import asyncio
import csv
import io
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.generators.data_analyzer import DataAnalyzer, DataAnalysisResult
from src.generators.pdf_engine import PDFEngine
from src.generators.report_generator import (
    ReportGenerator,
    _AnalysisPart,
    _IdeaPart,
    _ReportRequirements,
)
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
        roi_score=7.0,
        roi_breakdown={"prize": 2.0, "difficulty": 2.0, "deadline": 2.0, "type_fit": 1.0},
        required_deliverables=["보고서", "발표자료"],
        suggested_approach="공공데이터 분석",
        relevant_public_data=["국가통계포털"],
        keywords=["AI", "데이터"],
        ai_restriction="없음",
        analyzed_at=datetime(2026, 3, 30),
    )
    defaults.update(overrides)
    return ContestAnalysis(**defaults)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _write_csv_euckr(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="euc-kr") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


# ── DataAnalyzer ───────────────────────────────────────────────────────────────

class TestDataAnalyzerLoad:
    def test_load_utf8_csv(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [{"이름": "홍길동", "점수": 90}, {"이름": "김철수", "점수": 85}])
        analyzer = DataAnalyzer()
        result = analyzer.analyze(csv_path)
        assert result.row_count == 2
        assert result.column_count == 2

    def test_load_euckr_csv(self, tmp_path):
        csv_path = tmp_path / "data_euckr.csv"
        _write_csv_euckr(csv_path, [{"이름": "홍길동", "나이": 30}, {"이름": "이영희", "나이": 25}])
        analyzer = DataAnalyzer()
        result = analyzer.analyze(csv_path)
        assert result.row_count == 2

    def test_invalid_encoding_raises(self, tmp_path):
        bad_path = tmp_path / "bad.csv"
        bad_path.write_bytes(b"\xff\xfe\x00bad data\x00")
        analyzer = DataAnalyzer()
        with pytest.raises(Exception):
            analyzer.analyze(bad_path)


class TestDataAnalyzerStats:
    def _make_csv(self, tmp_path) -> Path:
        p = tmp_path / "stats.csv"
        rows = [
            {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5},
            {"a": 2, "b": 3, "c": 4, "d": 5, "e": 6},
            {"a": 3, "b": 4, "c": 5, "d": 6, "e": 7},
        ]
        _write_csv(p, rows)
        return p

    def test_summary_stats_not_empty(self, tmp_path):
        p = self._make_csv(tmp_path)
        result = DataAnalyzer().analyze(p)
        assert isinstance(result.summary_stats, dict)
        assert len(result.summary_stats) > 0

    def test_correlations_computed_for_numeric(self, tmp_path):
        p = self._make_csv(tmp_path)
        result = DataAnalyzer().analyze(p)
        assert result.correlations is not None

    def test_correlations_none_for_single_numeric(self, tmp_path):
        p = tmp_path / "single.csv"
        _write_csv(p, [{"x": 1, "name": "a"}, {"x": 2, "name": "b"}])
        result = DataAnalyzer().analyze(p)
        # 수치형 1개 → 상관관계 없음
        assert result.correlations is None

    def test_columns_metadata(self, tmp_path):
        p = tmp_path / "meta.csv"
        _write_csv(p, [{"col1": 1, "col2": "hello"}, {"col1": 2, "col2": "world"}])
        result = DataAnalyzer().analyze(p)
        names = [c["name"] for c in result.columns]
        assert "col1" in names
        assert "col2" in names
        for c in result.columns:
            assert "dtype" in c
            assert "missing_pct" in c

    def test_result_model_valid(self, tmp_path):
        p = tmp_path / "valid.csv"
        _write_csv(p, [{"x": 1}, {"x": 2}])
        result = DataAnalyzer().analyze(p)
        assert isinstance(result, DataAnalysisResult)


class TestDataAnalyzerInsights:
    def test_missing_pct_insight(self, tmp_path):
        p = tmp_path / "missing.csv"
        rows = [{"x": i if i % 3 != 0 else None, "y": i} for i in range(10)]
        _write_csv(p, rows)
        result = DataAnalyzer().analyze(p)
        # 결측치 30% 이상인 컬럼에 대한 인사이트 확인
        high_missing = [c for c in result.columns if c["missing_pct"] >= 0.3]
        if high_missing:
            assert len(result.insights) > 0

    def test_empty_dataframe_insight(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("col1,col2\n", encoding="utf-8")
        result = DataAnalyzer().analyze(p)
        assert result.row_count == 0
        assert any("비어" in i for i in result.insights)


class TestDataAnalyzerVisualizations:
    def _make_numeric_csv(self, tmp_path, n_cols=3) -> Path:
        p = tmp_path / "viz.csv"
        cols = {f"col{i}": list(range(1, 6)) for i in range(n_cols)}
        rows = [dict(zip(cols.keys(), vals)) for vals in zip(*cols.values())]
        _write_csv(p, rows)
        return p

    def test_creates_bar_chart(self, tmp_path):
        p = self._make_numeric_csv(tmp_path)
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "테스트 공모전")
        assert any("bar" in x.name for x in paths)
        assert all(x.exists() for x in paths)

    def test_creates_heatmap_for_5plus_cols(self, tmp_path):
        p = self._make_numeric_csv(tmp_path, n_cols=6)
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "히트맵 테스트")
        assert any("heatmap" in x.name for x in paths)

    def test_no_heatmap_for_fewer_than_5_cols(self, tmp_path):
        p = self._make_numeric_csv(tmp_path, n_cols=3)
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "히트맵 없음")
        assert not any(x.name == "heatmap.png" for x in paths)

    def test_creates_pie_for_categorical(self, tmp_path):
        p = tmp_path / "cat.csv"
        rows = [{"cat": c, "val": i} for i, c in enumerate(["A", "B", "C", "A", "B"])]
        _write_csv(p, rows)
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "파이 테스트")
        assert any("pie" in x.name for x in paths)

    def test_empty_data_returns_empty_list(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("col1,col2\n", encoding="utf-8")
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "빈 데이터")
        assert paths == []

    def test_max_4_charts(self, tmp_path):
        p = tmp_path / "many.csv"
        # date col + 6 numeric + 1 cat => all chart types triggered
        rows = [
            {"date": f"2026-0{i+1}-01", **{f"n{j}": i * j for j in range(6)}, "cat": f"C{i % 3}"}
            for i in range(5)
        ]
        _write_csv(p, rows)
        out = tmp_path / "charts"
        paths = DataAnalyzer().create_visualizations(p, out, "최대 차트")
        assert len(paths) <= 4


# ── PDFEngine ──────────────────────────────────────────────────────────────────

class TestPDFEngine:
    def _make_md(self, tmp_path, content: str = "# 테스트\n\n본문입니다.") -> Path:
        p = tmp_path / "report.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_convert_produces_pdf(self, tmp_path):
        md = self._make_md(tmp_path)
        out = tmp_path / "out.pdf"
        engine = PDFEngine()
        result = engine.convert(md, out, "테스트 보고서")
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_convert_creates_html_intermediate(self, tmp_path):
        md = self._make_md(tmp_path)
        out = tmp_path / "out.pdf"
        PDFEngine().convert(md, out, "HTML 중간 파일")
        html_path = out.with_suffix(".html")
        assert html_path.exists()

    def test_korean_content_renders(self, tmp_path):
        md = self._make_md(
            tmp_path,
            "# 한글 제목\n\n한글 본문: 공모전 분석 보고서입니다.\n\n"
            "## 소제목\n\n- 항목 1\n- 항목 2\n",
        )
        out = tmp_path / "korean.pdf"
        PDFEngine().convert(md, out, "한글 보고서")
        assert out.exists()
        assert out.stat().st_size > 100

    def test_image_insertion(self, tmp_path):
        # 1x1 투명 PNG
        png = tmp_path / "chart.png"
        import struct, zlib
        def make_png():
            def chunk(name, data):
                c = struct.pack(">I", len(data)) + name + data
                return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
            ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            idat = zlib.compress(b"\x00\xff\xff\xff")
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
        png.write_bytes(make_png())
        md = self._make_md(tmp_path, "# 이미지 테스트\n")
        out = tmp_path / "with_image.pdf"
        PDFEngine().convert(md, out, "이미지 포함", images=[png])
        assert out.exists()

    def test_css_contains_korean_font(self):
        css = PDFEngine()._get_css()
        assert "WenQuanYi Zen Hei" in css

    def test_css_contains_page_settings(self):
        css = PDFEngine()._get_css()
        assert "A4" in css
        assert "counter(page)" in css

    def test_output_dir_created_automatically(self, tmp_path):
        md = self._make_md(tmp_path)
        nested = tmp_path / "deep" / "nested" / "out.pdf"
        PDFEngine().convert(md, nested, "중첩 디렉토리")
        assert nested.exists()

    def test_table_markdown_renders(self, tmp_path):
        md = self._make_md(
            tmp_path,
            "# 테이블\n\n| 항목 | 값 |\n|------|----|\n| A | 1 |\n| B | 2 |\n",
        )
        out = tmp_path / "table.pdf"
        PDFEngine().convert(md, out, "테이블 테스트")
        assert out.exists()


# ── Jinja2 템플릿 렌더링 ────────────────────────────────────────────────────────

class TestTemplates:
    def _env(self):
        from jinja2 import Environment, FileSystemLoader
        template_dir = Path(__file__).parent.parent.parent / "src" / "generators" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
        env.filters["number_format"] = lambda v: f"{v:,}"
        return env

    def test_analysis_report_renders_without_data(self):
        env = self._env()
        tmpl = env.get_template("analysis_report.md.j2")
        result = tmpl.render(
            contest_title="테스트 공모전",
            organizer="테스트기관",
            generated_date="2026년 03월 31일",
            background="배경 내용",
            scope="분석 범위",
            data_description="",
            methodology="분석 방법론",
            data_analysis=None,
            visualizations=[],
            findings="발견사항",
            insights_and_proposals="제안사항",
            conclusion="결론",
            references=["참고1", "참고2"],
        )
        assert "테스트 공모전" in result
        assert "공개된 통계 자료" in result
        assert "참고1" in result

    def test_analysis_report_renders_with_data(self):
        env = self._env()
        tmpl = env.get_template("analysis_report.md.j2")

        class FakeDataResult:
            row_count = 100
            column_count = 5
            columns = [{"name": "col1"}, {"name": "col2"}]
            insights = ["결측치 30% 이상입니다."]

        result = tmpl.render(
            contest_title="데이터 공모전",
            organizer="주최기관",
            generated_date="2026년 03월 31일",
            background="배경",
            scope="범위",
            data_description="데이터 설명",
            methodology="방법",
            data_analysis=FakeDataResult(),
            visualizations=[{"title": "Bar Chart", "path": "/tmp/bar.png", "description": ""}],
            findings="발견",
            insights_and_proposals="제안",
            conclusion="결론",
            references=[],
        )
        assert "100" in result
        assert "결측치" in result
        assert "Bar Chart" in result

    def test_idea_proposal_renders(self):
        env = self._env()
        tmpl = env.get_template("idea_proposal.md.j2")
        result = tmpl.render(
            contest_title="아이디어 공모전",
            organizer="주최",
            generated_date="2026년 03월 31일",
            problem_statement="문제 정의",
            core_idea="핵심 아이디어",
            technologies="Python, AI",
            expected_impact="기대 효과",
            system_design="시스템 설계",
            execution_plan="실행 계획",
            differentiation="차별점",
            conclusion="결론",
        )
        assert "아이디어 공모전" in result
        assert "핵심 아이디어" in result
        assert "차별점" in result

    def test_number_format_filter(self):
        env = self._env()
        tmpl = env.get_template("analysis_report.md.j2")

        class D:
            row_count = 1000
            column_count = 3
            columns = [{"name": "x"}]
            insights = []

        result = tmpl.render(
            contest_title="숫자 포맷 테스트",
            organizer="기관",
            generated_date="2026년 03월 31일",
            background="", scope="", data_description="",
            methodology="", data_analysis=D(), visualizations=[],
            findings="", insights_and_proposals="", conclusion="",
            references=[],
        )
        assert "1,000" in result


# ── ReportGenerator (mock Claude) ─────────────────────────────────────────────

def _make_mock_cli(report_type: str = "analysis_report") -> MagicMock:
    """Claude 응답을 고정 반환하는 mock CLI."""
    cli = MagicMock()

    requirements = _ReportRequirements(
        report_type=report_type,
        background="배경 내용",
        scope="전국 단위 분석",
        data_description="공공 통계 데이터",
        methodology="정량 분석",
        references=["참고자료 1", "참고자료 2"],
    )
    analysis_part = _AnalysisPart(
        findings="주요 발견사항입니다.",
        insights_and_proposals="정책 제안사항입니다.",
        conclusion="결론입니다.",
    )
    idea_part = _IdeaPart(
        problem_statement="문제 정의",
        core_idea="핵심 아이디어",
        technologies="Python, TensorFlow",
        expected_impact="사회적 효과",
        system_design="마이크로서비스 아키텍처",
        execution_plan="단계별 계획",
        differentiation="독창성",
        conclusion="마무리",
    )

    async def fake_call_json(prompt, model):
        if model is _ReportRequirements:
            return requirements
        if model is _AnalysisPart:
            return analysis_part
        if model is _IdeaPart:
            return idea_part
        raise ValueError(f"Unknown model: {model}")

    async def fake_call(prompt):
        return "# 개선된 보고서\n\n개선된 내용입니다."

    cli.call_json = fake_call_json
    cli.call = fake_call
    return cli


class TestReportGeneratorWithoutData:
    def test_generate_returns_artifact(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        contest = make_contest()
        analysis = make_analysis()
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(contest, analysis))
        assert isinstance(artifact, ReportArtifact)
        assert artifact.contest_id == contest.id
        assert artifact.file_path.exists()
        assert artifact.markdown_path.exists()

    def test_generate_pdf_created(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert artifact.file_path.suffix == ".pdf"
        assert artifact.file_path.stat().st_size > 0

    def test_generate_word_count_positive(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert artifact.word_count > 0

    def test_generate_sections_not_empty(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert len(artifact.sections) > 0

    def test_generate_no_visualizations_without_data(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert artifact.visualizations == []

    def test_generate_calls_claude_twice(self, tmp_path):
        """analysis_report path: requirements (1) + analysis_part (1) = 2 call_json calls."""
        call_log = []

        async def tracked_call_json(prompt, model):
            call_log.append(model)
            return await _make_mock_cli().call_json(prompt, model)

        cli = MagicMock()
        cli.call_json = tracked_call_json
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert len(call_log) == 2
        assert call_log[0] is _ReportRequirements
        assert call_log[1] is _AnalysisPart

    def test_generate_idea_proposal(self, tmp_path):
        cli = _make_mock_cli(report_type="idea_proposal")
        gen = ReportGenerator(cli)
        analysis = make_analysis(contest_type="아이디어")
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), analysis))
        assert artifact.report_type == "idea_proposal"

    def test_generate_duration_recorded(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis()))
        assert artifact.generation_duration_sec >= 0.0


class TestReportGeneratorWithData:
    def _make_data_csv(self, tmp_path) -> Path:
        p = tmp_path / "data.csv"
        rows = [
            {"지역": "서울", "수치1": 100, "수치2": 200, "수치3": 50, "카테고리": "A"},
            {"지역": "부산", "수치1": 80,  "수치2": 150, "수치3": 60, "카테고리": "B"},
            {"지역": "대구", "수치1": 70,  "수치2": 130, "수치3": 40, "카테고리": "A"},
        ]
        _write_csv(p, rows)
        return p

    def test_generate_with_data_has_visualizations(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        data_csv = self._make_data_csv(tmp_path)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis(), data_path=data_csv))
        assert len(artifact.visualizations) > 0

    def test_generate_with_data_word_count_positive(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        data_csv = self._make_data_csv(tmp_path)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(gen.generate(make_contest(), make_analysis(), data_path=data_csv))
        assert artifact.word_count > 0

    def test_generate_missing_data_path_skips_analysis(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            artifact = asyncio.run(
                gen.generate(make_contest(), make_analysis(), data_path=Path("/nonexistent/data.csv"))
            )
        assert artifact.visualizations == []


class TestReportGeneratorImprove:
    def test_improve_returns_artifact(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            original = asyncio.run(gen.generate(make_contest(), make_analysis()))
            improved = asyncio.run(gen.improve(original, "결론을 더 자세히 써주세요."))
        assert isinstance(improved, ReportArtifact)

    def test_improve_updates_word_count(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            original = asyncio.run(gen.generate(make_contest(), make_analysis()))
            improved = asyncio.run(gen.improve(original, "더 자세하게"))
        assert improved.word_count > 0

    def test_improve_pdf_regenerated(self, tmp_path):
        cli = _make_mock_cli()
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            original = asyncio.run(gen.generate(make_contest(), make_analysis()))
            mtime_before = original.file_path.stat().st_mtime
            import time; time.sleep(0.05)
            improved = asyncio.run(gen.improve(original, "개선 요청"))
        assert improved.file_path.stat().st_mtime >= mtime_before

    def test_improve_calls_claude_call_once(self, tmp_path):
        call_count = {"n": 0}
        base_cli = _make_mock_cli()

        async def tracked_call(prompt):
            call_count["n"] += 1
            return await base_cli.call(prompt)

        cli = MagicMock()
        cli.call_json = base_cli.call_json
        cli.call = tracked_call
        gen = ReportGenerator(cli)
        with patch("src.generators.report_generator._REPORTS_ROOT", tmp_path):
            original = asyncio.run(gen.generate(make_contest(), make_analysis()))
            asyncio.run(gen.improve(original, "피드백"))
        assert call_count["n"] == 1


# ── ReportArtifact 모델 검증 ────────────────────────────────────────────────────

class TestReportArtifactModel:
    def test_round_trip(self, tmp_path):
        p = tmp_path / "r.pdf"
        m = tmp_path / "r.md"
        p.touch()
        m.touch()
        artifact = ReportArtifact(
            contest_id="c1",
            report_type="analysis_report",
            file_path=p,
            markdown_path=m,
            title="테스트",
            sections=["서론", "결론"],
            data_sources=["공공데이터"],
            visualizations=[],
            word_count=500,
            generated_at=datetime(2026, 3, 31),
            generation_duration_sec=12.5,
        )
        restored = ReportArtifact.model_validate_json(artifact.model_dump_json())
        assert restored.contest_id == "c1"
        assert restored.word_count == 500
        assert restored.generation_duration_sec == 12.5

    def test_required_fields_present(self, tmp_path):
        p = tmp_path / "f.pdf"
        m = tmp_path / "f.md"
        p.touch(); m.touch()
        artifact = ReportArtifact(
            contest_id="x",
            report_type="idea_proposal",
            file_path=p,
            markdown_path=m,
            title="제목",
            sections=[],
            data_sources=[],
            visualizations=[],
            word_count=0,
            generated_at=datetime.utcnow(),
            generation_duration_sec=0.0,
        )
        assert artifact.report_type == "idea_proposal"
