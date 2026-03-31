"""CLI 엔트리포인트 — uv run python -m src.main <command>"""
import asyncio
from pathlib import Path

import structlog
import typer
from rich.console import Console

from src.core.storage import JSONStorage
from src.dashboard.cli_dashboard import CLIDashboard

app = typer.Typer(name="sweep", help="공공 AI 공모전 싹쓸이 시스템", add_completion=False)
console = Console()
logger = structlog.get_logger(__name__)


def _get_storage() -> JSONStorage:
    return JSONStorage(base_dir=Path("data"))


@app.command()
def collect() -> None:
    """콘테스트코리아 + 위비티에서 공모전 수집"""
    from src.collectors.contestkorea import ContestKoreaCollector
    from src.collectors.wevity import WevityCollector
    from src.collectors.filters import filter_by_keywords, filter_by_deadline, filter_by_eligibility
    from src.config import settings

    async def _run() -> None:
        console.print("[bold]공모전 수집 시작...[/bold]")

        ck_collector = ContestKoreaCollector()
        wv_collector = WevityCollector()

        ck_contests = await ck_collector.discover()
        console.print(f"콘테스트코리아: {len(ck_contests)}건 수집")

        wv_contests = await wv_collector.discover()
        console.print(f"위비티: {len(wv_contests)}건 수집")

        all_contests = ck_contests + wv_contests
        console.print(f"총 수집: {len(all_contests)}건")

        # 필터링
        after_keyword = [c for c in all_contests if filter_by_keywords(c)]
        after_deadline = [
            c for c in after_keyword
            if filter_by_deadline(c, min_days=settings.min_preparation_days)
        ]
        filtered = []
        for c in after_deadline:
            if filter_by_eligibility(c) is not False:
                filtered.append(c)

        console.print(f"필터링 후: {len(filtered)}건")

        storage = _get_storage()
        new_count = storage.save_contests(filtered)
        console.print(f"[green]저장 완료: 신규 {new_count}건[/green]")

    asyncio.run(_run())


@app.command()
def analyze() -> None:
    """수집된 공모전 Claude 분석 + ROI 스코어링"""
    from src.analyzers.contest_analyzer import ContestAnalyzer
    from src.analyzers.roi_scorer import ROIScorer
    from src.analyzers.pipeline import AnalysisPipeline
    from src.core.claude_cli import ClaudeCLI
    from src.config import settings

    async def _run() -> None:
        storage = _get_storage()
        contests = storage.load_contests()

        if not contests:
            console.print("[yellow]분석할 공모전이 없습니다. 먼저 collect를 실행하세요.[/yellow]")
            raise typer.Exit(1)

        # 이미 분석된 ID 제외
        existing_analyses = storage.load_analyses()
        analyzed_ids = {a.contest_id for a in existing_analyses}
        unanalyzed = [c for c in contests if c.id not in analyzed_ids]

        if not unanalyzed:
            console.print("[yellow]모든 공모전이 이미 분석되었습니다.[/yellow]")
            raise typer.Exit(0)

        console.print(f"[bold]분석 시작: {len(unanalyzed)}건[/bold]")

        claude = ClaudeCLI()
        analyzer = ContestAnalyzer(claude_cli=claude, settings=settings)
        scorer = ROIScorer(settings=settings)
        pipeline = AnalysisPipeline(analyzer=analyzer, scorer=scorer, settings=settings)

        analyses = await pipeline.run(unanalyzed)

        for analysis in analyses:
            storage.save_analysis(analysis)

        console.print(f"[green]분석 완료: {len(analyses)}건[/green]")

        # ROI 상위 5개 출력
        dashboard = CLIDashboard(console=console)
        all_contests = storage.load_contests()
        dashboard.show_roi_ranking(analyses, contests=all_contests)

    asyncio.run(_run())


@app.command()
def generate(
    contest_id: str = typer.Argument(..., help="공모전 ID (예: ck_202603180064)"),
    data_path: str | None = typer.Option(None, "--data", help="분석 데이터 CSV/Excel 경로"),
) -> None:
    """특정 공모전에 대한 보고서 자동 생성"""
    from src.generators.report_generator import ReportGenerator
    from src.core.claude_cli import ClaudeCLI

    async def _run() -> None:
        storage = _get_storage()
        contests = storage.load_contests()
        contest = next((c for c in contests if c.id == contest_id), None)
        if not contest:
            console.print(f"[red]공모전 '{contest_id}'을 찾을 수 없습니다.[/red]")
            raise typer.Exit(1)

        analyses = storage.load_analyses()
        analysis = next((a for a in analyses if a.contest_id == contest_id), None)
        if not analysis:
            console.print(f"[red]공모전 '{contest_id}'의 분석 결과가 없습니다. 먼저 analyze를 실행하세요.[/red]")
            raise typer.Exit(1)

        data_file: Path | None = Path(data_path) if data_path else None

        console.print(f"[bold]보고서 생성 중: {contest.title}[/bold]")
        claude = ClaudeCLI()
        generator = ReportGenerator(claude_cli=claude)
        artifact = await generator.generate(contest, analysis, data_path=data_file)

        storage.save_artifact(artifact)
        console.print(f"[green]보고서 생성 완료: {artifact.file_path}[/green]")

    asyncio.run(_run())


@app.command()
def status() -> None:
    """전체 공모전 현황 대시보드"""
    storage = _get_storage()
    contests = storage.load_contests()
    analyses = storage.load_analyses()
    artifacts = storage.load_artifacts()

    dashboard = CLIDashboard(console=console)

    stats = {
        "total": len(contests),
        "analyzed": len(analyses),
        "generated": len(artifacts),
        "submitted": sum(1 for c in contests if c.status == "제출완료"),
    }
    dashboard.show_summary(stats)
    dashboard.show_status(contests, analyses, artifacts)


@app.command()
def guide(
    contest_id: str = typer.Argument(..., help="공모전 ID"),
) -> None:
    """특정 공모전 제출 가이드 출력"""
    storage = _get_storage()
    contests = storage.load_contests()
    contest = next((c for c in contests if c.id == contest_id), None)

    if not contest:
        console.print(f"[red]공모전 '{contest_id}'을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    analyses = storage.load_analyses()
    analysis = next((a for a in analyses if a.contest_id == contest_id), None)

    from rich.panel import Panel
    from datetime import date

    today = date.today()
    days_left = (contest.deadline - today).days if contest.deadline else None
    dday_str = f"D-{days_left}" if days_left is not None and days_left >= 0 else "마감"

    lines = [
        f"[bold]제목:[/bold] {contest.title}",
        f"[bold]주최:[/bold] {contest.organizer}",
        f"[bold]마감:[/bold] {contest.deadline} ({dday_str})",
        f"[bold]URL:[/bold] {contest.url}",
    ]
    if analysis:
        lines += [
            f"[bold]유형:[/bold] {analysis.contest_type}",
            f"[bold]난이도:[/bold] {analysis.difficulty}",
            f"[bold]ROI:[/bold] {analysis.roi_score:.1f}",
            f"[bold]접근 전략:[/bold] {analysis.suggested_approach}",
            f"[bold]제출물:[/bold] {', '.join(analysis.required_deliverables)}",
        ]

    console.print(Panel("\n".join(lines), title=f"제출 가이드 — {contest_id}"))


@app.command("list")
def list_contests(
    state: str | None = typer.Option(None, "--state", help="상태 필터 (접수중|접수예정|마감)"),
) -> None:
    """공모전 목록 (상태별 필터 가능)"""
    storage = _get_storage()
    contests = storage.load_contests(state=state)

    if not contests:
        label = f" ({state})" if state else ""
        console.print(f"[yellow]공모전 목록이 없습니다{label}.[/yellow]")
        return

    analyses = storage.load_analyses()
    artifacts = storage.load_artifacts()
    dashboard = CLIDashboard(console=console)
    dashboard.show_status(contests, analyses, artifacts)


if __name__ == "__main__":
    app()
