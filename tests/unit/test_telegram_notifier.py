"""TelegramNotifier extensions — send_card/digest/document/pin/edit_or_send."""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.notifiers.telegram import TelegramNotifier

BOT_TOKEN = "TEST_TOKEN"
CHAT_ID = "123456"
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _notifier() -> TelegramNotifier:
    return TelegramNotifier(bot_token=BOT_TOKEN, chat_id=CHAT_ID)


def _contest(
    contest_id: str = "ck_test001",
    d_day: Optional[int] = 10,
) -> ContestInfo:
    return ContestInfo(
        id=contest_id,
        platform="contestkorea",
        title="테스트 공모전",
        organizer="테스트 기관",
        deadline="2026-05-01",
        start_date=None,
        d_day=d_day,
        prize="100만원",
        prize_amount=1_000_000,
        url="https://example.com",
        eligibility_raw="제한 없음",
        eligibility_tags=["일반인"],
        submission_format="보고서",
        category="기타",
        description=None,
        status="접수중",
        scraped_at=datetime(2026, 4, 20),
    )


def _analysis(contest_id: str = "ck_test001") -> ContestAnalysis:
    return ContestAnalysis(
        contest_id=contest_id,
        roi_score=7.5,
        difficulty="MEDIUM",
        contest_type="SW개발",
        suggested_approach="접근 전략 1줄",
        is_eligible=True,
        eligibility_reason="해당 없음",
        roi_breakdown={"prize": 3.5, "difficulty": 3.0},
        required_deliverables=[],
        relevant_public_data=[],
        keywords=[],
        ai_restriction=None,
        analyzed_at=datetime(2026, 4, 20),
    )


def _artifact(
    contest_id: str = "ck_test001",
    status: str = "done",
    file_path: str = "/tmp/report.pdf",
) -> ReportArtifact:
    return ReportArtifact(
        contest_id=contest_id,
        report_type="analysis_report",
        file_path=Path(file_path),
        markdown_path=Path("/tmp/report.md"),
        title="테스트 보고서",
        sections=[],
        data_sources=[],
        visualizations=[],
        word_count=5000,
        generated_at=datetime(2026, 4, 20),
        generation_duration_sec=30.0,
        status=status,
    )


# ---------------------------------------------------------------------------
# send_card
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_card_basic(httpx_mock):
    """send_card가 sendMessage를 한 번 호출한다."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 1}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_card(_contest(), _analysis())
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "sendMessage" in str(requests[0].url)


@pytest.mark.asyncio
async def test_send_card_with_artifact_includes_keyboard(httpx_mock):
    """done artifact가 있으면 reply_markup(inline_keyboard)이 payload에 포함된다."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 2}},
    )
    notifier = _notifier()
    artifact = _artifact(status="done")
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_card(_contest(), _analysis(), artifact)
    assert result is True
    import json
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert "reply_markup" in body
    keyboard = body["reply_markup"]["inline_keyboard"]
    # PDF/가이드 버튼 행에만 callback_data가 있음 (원문 버튼은 url 키 사용)
    cb_data_values = [btn["callback_data"] for row in keyboard for btn in row if "callback_data" in btn]
    assert any(v.startswith("pdf:") for v in cb_data_values)


@pytest.mark.asyncio
async def test_send_card_html_failure_falls_back_to_plain(httpx_mock):
    """첫 sendMessage가 실패하면 plain text로 재시도한다."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        status_code=400,
        json={"ok": False, "description": "Bad Request: can't parse entities"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 3}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_card(_contest(), _analysis())
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_send_card_html_fallback_preserves_reply_markup(httpx_mock):
    """HTML fallback 재시도 시 reply_markup이 유지된다."""
    import json as _json
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        status_code=400,
        json={"ok": False, "description": "Bad Request: can't parse entities"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 3}},
    )
    notifier = _notifier()
    artifact = _artifact(status="done")
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_card(_contest(), _analysis(), artifact)
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    # 두 번째 요청(fallback)에 reply_markup 포함 확인
    fallback_body = _json.loads(requests[1].content)
    assert "reply_markup" in fallback_body
    # parse_mode는 제거되어야 함
    assert "parse_mode" not in fallback_body


# ---------------------------------------------------------------------------
# send_document — R10 AC4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_document_small_pdf(httpx_mock, tmp_path):
    """45MB 미만 PDF는 sendDocument로 전송된다."""
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF small")
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendDocument",
        json={"ok": True, "result": {"message_id": 4}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_document(pdf, caption="테스트 PDF")
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "sendDocument" in str(requests[0].url)


@pytest.mark.asyncio
async def test_send_document_large_pdf_markdown_fallback(httpx_mock, tmp_path, monkeypatch):
    """45MB 초과 PDF는 markdown 파일로 fallback 전송된다."""
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF large")
    md = tmp_path / "report.md"
    md.write_text("# 마크다운 보고서")

    monkeypatch.setattr(os.path, "getsize", lambda p: 50 * 1024 * 1024)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendDocument",
        json={"ok": True, "result": {"message_id": 5}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_document(pdf, caption="큰 파일")
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "sendDocument" in str(requests[0].url)


@pytest.mark.asyncio
async def test_send_document_large_pdf_no_markdown_sends_text(httpx_mock, tmp_path, monkeypatch):
    """45MB 초과 PDF + markdown 없음 → sendMessage 안내 텍스트 + False 반환 (caller에 실패 신호)."""
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF large")

    monkeypatch.setattr(os.path, "getsize", lambda p: 50 * 1024 * 1024)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 6}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_document(pdf, caption="큰 파일")
    assert result is False  # 파일 전송 실패 신호 (안내 텍스트만 발송)
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "sendMessage" in str(requests[0].url)


# ---------------------------------------------------------------------------
# pin_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pin_message_sends_then_pins(httpx_mock):
    """pin_message는 sendMessage 후 pinChatMessage를 호출한다."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 10}},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/pinChatMessage",
        json={"ok": True, "result": True},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.pin_message("핀 메시지")
    assert result is True
    urls = [str(r.url) for r in httpx_mock.get_requests()]
    assert any("sendMessage" in u for u in urls)
    assert any("pinChatMessage" in u for u in urls)


# ---------------------------------------------------------------------------
# edit_message_or_send — R9 AC6
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_message_or_send_success(httpx_mock):
    """message_id가 유효하면 editMessageText 호출."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/editMessageText",
        json={"ok": True, "result": {"message_id": 42}},
    )
    notifier = _notifier()
    result = await notifier.edit_message_or_send("업데이트", message_id=42)
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "editMessageText" in str(requests[0].url)


@pytest.mark.asyncio
async def test_edit_message_or_send_not_found_falls_back(httpx_mock):
    """editMessageText가 400 + message to edit not found → sendMessage fallback."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/editMessageText",
        status_code=400,
        json={"ok": False, "error_code": 400, "description": "Bad Request: message to edit not found"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 99}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.edit_message_or_send("새 메시지", message_id=9999)
    assert result is True
    urls = [str(r.url) for r in httpx_mock.get_requests()]
    assert any("editMessageText" in u for u in urls)
    assert any("sendMessage" in u for u in urls)


@pytest.mark.asyncio
async def test_edit_message_or_send_no_message_id(httpx_mock):
    """message_id None이면 바로 sendMessage."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 100}},
    )
    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.edit_message_or_send("신규 메시지")
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert "sendMessage" in str(requests[0].url)


@pytest.mark.asyncio
async def test_edit_message_or_send_not_modified_does_not_fallback(httpx_mock):
    """editMessageText 400 + 'message is not modified' → sendMessage 호출 없이 False 반환."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/editMessageText",
        status_code=400,
        json={"ok": False, "error_code": 400, "description": "Bad Request: message is not modified"},
    )
    notifier = _notifier()
    result = await notifier.edit_message_or_send("동일 내용", message_id=42)
    assert result is False
    urls = [str(r.url) for r in httpx_mock.get_requests()]
    assert not any("sendMessage" in u for u in urls)


# ---------------------------------------------------------------------------
# 429 retry_after 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_retry_429_then_200(httpx_mock):
    """429 응답 1회 → retry 후 200 → 성공 (sleep retry_after + 0.5 호출)."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        status_code=429,
        json={"ok": False, "parameters": {"retry_after": 3}},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 1}},
    )
    notifier = _notifier()
    sleep_calls = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)

    url = f"{BASE}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": "hello"}

    with patch("asyncio.sleep", side_effect=_fake_sleep):
        result = await notifier._send_with_retry(url, payload)

    assert result is not None
    assert result["ok"] is True
    # retry_after=3 + buffer=0.5 = 3.5초 sleep 호출
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(3.5)


@pytest.mark.asyncio
async def test_send_with_retry_429_max_retries_exceeded(httpx_mock):
    """429 응답 max_retries 초과 → None 반환."""
    for _ in range(3):
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE}/sendMessage",
            status_code=429,
            json={"ok": False, "parameters": {"retry_after": 1}},
        )
    notifier = _notifier()

    url = f"{BASE}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": "hello"}

    with patch("asyncio.sleep"):
        result = await notifier._send_with_retry(url, payload, max_retries=3)

    assert result is None


# ---------------------------------------------------------------------------
# _enforce_rate_limit 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enforce_rate_limit_same_chat_id_waits():
    """같은 chat_id 연속 호출 시 두 번째는 RATE_LIMIT_SLEEP_SEC 미만이면 대기."""
    import src.notifiers.telegram as tg_module
    from src.notifiers.telegram import RATE_LIMIT_SLEEP_SEC

    # 상태 초기화
    tg_module._last_send_time.clear()
    tg_module._send_locks.clear()

    sleep_calls = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)

    chat_id = "test_chat_001"
    # 첫 번째 호출 — _last_send_time[chat_id]=0.0, now=5.0 → elapsed=5.0 >= 1.1 → no sleep
    # 두 번째 호출 — _last_send_time[chat_id]=5.0, now=5.3 → elapsed=0.3 < 1.1 → sleep(0.8)
    time_values = iter([5.0, 5.0, 5.3, 6.1])

    with patch("asyncio.sleep", side_effect=_fake_sleep):
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.side_effect = time_values
            await tg_module._enforce_rate_limit(chat_id)
            await tg_module._enforce_rate_limit(chat_id)

    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(RATE_LIMIT_SLEEP_SEC - 0.3, abs=0.05)


@pytest.mark.asyncio
async def test_enforce_rate_limit_different_chat_ids_independent():
    """다른 chat_id는 서로 독립적인 rate limiter를 가진다."""
    import src.notifiers.telegram as tg_module

    tg_module._last_send_time.clear()
    tg_module._send_locks.clear()

    sleep_calls = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)

    # chat_a, chat_b 각각 첫 호출: _last_send_time 초기값 0.0, now=100.0 → elapsed=100.0 >= 1.1 → no sleep
    with patch("asyncio.sleep", side_effect=_fake_sleep):
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 100.0
            await tg_module._enforce_rate_limit("chat_a")
            await tg_module._enforce_rate_limit("chat_b")

    # 두 chat_id 모두 첫 호출이므로 sleep 없음
    assert len(sleep_calls) == 0


# ---------------------------------------------------------------------------
# send_digest — rate limiter 통합
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_digest_no_direct_sleep():
    """send_digest는 직접 asyncio.sleep을 호출하지 않는다 (rate limit은 각 send_* 내부에서 처리)."""
    from unittest.mock import AsyncMock

    contests = [_contest(f"c{i}", d_day=2) for i in range(3)]
    analyses = [_analysis(f"c{i}") for i in range(3)]
    top_n = 3

    notifier = _notifier()
    sleep_calls = []

    async def _fake_sleep(secs):
        sleep_calls.append(secs)

    with patch("src.notifiers.telegram.TelegramNotifier._send_with_markup", new_callable=AsyncMock, return_value=True), \
         patch("src.notifiers.telegram.TelegramNotifier.send", new_callable=AsyncMock, return_value=True), \
         patch("src.notifiers.telegram.TelegramNotifier.send_card", new_callable=AsyncMock, return_value=True), \
         patch("asyncio.sleep", side_effect=_fake_sleep):
        await notifier.send_digest(contests, analyses, [], [], top_n=top_n)

    # send_digest 자체는 asyncio.sleep을 직접 호출하지 않음
    assert len(sleep_calls) == 0


@pytest.mark.asyncio
async def test_send_digest_calls_expected_endpoints(httpx_mock):
    """send_digest는 digest 헤더 + 핀 메시지 + N개 카드를 전송한다."""
    # digest header + pin + 2 cards = 4 sendMessage calls
    for _ in range(4):
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE}/sendMessage",
            json={"ok": True, "result": {"message_id": 1}},
        )
    contests = [_contest("c1", d_day=2), _contest("c2", d_day=5)]
    analyses = [_analysis("c1"), _analysis("c2")]
    artifacts = [_artifact("c1", status="done")]

    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_digest(contests, analyses, artifacts, [], top_n=2)
    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) >= 3  # 최소 digest + 카드 2개


# ---------------------------------------------------------------------------
# send_digest — webapp 버튼 통합 (T4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_digest_header_includes_webapp_button():
    """send_digest가 _send_with_markup에 web_app 버튼 markup을 전달한다."""
    from unittest.mock import AsyncMock, call
    from src.notifiers import views

    contests = [_contest("c1", d_day=10)]
    analyses = [_analysis("c1")]

    notifier = _notifier()
    with patch("src.notifiers.telegram.TelegramNotifier._send_with_markup", new_callable=AsyncMock, return_value=True) as mock_markup, \
         patch("src.notifiers.telegram.TelegramNotifier.send", new_callable=AsyncMock, return_value=True), \
         patch("src.notifiers.telegram.TelegramNotifier.send_card", new_callable=AsyncMock, return_value=True), \
         patch("src.notifiers.telegram._enforce_rate_limit"):
        await notifier.send_digest(contests, analyses, [], [], top_n=1)

    # _send_with_markup이 1회 호출됐고, markup에 web_app 버튼 포함
    assert mock_markup.call_count == 1
    _, markup_arg = mock_markup.call_args[0]
    keyboard = markup_arg["inline_keyboard"]
    flat = [btn for row in keyboard for btn in row]
    webapp_btns = [btn for btn in flat if "web_app" in btn]
    assert len(webapp_btns) == 1
    assert webapp_btns[0]["text"] == "📊 대시보드 열기"
    assert webapp_btns[0]["web_app"]["url"].startswith("http")


@pytest.mark.asyncio
async def test_send_digest_header_webapp_button_fallback_on_markup_failure(httpx_mock):
    """헤더 전송 시 markup 포함 요청이 실패하면 markup 없이 재시도한다."""
    import json as _json
    # 첫 요청(markup 포함) 실패, 두 번째(markup 없이) 성공, 이후 카드 1개
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        status_code=400,
        json={"ok": False, "description": "Bad Request: button_type invalid"},
    )
    # fallback (no markup) 성공
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 1}},
    )
    # send_card 호출 (1개 카드)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/sendMessage",
        json={"ok": True, "result": {"message_id": 2}},
    )
    contests = [_contest("c1", d_day=10)]
    analyses = [_analysis("c1")]

    notifier = _notifier()
    with patch("src.notifiers.telegram._enforce_rate_limit"):
        result = await notifier.send_digest(contests, analyses, [], [], top_n=1)
    assert result is True
    reqs = httpx_mock.get_requests()
    # 첫 시도(markup) + fallback(no markup) 포함 2+ 요청
    assert len(reqs) >= 2
    # fallback 요청에 reply_markup 없음
    fallback_body = _json.loads(reqs[1].content)
    assert "reply_markup" not in fallback_body
