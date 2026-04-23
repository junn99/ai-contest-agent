"""WebApp action dispatcher — handles web_app_data payloads from Telegram Mini App."""
import asyncio
import html
import json
import re
import structlog
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot.telegram_bot import TelegramBot

logger = structlog.get_logger(__name__)

# Task set to prevent GC collection of fire-and-forget tasks (Python 3.11+ guideline)
_pending_tasks: set[asyncio.Task] = set()

# chat_id -> set of contest_ids currently being generated (R-A6 in-flight dedup)
_in_flight: dict[str, set[str]] = {}

# Allowed contest_id prefixes and character whitelist
_ALLOWED_PREFIXES = ("ck_", "wv_")
_ID_RE = re.compile(r'^[a-zA-Z0-9_]+$')
_MAX_ID_LEN = 64


def validate_contest_id(contest_id: str) -> bool:
    """Whitelist validation: must start with allowed prefix, alphanumeric+underscore only."""
    if not isinstance(contest_id, str):
        return False
    if len(contest_id) > _MAX_ID_LEN:
        return False
    if not any(contest_id.startswith(p) for p in _ALLOWED_PREFIXES):
        return False
    return bool(_ID_RE.match(contest_id))


def parse_web_app_data(raw: str) -> dict | None:
    """Parse JSON payload from web_app_data. Returns None on error."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        logger.warning("web_app_data_parse_failed", raw=raw[:100])
        return None


async def dispatch_action(bot: "TelegramBot", chat_id: str, payload: dict) -> None:
    """Route action to the appropriate handler."""
    action = payload.get("action")
    contest_id = payload.get("contest_id", "")

    if not validate_contest_id(contest_id):
        logger.warning("invalid_contest_id", contest_id=contest_id)
        await bot._send(chat_id, "잘못된 공모전 ID입니다.")
        return

    logger.info("web_app_action", action=action, contest_id=contest_id)

    if action == "pdf":
        await handle_pdf(bot, chat_id, contest_id)
    elif action == "generate":
        await handle_generate(bot, chat_id, contest_id)
    elif action == "guide":
        await handle_guide(bot, chat_id, contest_id)
    else:
        logger.warning("unknown_web_app_action", action=action)
        await bot._send(chat_id, f"알 수 없는 액션: {action}")


async def handle_pdf(bot: "TelegramBot", chat_id: str, contest_id: str) -> None:
    """Send existing PDF/report artifact to the user."""
    from src.core.storage import JSONStorage
    storage = JSONStorage(base_dir=Path("data"))

    artifact = storage.get_artifact(contest_id)
    contest = storage.get_contest(contest_id)
    title = contest.title if contest else contest_id

    if artifact is None or artifact.status != "done":
        await bot._send(chat_id, f"<b>{title}</b>\n보고서가 아직 생성되지 않았습니다. ⚡ 생성 버튼을 눌러주세요.")
        return

    path = Path(artifact.path) if artifact.path else None
    if path is None or not path.exists():
        await bot._send(chat_id, f"<b>{title}</b>\n보고서 파일을 찾을 수 없습니다.")
        return

    caption = f"📄 <b>{title}</b> 보고서"
    from src.notifiers.telegram import TelegramNotifier
    notifier = TelegramNotifier(bot_token=bot.bot_token, chat_id=chat_id)
    success = await notifier.send_document(path, caption=caption, chat_id=chat_id)
    if not success:
        await bot._send(chat_id, f"{caption}\n\n파일 전송에 실패했습니다.")


async def handle_generate(bot: "TelegramBot", chat_id: str, contest_id: str) -> None:
    """Trigger async report generation; send immediate ack then background task."""
    from src.core.storage import JSONStorage
    storage = JSONStorage(base_dir=Path("data"))

    contest = storage.get_contest(contest_id)
    if contest is None:
        await bot._send(chat_id, "해당 공모전을 찾을 수 없습니다.")
        return

    artifact = storage.get_artifact(contest_id)
    if artifact and artifact.status == "done":
        await bot._send(chat_id, f"<b>{contest.title}</b>\n보고서가 이미 생성되어 있습니다. 📥 PDF 버튼을 눌러주세요.")
        return

    # R-A6: 같은 chat_id+contest_id 동시 클릭 차단
    in_flight = _in_flight.setdefault(chat_id, set())
    if contest_id in in_flight:
        await bot._send(chat_id, f"⏳ <b>{contest.title}</b>\n이미 생성 중입니다.")
        return
    in_flight.add(contest_id)

    # Immediate ack
    await bot._send(chat_id, f"⚡ <b>{contest.title}</b>\n보고서 생성 중... 잠시만 기다려주세요.")

    async def _wrapped():
        try:
            await _run_generate_with_timeout(bot, chat_id, contest_id, contest.title)
        finally:
            in_flight.discard(contest_id)

    # Fire-and-forget background task — store ref to prevent GC collection
    task = asyncio.create_task(_wrapped())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _run_generate_with_timeout(bot: "TelegramBot", chat_id: str, contest_id: str, title: str) -> None:
    """Background report generation task with 10-minute timeout."""
    try:
        await asyncio.wait_for(
            _run_generate(bot, chat_id, contest_id, title),
            timeout=600,  # 10분
        )
    except asyncio.TimeoutError:
        await bot._send(chat_id, "⏱️ 보고서 생성 시간 초과 (10분). 재시도해주세요.")
    except Exception as exc:
        logger.error("generate_failed", contest_id=contest_id, error=str(exc), exc_info=True)
        await bot._send(chat_id, "❌ 보고서 생성 실패. 로그를 확인해주세요.")


async def _run_generate(bot: "TelegramBot", chat_id: str, contest_id: str, title: str) -> None:
    """Real report generation: ReportGenerator + storage + sendDocument."""
    from src.core.storage import JSONStorage
    from src.generators.report_generator import ReportGenerator
    from src.notifiers.telegram import TelegramNotifier

    storage = JSONStorage(base_dir=Path("data"))
    contest = storage.get_contest(contest_id)
    analysis = storage.get_analysis(contest_id)

    if contest is None or analysis is None:
        await bot._send(chat_id, f"❌ <b>{title}</b> — 공모전 또는 분석 정보가 없습니다.")
        return

    # status: running 마킹 (R-A4 영속화)
    artifact_existing = storage.get_artifact(contest_id)
    if artifact_existing:
        artifact_existing.status = "running"
        storage.save_artifact(artifact_existing)

    # bot.gen_claude 사용 (Group Y가 추가). 없으면 fallback to bot.claude
    claude = getattr(bot, "gen_claude", None) or getattr(bot, "claude", None)
    if claude is None:
        await bot._send(chat_id, f"❌ <b>{title}</b> — Claude CLI 미초기화.")
        return

    generator = ReportGenerator(claude_cli=claude)
    try:
        artifact = await generator.generate(contest, analysis)
        artifact.status = "done"
        storage.save_artifact(artifact)
    except Exception as exc:
        # 실패 status 마킹
        if artifact_existing:
            artifact_existing.status = "failed"
            storage.save_artifact(artifact_existing)
        else:
            from src.models.artifact import ReportArtifact
            from datetime import datetime
            stub = ReportArtifact(
                contest_id=contest_id,
                report_type="analysis_report",
                file_path=Path("/dev/null"),
                markdown_path=Path("/dev/null"),
                title=title,
                sections=[],
                data_sources=[],
                visualizations=[],
                word_count=0,
                generated_at=datetime.utcnow(),
                generation_duration_sec=0.0,
                status="failed",
            )
            storage.save_artifact(stub)
        raise

    # 완료 메시지 + PDF 첨부
    notifier = TelegramNotifier(bot_token=bot.bot_token, chat_id=chat_id)
    caption = f"✅ <b>{title}</b> 보고서 생성 완료!\n📝 {artifact.word_count:,}자"
    await notifier.send_document(artifact.file_path, caption=caption, chat_id=chat_id)


async def handle_guide(bot: "TelegramBot", chat_id: str, contest_id: str) -> None:
    """Send submission guide for a contest."""
    from src.core.storage import JSONStorage
    storage = JSONStorage(base_dir=Path("data"))

    contest = storage.get_contest(contest_id)
    analysis = storage.get_analysis(contest_id)

    if contest is None:
        await bot._send(chat_id, "해당 공모전을 찾을 수 없습니다.")
        return

    if analysis is None:
        await bot._send(chat_id, "분석 정보가 없습니다.")
        return

    deadline_str = str(contest.deadline) if contest.deadline else "미정"
    d_day_str = f"D-{contest.d_day}" if contest.d_day is not None else ""
    lines = [
        f"<b>📋 {html.escape(contest.title)}</b>",
        f"⏰ 마감: {deadline_str} ({d_day_str})",
        f"💡 접근전략: {html.escape(analysis.suggested_approach)}",
    ]
    if analysis.required_deliverables:
        items = ", ".join(html.escape(d) for d in analysis.required_deliverables[:5])
        lines.append(f"📦 제출물: {items}")
    if analysis.relevant_public_data:
        items = ", ".join(html.escape(d) for d in analysis.relevant_public_data[:3])
        lines.append(f"📊 공공데이터: {items}")

    await bot._send(chat_id, "\n".join(lines))
