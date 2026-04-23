"""Telegram 메시지 포맷터 — pure functions, storage 의존 없음."""
import html
from typing import Optional

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.config import settings

WEBAPP_URL: str = settings.webapp_url

MAX_MESSAGE_LEN = 4096
MAX_CAPTION_LEN = 1024

_URGENCY_BADGE = {
    "critical": "🚨",  # D-3 이하
    "warning": "⚠️",   # D-7 이하
    "info": "ℹ️",      # D-14 이하
}

_STATUS_BADGE = {
    "pending": "⏳",
    "running": "🔄",
    "done": "✅",
    "failed": "❌",
}

_DIFFICULTY_BADGE = {
    "LOW": "🟢",
    "MEDIUM": "🟡",
    "HIGH": "🔴",
}

_TYPE_BADGE = {
    "보고서": "📄",
    "아이디어": "💡",
    "SW개발": "💻",
    "데이터분석": "📊",
    "기타": "📌",
}


def _urgency(d_day: int | None) -> tuple[str, str]:
    """(badge, label) — d_day None이면 빈 문자열."""
    if d_day is None:
        return "", ""
    if d_day <= 3:
        return _URGENCY_BADGE["critical"], f"D-{d_day}"
    if d_day <= 7:
        return _URGENCY_BADGE["warning"], f"D-{d_day}"
    if d_day <= 14:
        return _URGENCY_BADGE["info"], f"D-{d_day}"
    return "", f"D-{d_day}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_webapp_keyboard(webapp_url: str | None = None) -> dict:
    """다이제스트 헤더용 [📊 대시보드 열기] WebApp 버튼 reply_markup."""
    url = webapp_url or WEBAPP_URL
    return {
        "inline_keyboard": [[
            {"text": "📊 대시보드 열기", "web_app": {"url": url}},
        ]]
    }


def build_navigation_keyboard(
    contest_id: str,
    contest_url: str | None,
    artifact: Optional[ReportArtifact],
    d_day: int | None,
) -> list[list[dict]] | None:
    """navigation-only inline keyboard 빌더.

    - 보고서 done: [📥 PDF][📋 가이드]
    - 원문 링크 (항상): [🔗 원문 보기]
    - D-3 이하 + artifact 없음(또는 failed): 버튼 없음, 텍스트 안내로 대체
    - 그 외: None (버튼 없음)
    """
    rows = []

    has_artifact = artifact is not None and artifact.status == "done"
    if has_artifact:
        rows.append([
            {"text": "📥 PDF", "callback_data": f"pdf:{contest_id}"},
            {"text": "📋 가이드", "callback_data": f"gd:{contest_id}"},
        ])

    # 원문 링크 버튼 (항상 추가, url field 사용 → callback handler 불필요)
    if contest_url:
        rows.append([{"text": "🔗 원문 보기", "url": contest_url}])

    return rows if rows else None


def format_contest_card(
    contest: ContestInfo,
    analysis: ContestAnalysis,
    artifact: Optional[ReportArtifact],
) -> tuple[str, dict | None]:
    """카드 텍스트(HTML) + reply_markup dict.

    Returns:
        (text, reply_markup) — reply_markup은 inline_keyboard가 없으면 None.
    """
    urgency_badge, d_label = _urgency(contest.d_day)
    type_badge = _TYPE_BADGE.get(analysis.contest_type, "📌")
    diff_badge = _DIFFICULTY_BADGE.get(analysis.difficulty, "")

    title = html.escape(contest.title)
    # Fix 5: organizer 40자 제한
    organizer = html.escape(_truncate(contest.organizer, 40))
    approach = html.escape(analysis.suggested_approach)

    # Fix 6: ROI 별 0~10 범위 방지
    roi_int = max(0, min(10, round(analysis.roi_score)))
    roi_stars = "★" * roi_int + "☆" * (10 - roi_int)

    status_badge = ""
    if artifact is not None:
        status_badge = _STATUS_BADGE.get(artifact.status, "")

    header_parts = []
    if urgency_badge:
        header_parts.append(f"{urgency_badge} <b>{d_label}</b>")
    header_parts.append(f"{type_badge} <b>{title}</b>")

    lines = [
        " ".join(header_parts),
        f"🏢 {organizer}",
    ]

    # Fix 4: deadline 한 줄로 통합
    if contest.deadline:
        deadline_label = f"📅 마감: {d_label} ({contest.deadline})" if d_label else f"📅 마감: {contest.deadline}"
        lines.append(deadline_label)
    elif d_label:
        lines.append(f"📅 마감: {d_label}")

    prize_str = f"{contest.prize_amount:,}원" if contest.prize_amount else (contest.prize or "—")
    lines.append(f"💰 상금: {html.escape(prize_str)}")
    lines.append(f"📈 ROI: {roi_stars} ({analysis.roi_score:.1f}/10)")
    lines.append(f"🎯 난이도: {diff_badge} {analysis.difficulty}")
    lines.append(f"💬 접근: {approach}")

    # Fix 2: required_deliverables 노출
    if analysis.required_deliverables:
        deliverables_str = ", ".join(analysis.required_deliverables[:5])
        lines.append(f"📦 제출물: {html.escape(deliverables_str)}")

    if status_badge:
        lines.append(f"📋 보고서: {status_badge} {artifact.status}")  # type: ignore[union-attr]

    # Fix 3: D-3 미생성 케이스 → 텍스트 안내 (클릭 무반응 버튼 제거)
    d_day = contest.d_day
    if d_day is not None and d_day <= 3 and (artifact is None or artifact.status != "done"):
        lines.append(f"⚡ <i>마감 임박! `uv run python -m src.main generate {contest.id}` 실행 권장</i>")

    text = _truncate("\n".join(lines), MAX_MESSAGE_LEN)

    # Fix 1: contest.url 전달
    keyboard = build_navigation_keyboard(contest.id, contest.url, artifact, contest.d_day)
    reply_markup = {"inline_keyboard": keyboard} if keyboard else None

    return text, reply_markup


def format_digest_header(
    total: int,
    imminent: int,
    done_reports: int,
    total_reports: int,
) -> str:
    """다이제스트 핀 메시지 헤더."""
    lines = [
        "<b>📋 공모전 에이전트 일일 다이제스트</b>",
        "",
        f"📊 활성 공모전: {total}건",
        f"🚨 마감 임박 (D-7 이하): {imminent}건",
        f"📄 보고서: {done_reports}/{total_reports} 완료",
    ]
    return _truncate("\n".join(lines), MAX_MESSAGE_LEN)


def format_deadline_pin(
    contests: list[ContestInfo],
    analyses: list[ContestAnalysis],
) -> str:
    """마감 임박 핀 메시지 — D-7 이하 공모전 목록."""
    analysis_map = {a.contest_id: a for a in analyses}
    imminent = [c for c in contests if c.d_day is not None and c.d_day <= 7]
    imminent.sort(key=lambda c: c.d_day or 0)

    lines = ["<b>⏰ 마감 임박 공모전</b>", ""]
    for c in imminent:
        badge, d_label = _urgency(c.d_day)
        roi = ""
        if c.id in analysis_map:
            roi = f" ROI {analysis_map[c.id].roi_score:.1f}"
        lines.append(f"{badge} [{d_label}] {html.escape(c.title)}{roi}")

    if not imminent:
        lines.append("마감 임박 공모전 없음")

    return _truncate("\n".join(lines), MAX_MESSAGE_LEN)


def format_done(artifact: ReportArtifact) -> str:
    """보고서 생성 완료 알림."""
    lines = [
        f"✅ <b>보고서 생성 완료</b>",
        f"📄 {html.escape(artifact.title)}",
        f"📝 {artifact.word_count:,}자",
    ]
    return _truncate("\n".join(lines), MAX_CAPTION_LEN)


def format_failed(contest_id: str, error: str) -> str:
    """보고서 생성 실패 알림."""
    lines = [
        "❌ <b>보고서 생성 실패</b>",
        f"🆔 {html.escape(contest_id)}",
        f"⚠️ {html.escape(error)}",
    ]
    return _truncate("\n".join(lines), MAX_MESSAGE_LEN)
