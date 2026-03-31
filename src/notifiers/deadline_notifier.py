"""Deadline notification system."""
from datetime import date

import structlog
from pydantic import BaseModel

from src.config import Settings
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


class DeadlineAlert(BaseModel):
    contest_id: str
    contest_title: str
    deadline: date
    days_remaining: int
    urgency: str  # "critical" | "warning" | "info"
    message: str


class DeadlineNotifier:
    """마감 알림 시스템"""

    ALERT_DAYS = [14, 7, 3, 1]  # D-14, D-7, D-3, D-1

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def check_deadlines(self, contests: list[ContestInfo]) -> list[DeadlineAlert]:
        """마감 임박 공모전 확인."""
        alerts: list[DeadlineAlert] = []
        today = date.today()

        for contest in contests:
            if contest.deadline is None:
                continue
            days_left = (contest.deadline - today).days
            if days_left not in self.ALERT_DAYS:
                continue

            if days_left <= 3:
                urgency = "critical"
            elif days_left <= 7:
                urgency = "warning"
            else:
                urgency = "info"

            alerts.append(
                DeadlineAlert(
                    contest_id=contest.id,
                    contest_title=contest.title,
                    deadline=contest.deadline,
                    days_remaining=days_left,
                    urgency=urgency,
                    message=f"[D-{days_left}] {contest.title} 마감 {days_left}일 전",
                )
            )

        logger.info("deadline_check_complete", alert_count=len(alerts))
        return alerts

    def format_alert(self, alert: DeadlineAlert) -> str:
        """Rich 포맷팅된 알림 메시지."""
        icons = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}
        icon = icons.get(alert.urgency, "")
        deadline_str = alert.deadline.strftime("%Y년 %m월 %d일")
        return (
            f"{icon} {alert.message}\n"
            f"   마감일: {deadline_str}\n"
            f"   긴급도: {alert.urgency}"
        )
