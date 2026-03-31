"""Rich 기반 CLI 대시보드."""
from datetime import date, datetime

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


class CLIDashboard:
    """Rich 기반 CLI 대시보드"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def show_status(
        self,
        contests: list[ContestInfo],
        analyses: list[ContestAnalysis],
        artifacts: list[ReportArtifact],
    ) -> None:
        """전체 현황 테이블"""
        analysis_map = {a.contest_id: a for a in analyses}
        artifact_map = {a.contest_id: a for a in artifacts}

        table = Table(title="공공 AI 공모전 현황")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("제목", style="bold")
        table.add_column("플랫폼")
        table.add_column("마감일", style="red")
        table.add_column("D-Day")
        table.add_column("상태", style="green")
        table.add_column("ROI", justify="right")
        table.add_column("보고서")

        today = date.today()
        for c in contests:
            analysis = analysis_map.get(c.id)
            artifact = artifact_map.get(c.id)

            deadline_str = str(c.deadline) if c.deadline else "-"
            if c.deadline:
                days_left = (c.deadline - today).days
                dday_str = f"D-{days_left}" if days_left >= 0 else "마감"
            else:
                dday_str = "-"

            roi_str = f"{analysis.roi_score:.1f}" if analysis else "-"
            report_str = "O" if artifact else "-"

            table.add_row(
                c.id,
                c.title[:30] + ("..." if len(c.title) > 30 else ""),
                c.platform,
                deadline_str,
                dday_str,
                c.status,
                roi_str,
                report_str,
            )

        self.console.print(table)

    def show_summary(self, stats: dict) -> None:
        """통계 요약 패널"""
        panel = Panel(
            f"수집: {stats.get('total', 0)}건 | "
            f"분석: {stats.get('analyzed', 0)}건 | "
            f"생성: {stats.get('generated', 0)}건 | "
            f"제출: {stats.get('submitted', 0)}건",
            title="요약",
        )
        self.console.print(panel)

    def show_roi_ranking(self, analyses: list[ContestAnalysis], contests: list[ContestInfo] | None = None) -> None:
        """ROI 상위 공모전 랭킹"""
        contest_map = {c.id: c for c in (contests or [])}

        sorted_analyses = sorted(analyses, key=lambda a: a.roi_score, reverse=True)[:5]

        table = Table(title="ROI 상위 공모전 (집중 타격 대상)")
        table.add_column("순위", justify="center")
        table.add_column("제목", style="bold")
        table.add_column("ROI", justify="right", style="green")
        table.add_column("난이도")
        table.add_column("마감")

        for rank, analysis in enumerate(sorted_analyses, start=1):
            contest = contest_map.get(analysis.contest_id)
            title = contest.title[:30] + ("..." if contest and len(contest.title) > 30 else "") if contest else analysis.contest_id
            deadline_str = str(contest.deadline) if contest and contest.deadline else "-"
            table.add_row(
                str(rank),
                title,
                f"{analysis.roi_score:.1f}",
                analysis.difficulty,
                deadline_str,
            )

        self.console.print(table)

    def show_deadlines(self, alerts: list) -> None:
        """마감 임박 알림"""
        for alert in alerts:
            urgency = getattr(alert, "urgency", "info")
            message = getattr(alert, "message", str(alert))
            if urgency == "critical":
                style = "red bold"
            elif urgency == "warning":
                style = "yellow"
            else:
                style = "blue"
            self.console.print(f"[{style}]{message}[/{style}]")
