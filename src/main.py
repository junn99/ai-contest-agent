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
    from src.collectors.filters import apply_all_filters
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
        filtered = apply_all_filters(all_contests, min_preparation_days=settings.min_preparation_days)
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
        analyzer = ContestAnalyzer(claude_cli=claude)
        scorer = ROIScorer()
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
        contest = storage.get_contest(contest_id)
        if not contest:
            console.print(f"[red]공모전 '{contest_id}'을 찾을 수 없습니다.[/red]")
            raise typer.Exit(1)

        analysis = storage.get_analysis(contest_id)
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
    contest = storage.get_contest(contest_id)

    if not contest:
        console.print(f"[red]공모전 '{contest_id}'을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    analysis = storage.get_analysis(contest_id)

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


@app.command()
def run(
    top_n: int = typer.Option(3, "--top", help="ROI 상위 N개 공모전에 보고서 생성"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="공공데이터 CSV 디렉토리"),
    no_push: bool = typer.Option(False, "--no-push", help="텔레그램 카드/다이제스트 자동 push 비활성화"),
) -> None:
    """전체 파이프라인 자동 실행 (수집 → 분석 → 보고서 생성 → 알림)"""
    from src.collectors.contestkorea import ContestKoreaCollector
    from src.collectors.wevity import WevityCollector
    from src.collectors.filters import apply_all_filters
    from src.analyzers.contest_analyzer import ContestAnalyzer
    from src.analyzers.roi_scorer import ROIScorer
    from src.analyzers.pipeline import AnalysisPipeline
    from src.generators.report_generator import ReportGenerator
    from src.notifiers.deadline_notifier import DeadlineNotifier
    from src.notifiers.telegram import TelegramNotifier
    from src.core.claude_cli import ClaudeCLI
    from src.config import settings

    async def _step_collect() -> tuple[list, list]:
        """returns (raw_all, filtered)"""
        console.print("\n[bold cyan][ 1/4 ] 공모전 수집 중...[/bold cyan]")
        collectors = [
            ("콘테스트코리아", ContestKoreaCollector()),
            ("위비티", WevityCollector()),
        ]
        all_contests = []
        for name, col in collectors:
            try:
                items = await col.discover()
                console.print(f"  {name}: {len(items)}건")
                all_contests.extend(items)
            except Exception as exc:
                console.print(f"  [red]{name} 실패: {exc}[/red]")
                logger.error("collector_failed", collector=name, error=str(exc), exc_info=True)

        if not all_contests:
            return [], []

        filtered = apply_all_filters(all_contests, min_preparation_days=settings.min_preparation_days)
        console.print(f"  필터링 후: [green]{len(filtered)}건[/green] (전체 {len(all_contests)}건 중)")
        return all_contests, filtered

    async def _step_analyze(filtered: list, claude: ClaudeCLI) -> tuple[list, list]:
        """returns (new_analyses, all_analyses_sorted)"""
        console.print("\n[bold cyan][ 2/4 ] Claude 분석 + ROI 스코어링...[/bold cyan]")
        storage = _get_storage()
        analyzer = ContestAnalyzer(claude_cli=claude)
        scorer = ROIScorer()
        pipeline = AnalysisPipeline(analyzer=analyzer, scorer=scorer, settings=settings)

        analyzed_ids = {a.contest_id for a in storage.load_analyses()}
        to_analyze = [c for c in filtered if c.id not in analyzed_ids]

        new_analyses = []
        if to_analyze:
            console.print(f"  신규 분석: {len(to_analyze)}건")
            new_analyses = await pipeline.run(to_analyze)
            for a in new_analyses:
                storage.save_analysis(a)
            console.print(f"  [green]분석 완료: {len(new_analyses)}건[/green]")
        else:
            console.print("  신규 분석 대상 없음 (기존 분석 결과 사용)")

        return new_analyses, storage.load_analyses_sorted_by_roi()

    async def _step_generate(
        all_analyses: list, filtered: list, top_n: int, data_dir: str | None, claude: ClaudeCLI
    ) -> list[str]:
        """returns generated_titles"""
        console.print(f"\n[bold cyan][ 3/4 ] ROI 상위 {top_n}개 보고서 생성...[/bold cyan]")
        storage = _get_storage()
        generator = ReportGenerator(claude_cli=claude)
        generated_ids = {a.contest_id for a in storage.load_artifacts()}
        targets = [a for a in all_analyses if a.contest_id not in generated_ids][:top_n]

        csv_path: Path | None = None
        if data_dir:
            data_p = Path(data_dir)
            for ext in ("*.csv", "*.xlsx", "*.xls"):
                matches = list(data_p.glob(ext))
                if matches:
                    csv_path = matches[0]
                    break

        generated_titles: list[str] = []
        for i, analysis in enumerate(targets, 1):
            contest = next((c for c in filtered if c.id == analysis.contest_id), None)
            if not contest:
                continue
            console.print(f"  [{i}/{len(targets)}] {contest.title}")
            try:
                artifact = await generator.generate(contest, analysis, data_path=csv_path)
                storage.save_artifact(artifact)
                generated_titles.append(contest.title)
                console.print(f"    [green]완료 → {artifact.file_path}[/green]")
            except Exception as exc:
                console.print(f"    [red]실패: {exc}[/red]")
                logger.error("report_generation_failed", contest_id=contest.id, error=str(exc), exc_info=True)

        return generated_titles

    def _step_deadlines(filtered: list, dashboard: CLIDashboard) -> list:
        """returns alerts"""
        console.print("\n[bold cyan][ 4/4 ] 마감 알림 확인...[/bold cyan]")
        notifier = DeadlineNotifier(settings=settings)
        alerts = notifier.check_deadlines(filtered)
        if alerts:
            dashboard.show_deadlines(alerts)
        else:
            console.print("  마감 임박 공모전 없음")
        return alerts

    def _step_summary(filtered: list, all_analyses: list, dashboard: CLIDashboard) -> None:
        storage = _get_storage()
        console.print("\n" + "=" * 50)
        stats = {
            "total": len(filtered),
            "analyzed": len(all_analyses),
            "generated": len(storage.load_artifacts()),
            "submitted": 0,
        }
        dashboard.show_summary(stats)
        console.print("[bold green]전체 파이프라인 완료![/bold green]\n")

    async def _step_telegram(
        new_contests_count: int,
        filtered_count: int,
        new_analyses_count: int,
        generated_titles: list[str],
        alerts: list,
        filtered: list,
        no_push: bool,
    ) -> None:
        if no_push:
            console.print("[dim]--no-push: 텔레그램 푸시 생략[/dim]")
            return
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            console.print("[dim]텔레그램 미설정 — .env에 INFOKE_TELEGRAM_BOT_TOKEN, INFOKE_TELEGRAM_CHAT_ID 추가[/dim]")
            return
        tg = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        alert_messages = [f"[D-{a.days_remaining}] {a.contest_title}" for a in alerts]
        message = tg.format_run_summary(
            new_contests=new_contests_count,
            total_filtered=filtered_count,
            new_analyses=new_analyses_count,
            new_reports=generated_titles,
            alerts=alert_messages,
        )
        await tg.send(message)

        storage = _get_storage()
        all_analyses = storage.load_analyses_sorted_by_roi()
        all_artifacts = storage.load_artifacts()
        await tg.send_digest(
            contests=filtered,
            analyses=all_analyses,
            artifacts=all_artifacts,
            alerts=alert_messages,
        )
        console.print("[green]텔레그램 다이제스트 카드 전송 완료[/green]")

    async def _run() -> None:
        dashboard = CLIDashboard(console=console)
        storage = _get_storage()

        all_contests, filtered = await _step_collect()
        if not all_contests:
            console.print("[red]수집된 공모전이 없습니다. 종료합니다.[/red]")
            return
        storage.save_contests(filtered)

        claude = ClaudeCLI()
        new_analyses, all_analyses = await _step_analyze(filtered, claude)
        if all_analyses:
            dashboard.show_roi_ranking(all_analyses, contests=filtered)

        generated_titles = await _step_generate(all_analyses, filtered, top_n, data_dir, claude)
        alerts = _step_deadlines(filtered, dashboard)
        _step_summary(filtered, all_analyses, dashboard)
        await _step_telegram(
            len(all_contests), len(filtered), len(new_analyses), generated_titles, alerts,
            filtered=filtered,
            no_push=no_push,
        )

    asyncio.run(_run())


@app.command()
def digest(
    top_n: int = typer.Option(5, "--top", help="ROI 상위 N개 카드 전송"),
) -> None:
    """텔레그램에 다이제스트 카드 수동 전송 (cron 등록 금지 — run이 자동 포함)"""
    from src.notifiers.telegram import TelegramNotifier
    from src.notifiers.deadline_notifier import DeadlineNotifier
    from src.config import settings

    async def _run() -> None:
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            console.print("[red]텔레그램 미설정 — .env에 INFOKE_TELEGRAM_BOT_TOKEN, INFOKE_TELEGRAM_CHAT_ID 추가[/red]")
            raise typer.Exit(1)

        storage = _get_storage()
        contests = storage.load_contests()
        analyses = storage.load_analyses_sorted_by_roi()
        artifacts = storage.load_artifacts()

        if not contests:
            console.print("[yellow]공모전 데이터 없음. 먼저 run 또는 collect를 실행하세요.[/yellow]")
            raise typer.Exit(1)

        notifier = DeadlineNotifier(settings=settings)
        raw_alerts = notifier.check_deadlines(contests)
        alert_messages = [f"[D-{a.days_remaining}] {a.contest_title}" for a in raw_alerts]

        tg = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        console.print(f"[bold]다이제스트 전송 중 (상위 {top_n}개)...[/bold]")
        ok = await tg.send_digest(
            contests=contests,
            analyses=analyses,
            artifacts=artifacts,
            alerts=alert_messages,
            top_n=top_n,
        )
        if ok:
            console.print("[green]다이제스트 전송 완료[/green]")
        else:
            console.print("[red]다이제스트 전송 실패[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command()
def bot() -> None:
    """텔레그램 에이전틱 봇 실행 (long polling)"""
    from src.bot.telegram_bot import main as bot_main
    bot_main()


if __name__ == "__main__":
    app()
