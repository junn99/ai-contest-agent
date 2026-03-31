"""Claude CLI 기반 보고서 자동 생성기."""
import time
from datetime import datetime
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from src.core.claude_cli import ClaudeCLI
from src.generators.data_analyzer import DataAnalyzer, DataAnalysisResult
from src.generators.pdf_engine import PDFEngine
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)

# 보고서 저장 루트
_REPORTS_ROOT = Path("data/reports")


# ── 내부 Claude 응답 모델 ──────────────────────────────────────────────────────

class _ReportRequirements(BaseModel):
    report_type: str          # "analysis_report" | "idea_proposal"
    background: str
    scope: str
    data_description: str
    methodology: str
    references: list[str]


class _AnalysisPart(BaseModel):
    findings: str
    insights_and_proposals: str
    conclusion: str


class _IdeaPart(BaseModel):
    problem_statement: str
    core_idea: str
    technologies: str
    expected_impact: str
    system_design: str
    execution_plan: str
    differentiation: str
    conclusion: str


# ── ReportGenerator ────────────────────────────────────────────────────────────

class ReportGenerator:
    """Claude CLI 기반 보고서 자동 생성기"""

    def __init__(self, claude_cli: ClaudeCLI, template_dir: Path | None = None) -> None:
        self.claude = claude_cli
        self.template_dir = template_dir or Path(__file__).parent / "templates"
        self._pdf_engine = PDFEngine()
        self._data_analyzer = DataAnalyzer()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        contest: ContestInfo,
        analysis: ContestAnalysis,
        data_path: Path | None = None,
    ) -> ReportArtifact:
        """
        보고서 생성 전체 파이프라인:
        1. 요구사항 구조화 (Claude 1회)
        2. 데이터 분석 (data_path 있으면 pandas, 없으면 skip)
        3. 시각화 생성 (데이터 있으면 matplotlib)
        4. 보고서 본문 작성 (Claude 2회 — 분석파트 + 제안파트)
        5. Markdown 조합 (Jinja2 템플릿)
        6. PDF 변환 (weasyprint)
        """
        t_start = time.monotonic()
        log = logger.bind(contest_id=contest.id, title=contest.title)
        log.info("report_generation_start")

        out_dir = _REPORTS_ROOT / contest.id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1) 요구사항 구조화 (Claude 1회)
        requirements = await self._call_requirements(contest, analysis)
        log.info("requirements_structured", report_type=requirements.report_type)

        # 2) 데이터 분석
        data_result: DataAnalysisResult | None = None
        viz_paths: list[Path] = []
        if data_path is not None and data_path.exists():
            try:
                data_result = self._data_analyzer.analyze(data_path)
                viz_paths = self._data_analyzer.create_visualizations(
                    data_path, out_dir / "charts", contest.title
                )
                log.info("data_analyzed", rows=data_result.row_count, charts=len(viz_paths))
            except Exception as exc:
                log.warning("data_analysis_failed", error=str(exc))

        # 3 & 4) 본문 작성 (Claude 2회)
        report_type = requirements.report_type
        markdown_text, sections = await self._write_body(
            contest, analysis, requirements, data_result, viz_paths, report_type
        )

        # 5) Markdown 저장
        md_path = out_dir / "report.md"
        md_path.write_text(markdown_text, encoding="utf-8")

        # 6) PDF 변환
        pdf_path = out_dir / "report.pdf"
        self._pdf_engine.convert(md_path, pdf_path, contest.title, viz_paths)
        log.info("pdf_generated", path=str(pdf_path))

        duration = time.monotonic() - t_start
        word_count = len(markdown_text.replace(" ", ""))

        artifact = ReportArtifact(
            contest_id=contest.id,
            report_type=report_type,
            file_path=pdf_path,
            markdown_path=md_path,
            title=contest.title,
            sections=sections,
            data_sources=analysis.relevant_public_data,
            visualizations=viz_paths,
            word_count=word_count,
            generated_at=datetime.utcnow(),
            generation_duration_sec=round(duration, 2),
        )
        log.info("report_generation_complete", duration_sec=duration)
        return artifact

    async def improve(self, artifact: ReportArtifact, feedback: str) -> ReportArtifact:
        """사용자 피드백 반영하여 보고서 개선 (Claude 1회)"""
        t_start = time.monotonic()
        log = logger.bind(contest_id=artifact.contest_id)
        log.info("report_improvement_start")

        current_md = artifact.markdown_path.read_text(encoding="utf-8")

        prompt = (
            f"다음 보고서를 사용자 피드백을 반영하여 개선해 주세요.\n\n"
            f"## 현재 보고서\n{current_md}\n\n"
            f"## 사용자 피드백\n{feedback}\n\n"
            f"개선된 전체 보고서를 Markdown 형식으로 출력하세요. "
            f"다른 설명 없이 Markdown 본문만 출력하세요."
        )

        improved_md = await self.claude.call(prompt)

        # 저장
        artifact.markdown_path.write_text(improved_md, encoding="utf-8")

        # PDF 재생성
        self._pdf_engine.convert(
            artifact.markdown_path,
            artifact.file_path,
            artifact.title,
            list(artifact.visualizations),
        )

        duration = time.monotonic() - t_start
        word_count = len(improved_md.replace(" ", ""))

        updated = ReportArtifact(
            contest_id=artifact.contest_id,
            report_type=artifact.report_type,
            file_path=artifact.file_path,
            markdown_path=artifact.markdown_path,
            title=artifact.title,
            sections=artifact.sections,
            data_sources=artifact.data_sources,
            visualizations=artifact.visualizations,
            word_count=word_count,
            generated_at=datetime.utcnow(),
            generation_duration_sec=round(duration, 2),
        )
        log.info("report_improved", duration_sec=duration)
        return updated

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _call_requirements(
        self, contest: ContestInfo, analysis: ContestAnalysis
    ) -> _ReportRequirements:
        """Claude 1회: 보고서 유형 및 구조 결정."""
        deliverables = ", ".join(analysis.required_deliverables) or "없음"
        prompt = (
            f"다음 공모전 정보를 바탕으로 보고서 구조를 결정해 주세요.\n\n"
            f"공모전 제목: {contest.title}\n"
            f"주최: {contest.organizer}\n"
            f"유형: {analysis.contest_type}\n"
            f"설명: {contest.description or '없음'}\n"
            f"제출물: {deliverables}\n"
            f"접근 전략: {analysis.suggested_approach}\n"
            f"키워드: {', '.join(analysis.keywords)}\n"
        )
        return await self.claude.call_json(prompt, _ReportRequirements)

    async def _write_body(
        self,
        contest: ContestInfo,
        analysis: ContestAnalysis,
        req: _ReportRequirements,
        data_result: DataAnalysisResult | None,
        viz_paths: list[Path],
        report_type: str,
    ) -> tuple[str, list[str]]:
        """Claude 2회 호출 후 Jinja2로 Markdown 조합."""
        env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=False,
        )
        env.filters["number_format"] = lambda v: f"{v:,}"

        generated_date = datetime.utcnow().strftime("%Y년 %m월 %d일")
        viz_list = [
            {
                "title": p.stem.replace("_", " ").title(),
                "path": str(p.resolve()),
                "description": "",
            }
            for p in viz_paths
        ]

        if report_type != "idea_proposal":
            # 분석 보고서 경로 (기본)
            part = await self._call_analysis_part(contest, analysis, req)
            tmpl = env.get_template("analysis_report.md.j2")
            ctx = {
                "contest_title": contest.title,
                "organizer": contest.organizer,
                "generated_date": generated_date,
                "background": req.background,
                "scope": req.scope,
                "data_description": req.data_description,
                "methodology": req.methodology,
                "data_analysis": data_result,
                "visualizations": viz_list,
                "findings": part.findings,
                "insights_and_proposals": part.insights_and_proposals,
                "conclusion": part.conclusion,
                "references": req.references,
            }
            sections = ["서론", "데이터 개요", "분석 방법", "분석 결과", "인사이트 및 정책 제안", "결론"]
        else:
            # 아이디어 제안서 경로
            part = await self._call_idea_part(contest, analysis, req)
            tmpl = env.get_template("idea_proposal.md.j2")
            ctx = {
                "contest_title": contest.title,
                "organizer": contest.organizer,
                "generated_date": generated_date,
                "problem_statement": part.problem_statement,
                "core_idea": part.core_idea,
                "technologies": part.technologies,
                "expected_impact": part.expected_impact,
                "system_design": part.system_design,
                "execution_plan": part.execution_plan,
                "differentiation": part.differentiation,
                "conclusion": part.conclusion,
            }
            sections = ["문제 인식", "제안 아이디어", "구현 방안", "차별점", "결론"]

        markdown_text = tmpl.render(**ctx)
        return markdown_text, sections

    async def _call_analysis_part(
        self,
        contest: ContestInfo,
        analysis: ContestAnalysis,
        req: _ReportRequirements,
    ) -> _AnalysisPart:
        """Claude 2회차: 분석 파트 본문 작성."""
        prompt = (
            f"공모전 분석 보고서의 핵심 내용을 작성해 주세요.\n\n"
            f"공모전: {contest.title}\n"
            f"설명: {contest.description or '없음'}\n"
            f"접근 전략: {analysis.suggested_approach}\n"
            f"공공데이터: {', '.join(analysis.relevant_public_data) or '없음'}\n"
            f"배경: {req.background}\n"
            f"분석 방법: {req.methodology}\n"
        )
        return await self.claude.call_json(prompt, _AnalysisPart)

    async def _call_idea_part(
        self,
        contest: ContestInfo,
        analysis: ContestAnalysis,
        req: _ReportRequirements,
    ) -> _IdeaPart:
        """Claude 3회차: 아이디어 제안서 본문 작성."""
        prompt = (
            f"공모전 아이디어 제안서의 핵심 내용을 작성해 주세요.\n\n"
            f"공모전: {contest.title}\n"
            f"설명: {contest.description or '없음'}\n"
            f"접근 전략: {analysis.suggested_approach}\n"
            f"키워드: {', '.join(analysis.keywords)}\n"
        )
        return await self.claude.call_json(prompt, _IdeaPart)
