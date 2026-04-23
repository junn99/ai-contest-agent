"""Telegram 알림 발송."""
import asyncio
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

import httpx
import structlog

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.notifiers import views

logger = structlog.get_logger(__name__)

API_BASE = "https://api.telegram.org/bot{token}"

_PDF_SIZE_LIMIT = 45 * 1024 * 1024  # 45MB
RATE_LIMIT_SLEEP_SEC = 1.1  # Telegram: 1 msg/sec per chat
TELEGRAM_API_TIMEOUT = 30
TELEGRAM_429_MAX_RETRIES = 3
TELEGRAM_429_BUFFER_SEC = 0.5

# chat_id별 rate limiter 상태
_last_send_time: dict[str, float] = defaultdict(float)
_send_locks: dict[str, asyncio.Lock] = {}


def _get_send_lock(chat_id: str) -> asyncio.Lock:
    """chat_id별 Lock을 반환 (없으면 생성)."""
    if chat_id not in _send_locks:
        _send_locks[chat_id] = asyncio.Lock()
    return _send_locks[chat_id]


async def _enforce_rate_limit(chat_id: str) -> None:
    """Telegram chat당 1msg/sec 보장."""
    lock = _get_send_lock(chat_id)
    async with lock:
        now = asyncio.get_event_loop().time()
        elapsed = now - _last_send_time[chat_id]
        if elapsed < RATE_LIMIT_SLEEP_SEC:
            await asyncio.sleep(RATE_LIMIT_SLEEP_SEC - elapsed)
        _last_send_time[chat_id] = asyncio.get_event_loop().time()


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base = API_BASE.format(token=bot_token)

    async def _send_with_retry(
        self,
        url: str,
        payload: dict,
        max_retries: int = TELEGRAM_429_MAX_RETRIES,
    ) -> dict | None:
        """Telegram API 호출 + 429 retry_after 준수."""
        async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
            for attempt in range(max_retries):
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 429:
                        body = resp.json()
                        retry_after = body.get("parameters", {}).get("retry_after", 5)
                        logger.warning(
                            "telegram_429_throttled",
                            retry_after=retry_after,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(retry_after + TELEGRAM_429_BUFFER_SEC)
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 429:
                        raise
            logger.error(
                "telegram_429_max_retries_exceeded",
                payload_keys=list(payload.keys()),
            )
            return None

    async def send(self, text: str) -> bool:
        """메시지 전송. 성공 시 True."""
        await _enforce_rate_limit(self.chat_id)
        url = f"{self._base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            result = await self._send_with_retry(url, payload)
            if result is None:
                return False
            logger.info("telegram_sent", chat_id=self.chat_id)
            return True
        except Exception as e:
            logger.error("telegram_failed", error=str(e))
            return False

    async def _send_with_markup(self, text: str, reply_markup: dict) -> bool:
        """reply_markup 포함 sendMessage. 실패 시 reply_markup 없이 재시도."""
        await _enforce_rate_limit(self.chat_id)
        url = f"{self._base}/sendMessage"
        payload: dict = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        }
        try:
            async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("telegram_sent_with_markup", chat_id=self.chat_id)
                    return True
                # markup 관련 실패면 markup 없이 재시도
                fallback = {k: v for k, v in payload.items() if k != "reply_markup"}
                resp = await client.post(url, json=fallback)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("telegram_send_with_markup_failed", error=str(e))
            return False

    async def send_card(
        self,
        contest: ContestInfo,
        analysis: ContestAnalysis,
        artifact: Optional[ReportArtifact] = None,
        chat_id: Optional[str] = None,
    ) -> bool:
        """공모전 카드 메시지 전송. views.format_contest_card 사용."""
        target_chat = chat_id or self.chat_id
        await _enforce_rate_limit(target_chat)
        text, reply_markup = views.format_contest_card(contest, analysis, artifact)
        url = f"{self._base}/sendMessage"
        payload: dict = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 429:
                    body = resp.json()
                    retry_after = body.get("parameters", {}).get("retry_after", 5)
                    logger.warning(
                        "telegram_429_throttled",
                        retry_after=retry_after,
                        attempt=1,
                    )
                    await asyncio.sleep(retry_after + TELEGRAM_429_BUFFER_SEC)
                    resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    # HTML parse 실패 시 plain text fallback — parse_mode만 제거, reply_markup 유지
                    fallback_payload = {k: v for k, v in payload.items() if k != "parse_mode"}
                    resp = await client.post(url, json=fallback_payload)
                resp.raise_for_status()
                logger.info("telegram_card_sent", contest_id=contest.id)
                return True
        except Exception as e:
            logger.error("telegram_card_failed", contest_id=contest.id, error=str(e))
            return False

    async def send_digest(
        self,
        contests: list[ContestInfo],
        analyses: list[ContestAnalysis],
        artifacts: list[ReportArtifact],
        alerts: list[str],
        top_n: int = 5,
    ) -> bool:
        """다이제스트 핀 메시지 + ROI 상위 N개 카드 전송."""
        artifact_map = {a.contest_id: a for a in artifacts}
        analysis_map = {a.contest_id: a for a in analyses}

        imminent = sum(1 for c in contests if c.d_day is not None and c.d_day <= 7)
        done_reports = sum(1 for a in artifacts if a.status == "done")

        digest_text = views.format_digest_header(
            total=len(contests),
            imminent=imminent,
            done_reports=done_reports,
            total_reports=len(artifacts),
        )
        webapp_markup = views.build_webapp_keyboard()
        if not await self._send_with_markup(digest_text, webapp_markup):
            return False

        # 마감 임박 핀 메시지
        if imminent:
            pin_text = views.format_deadline_pin(contests, analyses)
            await self.send(pin_text)

        # ROI 상위 N개 카드
        sorted_analyses = sorted(analyses, key=lambda a: a.roi_score, reverse=True)[:top_n]
        for analysis in sorted_analyses:
            contest = next((c for c in contests if c.id == analysis.contest_id), None)
            if contest is None:
                continue
            artifact = artifact_map.get(analysis.contest_id)
            await self.send_card(contest, analysis, artifact)

        return True

    async def send_document(
        self,
        path: str | Path,
        caption: str = "",
        chat_id: Optional[str] = None,
    ) -> bool:
        """PDF 파일 전송. 45MB 초과 시 markdown fallback + 안내 메시지."""
        target_chat = chat_id or self.chat_id
        await _enforce_rate_limit(target_chat)
        path = Path(path)

        if not path.exists():
            logger.error("telegram_document_not_found", path=str(path))
            return False

        if os.path.getsize(path) > _PDF_SIZE_LIMIT:
            md_path = path.with_suffix(".md")
            fallback_note = f"⚠️ PDF 파일이 45MB를 초과하여 마크다운 파일을 첨부합니다.\n{caption}"
            if md_path.exists():
                return await self._send_file(md_path, fallback_note, target_chat)
            # 마크다운도 없으면 텍스트 안내 후 False 반환 (caller에 실패 신호)
            await self.send(fallback_note)
            return False

        return await self._send_file(path, caption, target_chat)

    async def _send_file(
        self,
        path: Path,
        caption: str,
        chat_id: str,
    ) -> bool:
        url = f"{self._base}/sendDocument"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                with open(path, "rb") as f:
                    resp = await client.post(
                        url,
                        data={
                            "chat_id": chat_id,
                            "caption": caption[:1024],
                            "parse_mode": "HTML",
                        },
                        files={"document": (path.name, f, "application/octet-stream")},
                    )
                resp.raise_for_status()
                logger.info("telegram_document_sent", path=str(path))
                return True
        except Exception as e:
            logger.error("telegram_document_failed", path=str(path), error=str(e))
            return False

    async def pin_message(self, text: str) -> bool:
        """메시지를 전송하고 채팅에 핀 고정."""
        await _enforce_rate_limit(self.chat_id)
        url_send = f"{self._base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            result = await self._send_with_retry(url_send, payload)
            if result is None:
                return False
            message_id = result["result"]["message_id"]

            async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
                pin_url = f"{self._base}/pinChatMessage"
                pin_resp = await client.post(
                    pin_url,
                    json={"chat_id": self.chat_id, "message_id": message_id, "disable_notification": True},
                )
                pin_resp.raise_for_status()
                logger.info("telegram_pinned", message_id=message_id)
                return True
        except Exception as e:
            logger.error("telegram_pin_failed", error=str(e))
            return False

    async def edit_message_or_send(
        self,
        text: str,
        message_id: Optional[int] = None,
        chat_id: Optional[str] = None,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """message_id가 있으면 edit 시도, 실패(not found)하면 new message push."""
        target_chat = chat_id or self.chat_id

        if message_id is not None:
            url = f"{self._base}/editMessageText"
            payload: dict = {
                "chat_id": target_chat,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            try:
                async with httpx.AsyncClient(timeout=TELEGRAM_API_TIMEOUT) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        logger.info("telegram_edited", message_id=message_id)
                        return True
                    desc = (resp.json().get("description") or "").lower()
                    if "message to edit not found" in desc:
                        logger.warning("telegram_edit_not_found", message_id=message_id)
                        # fallthrough to send new message
                    else:
                        logger.error("telegram_edit_failed", status=resp.status_code, desc=desc)
                        return False
            except Exception as e:
                logger.error("telegram_edit_failed", error=str(e))

        # new message fallback
        return await self.send(text)

    def format_run_summary(
        self,
        *,
        new_contests: int,
        total_filtered: int,
        new_analyses: int,
        new_reports: list[str],
        alerts: list[str],
    ) -> str:
        """파이프라인 실행 결과 요약 메시지 생성."""
        lines = ["<b>📋 공모전 에이전트 일일 리포트</b>", ""]

        lines.append(f"🔍 신규 수집: {new_contests}건")
        lines.append(f"✅ 필터 통과: {total_filtered}건")
        lines.append(f"🧠 신규 분석: {new_analyses}건")

        if new_reports:
            lines.append(f"\n📄 <b>생성된 보고서 ({len(new_reports)}건)</b>")
            for title in new_reports:
                lines.append(f"  • {title}")

        if alerts:
            lines.append(f"\n⏰ <b>마감 알림 ({len(alerts)}건)</b>")
            for alert in alerts:
                lines.append(f"  • {alert}")

        if not new_contests and not new_analyses and not new_reports:
            lines.append("\n변동 없음 — 새 공모전이 없습니다.")

        return "\n".join(lines)
