"""텔레그램 봇 — long polling 기반 에이전틱 어시스턴트."""
import asyncio
import sys
from pathlib import Path

import httpx
import structlog

from src.bot.agent import ContestAgent
from src.config import settings
from src.core.claude_cli import ClaudeCLI
from src.core.storage import JSONStorage

logger = structlog.get_logger(__name__)

API_BASE = "https://api.telegram.org/bot{token}"
TELEGRAM_API_TIMEOUT = 60          # API 호출 timeout (초)
TELEGRAM_LONG_POLL_TIMEOUT = 30    # getUpdates long polling (초)
TELEGRAM_POLL_RETRY_DELAY = 5      # polling 실패 시 대기 (초)
CLAUDE_BOT_TIMEOUT = 180           # deprecated: 하위호환 유지 (아래 상수로 대체)
CLAUDE_BOT_SEMAPHORE = 1           # deprecated: 하위호환 유지 (아래 상수로 대체)

CLAUDE_AGENT_TIMEOUT = 60          # 자연어 대화는 짧음
CLAUDE_AGENT_SEMAPHORE = 1         # 1:1 채팅이라 직렬

CLAUDE_GEN_TIMEOUT = 600           # 보고서 생성은 분 단위
CLAUDE_GEN_SEMAPHORE = 2           # 동시 2개 생성 가능 (다른 contest)


class TelegramBot:
    def __init__(self, bot_token: str, allowed_chat_id: str) -> None:
        self.bot_token = bot_token
        self.allowed_chat_id = str(allowed_chat_id)
        self._base = API_BASE.format(token=bot_token)
        self._offset = 0

        storage = JSONStorage(base_dir=Path("data"))
        # 자연어 응답용 — 짧은 timeout
        self.agent_claude = ClaudeCLI(
            semaphore_limit=CLAUDE_AGENT_SEMAPHORE,
            timeout=CLAUDE_AGENT_TIMEOUT,
        )
        # 보고서 생성용 — 긴 timeout, 별도 semaphore
        self.gen_claude = ClaudeCLI(
            semaphore_limit=CLAUDE_GEN_SEMAPHORE,
            timeout=CLAUDE_GEN_TIMEOUT,
        )
        # 호환: bot.claude는 agent_claude로 alias (callbacks.py fallback 보호)
        self.claude = self.agent_claude

        self.agent = ContestAgent(storage=storage, claude=self.agent_claude)

    async def _api(self, method: str, **params) -> dict:
        async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
            resp = await client.post(f"{self._base}/{method}", json=params)
            resp.raise_for_status()
            return resp.json()

    async def _send(self, chat_id: str, text: str) -> None:
        # HTML 파싱 실패 시 일반 텍스트로 fallback
        try:
            await self._api(
                "sendMessage",
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning("html_parse_failed_fallback_plain", error=str(exc))
            await self._api(
                "sendMessage",
                chat_id=chat_id,
                text=text,
                disable_web_page_preview=True,
            )

    async def _send_typing(self, chat_id: str) -> None:
        try:
            await self._api("sendChatAction", chat_id=chat_id, action="typing")
        except Exception as exc:
            logger.debug("typing_action_failed", error=str(exc))

    async def _handle_web_app_data(self, message: dict) -> None:
        """Handle Telegram Mini App web_app_data payloads."""
        from src.bot.callbacks import dispatch_action, parse_web_app_data
        chat_id = str(message["chat"]["id"])
        raw = message.get("web_app_data", {}).get("data", "")
        payload = parse_web_app_data(raw)
        if payload is None:
            await self._send(chat_id, "WebApp 데이터를 읽을 수 없습니다.")
            return
        await dispatch_action(self, chat_id, payload)

    async def _answer_callback_query(self, cq_id: str, text: str = "") -> None:
        """Telegram 15초 timeout 회피 — 즉시 ack."""
        try:
            await self._api("answerCallbackQuery", callback_query_id=cq_id, text=text)
        except Exception as exc:
            logger.warning("answer_callback_failed", error=str(exc))

    async def _handle_callback_query(self, cq: dict) -> None:
        """Handle inline keyboard button callback_query updates."""
        cq_id = cq["id"]
        chat_id = str(cq["message"]["chat"]["id"])
        user_id = str(cq.get("from", {}).get("id", ""))
        data = cq.get("data", "")

        # 인증: chat_id와 user_id 모두 검증
        if chat_id != self.allowed_chat_id or user_id != self.allowed_chat_id:
            await self._answer_callback_query(cq_id, text="권한 없음")
            return

        # 즉시 ack (15초 timeout 회피)
        await self._answer_callback_query(cq_id)

        # parse "action:contest_id"
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        action_prefix, contest_id = parts[0], parts[1]

        # views.py 약속: pdf, gd, gen
        action_map = {"pdf": "pdf", "gd": "guide", "gen": "generate"}
        canonical_action = action_map.get(action_prefix)
        if not canonical_action:
            return

        from src.bot.callbacks import dispatch_action
        await dispatch_action(self, chat_id, {"action": canonical_action, "contest_id": contest_id})

    async def _handle_message(self, message: dict) -> None:
        chat_id = str(message["chat"]["id"])
        from_id = str(message.get("from", {}).get("id", ""))

        # web_app_data takes priority over text
        if "web_app_data" in message:
            if chat_id != self.allowed_chat_id or from_id != self.allowed_chat_id:
                await self._send(chat_id, "접근 권한이 없습니다.")
                return
            await self._handle_web_app_data(message)
            return

        text = message.get("text", "")

        if not text:
            return

        # 본인만 사용 가능 (chat_id + user.id 모두 검증)
        if chat_id != self.allowed_chat_id or from_id != self.allowed_chat_id:
            await self._send(chat_id, "접근 권한이 없습니다.")
            return

        logger.info("message_received", chat_id=chat_id, text=text[:50])

        # /start 명령
        if text.strip() == "/start":
            await self._send(
                chat_id,
                "<b>공모전 에이전트</b> 준비 완료!\n\n"
                "자연어로 물어보세요. 예시:\n"
                '• "마감 임박한 공모전 뭐 있어?"\n'
                '• "ROI 높은 순서로 보여줘"\n'
                '• "상금 1000만원 이상인 거 있어?"\n'
                '• "데이터분석 유형 공모전만"\n'
                '• "ck_202603180064 상세 알려줘"',
            )
            return

        # 에이전트에게 위임
        await self._send_typing(chat_id)
        response = await self.agent.answer(text)
        await self._send(chat_id, response)

    async def _check_orphaned_running(self) -> None:
        """봇 시작 시 status=running 잔존 보고서 발견 → 사용자에게 알림 + status=failed 마킹."""
        storage = JSONStorage(base_dir=Path("data"))
        orphans = [a for a in storage.load_artifacts() if a.status == "running"]
        if not orphans:
            return
        titles = []
        for o in orphans:
            contest = storage.get_contest(o.contest_id)
            title = contest.title if contest else o.contest_id
            titles.append(title)
            o.status = "failed"
            storage.save_artifact(o)
        msg = (
            "⚠️ <b>이전 세션 미완 보고서 감지</b>\n"
            f"{len(orphans)}건의 보고서 생성이 중단되었습니다:\n"
            + "\n".join(f"• {t}" for t in titles[:5])
            + "\n\n다시 [⚡ 생성] 버튼을 눌러주세요."
        )
        await self._send(self.allowed_chat_id, msg)

    async def run(self) -> None:
        """Long polling 시작."""
        logger.info("bot_started", chat_id=self.allowed_chat_id)
        try:
            await self._check_orphaned_running()
        except Exception as exc:
            logger.warning("orphan_check_failed", error=str(exc))

        while True:
            try:
                data = await self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=TELEGRAM_LONG_POLL_TIMEOUT,
                )
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    if "callback_query" in update:
                        await self._handle_callback_query(update["callback_query"])
                    elif "message" in update:
                        await self._handle_message(update["message"])
            except httpx.TimeoutException:
                continue
            except Exception as e:
                logger.error("polling_error", error=str(e), exc_info=True)
                await asyncio.sleep(TELEGRAM_POLL_RETRY_DELAY)


def main() -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        sys.stderr.write("[ERROR] .env에 INFOKE_TELEGRAM_BOT_TOKEN, INFOKE_TELEGRAM_CHAT_ID 설정 필요\n")
        logger.error("missing_credentials")
        return

    bot = TelegramBot(
        bot_token=settings.telegram_bot_token,
        allowed_chat_id=settings.telegram_chat_id,
    )
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
