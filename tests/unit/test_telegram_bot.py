"""Unit tests for web_app_data handling in TelegramBot."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


def make_bot():
    with patch("src.bot.telegram_bot.JSONStorage"), \
         patch("src.bot.telegram_bot.ClaudeCLI"), \
         patch("src.bot.telegram_bot.ContestAgent"):
        from src.bot.telegram_bot import TelegramBot
        bot = TelegramBot(bot_token="fake_token", allowed_chat_id="111")
        bot._send = AsyncMock()
        bot._send_typing = AsyncMock()
        return bot


@pytest.mark.asyncio
class TestHandleWebAppData:
    async def test_dispatches_valid_payload(self):
        bot = make_bot()
        raw = json.dumps({"action": "pdf", "contest_id": "ck_001"})
        message = {"chat": {"id": "111"}, "web_app_data": {"data": raw}}
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_web_app_data(message)
            mock_dispatch.assert_awaited_once_with(bot, "111", {"action": "pdf", "contest_id": "ck_001"})

    async def test_handles_invalid_json(self):
        bot = make_bot()
        message = {"chat": {"id": "111"}, "web_app_data": {"data": "not json"}}
        await bot._handle_web_app_data(message)
        bot._send.assert_awaited_once()
        assert "읽을 수 없습니다" in bot._send.call_args[0][1]

    async def test_handles_missing_data_field(self):
        bot = make_bot()
        message = {"chat": {"id": "111"}, "web_app_data": {}}
        await bot._handle_web_app_data(message)
        bot._send.assert_awaited_once()


@pytest.mark.asyncio
class TestHandleMessageWebAppData:
    async def test_web_app_data_takes_priority(self):
        bot = make_bot()
        raw = json.dumps({"action": "guide", "contest_id": "wv_abc"})
        message = {
            "chat": {"id": "111"},
            "from": {"id": "111"},
            "text": "some text",
            "web_app_data": {"data": raw},
        }
        with patch.object(bot, "_handle_web_app_data", new_callable=AsyncMock) as mock_wa:
            await bot._handle_message(message)
            mock_wa.assert_awaited_once_with(message)

    async def test_web_app_data_blocked_for_unauthorized_chat(self):
        bot = make_bot()
        raw = json.dumps({"action": "pdf", "contest_id": "ck_001"})
        message = {
            "chat": {"id": "999"},
            "from": {"id": "999"},
            "web_app_data": {"data": raw},
        }
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_message(message)
            mock_dispatch.assert_not_awaited()
        bot._send.assert_awaited_once()
        assert "접근 권한" in bot._send.call_args[0][1]

    async def test_normal_text_still_works(self):
        bot = make_bot()
        message = {"chat": {"id": "111"}, "from": {"id": "111"}, "text": "/start"}
        await bot._handle_message(message)
        bot._send.assert_awaited_once()
        assert "공모전 에이전트" in bot._send.call_args[0][1]

    async def test_empty_message_ignored(self):
        bot = make_bot()
        message = {"chat": {"id": "111"}, "from": {"id": "111"}, "text": ""}
        await bot._handle_message(message)
        bot._send.assert_not_awaited()

    async def test_from_id_mismatch_blocked(self):
        """Fix 4: user.id가 allowed_chat_id와 다르면 거부."""
        bot = make_bot()
        # chat_id matches but from.id (user) is a different member
        message = {"chat": {"id": "111"}, "from": {"id": "999"}, "text": "안녕"}
        await bot._handle_message(message)
        bot._send.assert_awaited_once()
        assert "접근 권한" in bot._send.call_args[0][1]


@pytest.mark.asyncio
class TestHandleCallbackQuery:
    def _make_cq(self, chat_id="111", user_id="111", data="pdf:ck_001", cq_id="cq1"):
        return {
            "id": cq_id,
            "message": {"chat": {"id": chat_id}},
            "from": {"id": user_id},
            "data": data,
        }

    async def test_pdf_scenario(self):
        """Fix 2: pdf 콜백 정상 처리."""
        bot = make_bot()
        bot._api = AsyncMock(return_value={})
        cq = self._make_cq(data="pdf:ck_001")
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_callback_query(cq)
        # answerCallbackQuery called
        bot._api.assert_awaited_once()
        call_args = bot._api.call_args
        assert call_args[0][0] == "answerCallbackQuery"
        # dispatch called with pdf action
        mock_dispatch.assert_awaited_once()
        _, call_chat_id, payload = mock_dispatch.call_args[0]
        assert call_chat_id == "111"
        assert payload["action"] == "pdf"
        assert payload["contest_id"] == "ck_001"

    async def test_invalid_user_id_rejected(self):
        """Fix 4: user.id 불일치 시 권한 없음 + dispatch 미호출."""
        bot = make_bot()
        bot._api = AsyncMock(return_value={})
        cq = self._make_cq(chat_id="111", user_id="999", data="pdf:ck_001")
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_callback_query(cq)
        # dispatch not called
        mock_dispatch.assert_not_awaited()
        # answer with rejection text
        bot._api.assert_awaited_once()
        kwargs = bot._api.call_args[1]
        assert "권한" in kwargs.get("text", "")

    async def test_invalid_callback_data_silent(self):
        """Fix 2: callback_data 파싱 실패 시 silent (no dispatch, no error)."""
        bot = make_bot()
        bot._api = AsyncMock(return_value={})
        cq = self._make_cq(data="no_colon_here")
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_callback_query(cq)
        mock_dispatch.assert_not_awaited()

    async def test_unknown_action_prefix_silent(self):
        """Fix 2: 알 수 없는 action prefix → silent."""
        bot = make_bot()
        bot._api = AsyncMock(return_value={})
        cq = self._make_cq(data="unknown:ck_001")
        with patch("src.bot.callbacks.dispatch_action", new_callable=AsyncMock) as mock_dispatch:
            await bot._handle_callback_query(cq)
        mock_dispatch.assert_not_awaited()


class TestClaudeCLIInstances:
    """R-A6: TelegramBot이 agent_claude / gen_claude / claude 3개 attribute를 올바르게 노출하는지."""

    def test_has_three_claude_attributes(self):
        bot = make_bot()
        assert hasattr(bot, "agent_claude"), "agent_claude 없음"
        assert hasattr(bot, "gen_claude"), "gen_claude 없음"
        assert hasattr(bot, "claude"), "claude alias 없음"

    def test_claude_is_alias_of_agent_claude(self):
        bot = make_bot()
        assert bot.claude is bot.agent_claude, "bot.claude가 agent_claude의 alias가 아님"

    def test_semaphore_limits(self):
        """ClaudeCLI mock의 call_args로 semaphore_limit 값 검증."""
        with patch("src.bot.telegram_bot.JSONStorage"), \
             patch("src.bot.telegram_bot.ContestAgent"):
            # ClaudeCLI를 실제로 생성하되 subprocess만 막음
            from src.bot.telegram_bot import TelegramBot
            bot = TelegramBot(bot_token="fake", allowed_chat_id="111")
        assert bot.agent_claude.semaphore_limit == 1, "agent_claude semaphore_limit != 1"
        assert bot.gen_claude.semaphore_limit == 2, "gen_claude semaphore_limit != 2"


@pytest.mark.asyncio
class TestCheckOrphanedRunning:
    """R-A4: _check_orphaned_running 동작 검증."""

    async def test_orphan_found_sends_message_and_marks_failed(self):
        """status=running 1건 → _send 호출 + artifact가 failed로 변경."""
        bot = make_bot()
        bot._send = AsyncMock()

        orphan = MagicMock()
        orphan.status = "running"
        orphan.contest_id = "ck_001"

        contest = MagicMock()
        contest.title = "테스트 공모전"

        mock_storage = MagicMock()
        mock_storage.load_artifacts.return_value = [orphan]
        mock_storage.get_contest.return_value = contest

        with patch("src.bot.telegram_bot.JSONStorage", return_value=mock_storage):
            await bot._check_orphaned_running()

        bot._send.assert_awaited_once()
        sent_text = bot._send.call_args[0][1]
        assert "미완 보고서" in sent_text
        assert "테스트 공모전" in sent_text
        assert orphan.status == "failed", "artifact status가 failed로 변경되지 않음"
        mock_storage.save_artifact.assert_called_once_with(orphan)

    async def test_no_orphan_send_not_called(self):
        """orphans 0건 → _send 미호출."""
        bot = make_bot()
        bot._send = AsyncMock()

        mock_storage = MagicMock()
        mock_storage.load_artifacts.return_value = []

        with patch("src.bot.telegram_bot.JSONStorage", return_value=mock_storage):
            await bot._check_orphaned_running()

        bot._send.assert_not_awaited()
