"""Unit tests for src/bot/callbacks.py."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.callbacks import (
    validate_contest_id,
    parse_web_app_data,
    dispatch_action,
    handle_pdf,
    handle_generate,
    handle_guide,
    _run_generate,
    _in_flight,
)


# ── validate_contest_id ────────────────────────────────────────────────────

class TestValidateContestId:
    def test_valid_ck_prefix(self):
        assert validate_contest_id("ck_202603180064") is True

    def test_valid_wv_prefix(self):
        assert validate_contest_id("wv_abc123") is True

    def test_rejects_unknown_prefix(self):
        assert validate_contest_id("xx_abc123") is False

    def test_rejects_no_prefix(self):
        assert validate_contest_id("abc123") is False

    def test_rejects_empty(self):
        assert validate_contest_id("") is False

    def test_rejects_non_string(self):
        assert validate_contest_id(None) is False  # type: ignore
        assert validate_contest_id(123) is False    # type: ignore

    def test_rejects_special_chars(self):
        assert validate_contest_id("ck_abc/../../etc") is False

    def test_rejects_too_long(self):
        assert validate_contest_id("ck_" + "a" * 62) is False

    def test_accepts_max_length(self):
        # prefix "ck_" = 3, remaining = 61 → total 64
        assert validate_contest_id("ck_" + "a" * 61) is True

    def test_rejects_spaces(self):
        assert validate_contest_id("ck_ abc") is False


# ── parse_web_app_data ─────────────────────────────────────────────────────

class TestParseWebAppData:
    def test_valid_json(self):
        raw = json.dumps({"action": "pdf", "contest_id": "ck_001"})
        result = parse_web_app_data(raw)
        assert result == {"action": "pdf", "contest_id": "ck_001"}

    def test_invalid_json(self):
        assert parse_web_app_data("not json") is None

    def test_non_dict_json(self):
        assert parse_web_app_data("[1,2,3]") is None

    def test_empty_string(self):
        assert parse_web_app_data("") is None


# ── dispatch_action ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDispatchAction:
    async def test_routes_pdf(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        with patch("src.bot.callbacks.handle_pdf", new_callable=AsyncMock) as mock_pdf:
            await dispatch_action(bot, "123", {"action": "pdf", "contest_id": "ck_001"})
            mock_pdf.assert_awaited_once_with(bot, "123", "ck_001")

    async def test_routes_generate(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        with patch("src.bot.callbacks.handle_generate", new_callable=AsyncMock) as mock_gen:
            await dispatch_action(bot, "123", {"action": "generate", "contest_id": "ck_001"})
            mock_gen.assert_awaited_once_with(bot, "123", "ck_001")

    async def test_routes_guide(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        with patch("src.bot.callbacks.handle_guide", new_callable=AsyncMock) as mock_guide:
            await dispatch_action(bot, "123", {"action": "guide", "contest_id": "ck_001"})
            mock_guide.assert_awaited_once_with(bot, "123", "ck_001")

    async def test_rejects_invalid_id(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        await dispatch_action(bot, "123", {"action": "pdf", "contest_id": "INVALID"})
        bot._send.assert_awaited_once()
        assert "잘못된" in bot._send.call_args[0][1]

    async def test_unknown_action(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        await dispatch_action(bot, "123", {"action": "noop", "contest_id": "ck_001"})
        bot._send.assert_awaited_once()


# ── handle_pdf ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHandlePdf:
    async def test_no_artifact(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_artifact.return_value = None
        mock_storage.get_contest.return_value = MagicMock(title="테스트 공모전")
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_pdf(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "보고서가 아직" in msg

    async def test_artifact_not_done(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_artifact.return_value = MagicMock(status="pending", path=None)
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_pdf(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "보고서가 아직" in msg

    async def test_artifact_file_missing(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_artifact.return_value = MagicMock(status="done", path="/nonexistent/file.pdf")
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_pdf(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "찾을 수 없습니다" in msg


# ── handle_generate ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHandleGenerate:
    async def test_contest_not_found(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = None
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_generate(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "찾을 수 없습니다" in msg

    async def test_already_done(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_artifact.return_value = MagicMock(status="done")
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_generate(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "이미 생성" in msg

    async def test_triggers_background_task(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_artifact.return_value = None
        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.bot.callbacks.asyncio.create_task") as mock_task:
            await handle_generate(bot, "123", "ck_001")
        assert bot._send.await_count == 1
        assert "생성 중" in bot._send.call_args[0][1]
        mock_task.assert_called_once()

    async def test_duplicate_click_blocked(self):
        """R-A6: 같은 chat_id+contest_id 동시 클릭 시 '이미 생성 중' 메시지"""
        import src.bot.callbacks as cb_module
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_artifact.return_value = None

        # in_flight에 미리 추가해서 중복 상태 시뮬레이션
        cb_module._in_flight["123"] = {"ck_001"}
        try:
            with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
                 patch("src.bot.callbacks.asyncio.create_task") as mock_task:
                await handle_generate(bot, "123", "ck_001")
            msg = bot._send.call_args[0][1]
            assert "이미 생성 중" in msg
            mock_task.assert_not_called()
        finally:
            cb_module._in_flight.pop("123", None)


# ── handle_guide ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHandleGuide:
    async def test_contest_not_found(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = None
        mock_storage.get_analysis.return_value = None
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_guide(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "찾을 수 없습니다" in msg

    async def test_analysis_not_found(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="공모전명")
        mock_storage.get_analysis.return_value = None
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_guide(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "분석 정보가 없습니다" in msg

    async def test_sends_guide_with_suggested_approach(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(
            title="공모전명", deadline=None, d_day=3
        )
        analysis = MagicMock()
        analysis.suggested_approach = "접근전략 설명"
        analysis.required_deliverables = ["보고서", "발표자료"]
        analysis.relevant_public_data = ["공공데이터A"]
        mock_storage.get_analysis.return_value = analysis
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_guide(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "공모전명" in msg
        assert "접근전략 설명" in msg
        assert "보고서" in msg
        assert "공공데이터A" in msg

    async def test_sends_guide_without_deliverables(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(
            title="공모전명", deadline=None, d_day=None
        )
        analysis = MagicMock()
        analysis.suggested_approach = "전략"
        analysis.required_deliverables = []
        analysis.relevant_public_data = []
        mock_storage.get_analysis.return_value = analysis
        with patch("src.core.storage.JSONStorage", return_value=mock_storage):
            await handle_guide(bot, "123", "ck_001")
        msg = bot._send.call_args[0][1]
        assert "전략" in msg


# ── _run_generate (ReportGenerator 진짜 호출) ─────────────────────────────

@pytest.mark.asyncio
class TestRunGenerate:
    async def test_success_calls_report_generator(self):
        """generate() 호출 → status done 마킹 → send_document 전송."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.bot_token = "TOKEN"
        bot.gen_claude = MagicMock()
        bot.claude = None

        mock_artifact = MagicMock()
        mock_artifact.word_count = 1234
        mock_artifact.file_path = Path("/tmp/report.pdf")
        mock_artifact.status = "done"

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_analysis.return_value = MagicMock()
        mock_storage.get_artifact.return_value = None

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_artifact)

        mock_notifier = MagicMock()
        mock_notifier.send_document = AsyncMock(return_value=True)

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator), \
             patch("src.notifiers.telegram.TelegramNotifier", return_value=mock_notifier):
            await _run_generate(bot, "123", "ck_001", "테스트")

        mock_generator.generate.assert_awaited_once()
        assert mock_artifact.status == "done"
        mock_storage.save_artifact.assert_called()
        mock_notifier.send_document.assert_awaited_once()

    async def test_running_status_marked_before_generate(self):
        """기존 artifact가 있으면 generate 전 status='running' 마킹."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.bot_token = "TOKEN"
        bot.gen_claude = MagicMock()

        existing_artifact = MagicMock()
        existing_artifact.status = "pending"

        mock_artifact = MagicMock()
        mock_artifact.word_count = 500
        mock_artifact.file_path = Path("/tmp/report.pdf")
        mock_artifact.status = "done"

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_analysis.return_value = MagicMock()
        mock_storage.get_artifact.return_value = existing_artifact

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_artifact)

        mock_notifier = MagicMock()
        mock_notifier.send_document = AsyncMock(return_value=True)

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator), \
             patch("src.notifiers.telegram.TelegramNotifier", return_value=mock_notifier):
            await _run_generate(bot, "123", "ck_001", "테스트")

        # running 마킹 후 save_artifact 호출됐는지 확인
        assert existing_artifact.status == "running"
        assert mock_storage.save_artifact.call_count >= 2  # running + done 각 1회

    async def test_generate_failure_marks_status_failed(self):
        """generate()가 예외 발생 시 status='failed' 마킹 + 예외 전파."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.bot_token = "TOKEN"
        bot.gen_claude = MagicMock()

        existing_artifact = MagicMock()
        existing_artifact.status = "running"

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_analysis.return_value = MagicMock()
        mock_storage.get_artifact.return_value = existing_artifact

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("생성 오류"))

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator):
            with pytest.raises(RuntimeError, match="생성 오류"):
                await _run_generate(bot, "123", "ck_001", "테스트")

        assert existing_artifact.status == "failed"
        mock_storage.save_artifact.assert_called()

    async def test_generate_failure_no_existing_artifact_creates_stub(self):
        """기존 artifact 없을 때 generate() 실패 → stub ReportArtifact 저장."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.bot_token = "TOKEN"
        bot.gen_claude = MagicMock()

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_analysis.return_value = MagicMock()
        mock_storage.get_artifact.return_value = None

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("오류"))

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator):
            with pytest.raises(RuntimeError):
                await _run_generate(bot, "123", "ck_001", "테스트")

        # stub artifact save 호출 확인
        mock_storage.save_artifact.assert_called_once()
        saved = mock_storage.save_artifact.call_args[0][0]
        assert saved.status == "failed"
        assert saved.contest_id == "ck_001"

    async def test_no_contest_or_analysis_sends_error(self):
        """contest 또는 analysis 없으면 오류 메시지 + generate 미호출."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.gen_claude = MagicMock()

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = None
        mock_storage.get_analysis.return_value = None

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock()

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator):
            await _run_generate(bot, "123", "ck_001", "테스트")

        bot._send.assert_awaited_once()
        assert "없습니다" in bot._send.call_args[0][1]
        mock_generator.generate.assert_not_awaited()

    async def test_fallback_to_bot_claude_when_no_gen_claude(self):
        """gen_claude 없으면 bot.claude fallback 사용."""
        bot = MagicMock()
        bot._send = AsyncMock()
        bot.bot_token = "TOKEN"
        del bot.gen_claude  # gen_claude 속성 없음
        bot.claude = MagicMock()

        mock_artifact = MagicMock()
        mock_artifact.word_count = 100
        mock_artifact.file_path = Path("/tmp/report.pdf")
        mock_artifact.status = "done"

        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_analysis.return_value = MagicMock()
        mock_storage.get_artifact.return_value = None

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=mock_artifact)

        mock_notifier = MagicMock()
        mock_notifier.send_document = AsyncMock(return_value=True)

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.generators.report_generator.ReportGenerator", return_value=mock_generator) as mock_rg_cls, \
             patch("src.notifiers.telegram.TelegramNotifier", return_value=mock_notifier):
            await _run_generate(bot, "123", "ck_001", "테스트")

        # ReportGenerator가 bot.claude로 초기화됐는지 확인
        mock_rg_cls.assert_called_once_with(claude_cli=bot.claude)
        mock_generator.generate.assert_awaited_once()


# ── handle_generate timeout ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestHandleGenerateTimeout:
    async def test_timeout_sends_message(self):
        bot = MagicMock()
        bot._send = AsyncMock()
        mock_storage = MagicMock()
        mock_storage.get_contest.return_value = MagicMock(title="테스트")
        mock_storage.get_artifact.return_value = None

        async def raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("src.core.storage.JSONStorage", return_value=mock_storage), \
             patch("src.bot.callbacks.asyncio.wait_for", side_effect=raise_timeout), \
             patch("src.bot.callbacks.asyncio.create_task") as mock_task:
            # Capture the coroutine passed to create_task and run it
            captured = {}
            def fake_create_task(coro):
                captured["coro"] = coro
                return MagicMock(add_done_callback=MagicMock())
            mock_task.side_effect = fake_create_task
            await handle_generate(bot, "123", "ck_001")
            # Run the captured coroutine to trigger timeout path
            if "coro" in captured:
                await captured["coro"]

        # At least the ack was sent
        assert bot._send.await_count >= 1
        # Check timeout message was sent
        calls = [call[0][1] for call in bot._send.call_args_list]
        assert any("시간 초과" in c for c in calls)
