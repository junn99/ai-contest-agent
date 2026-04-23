"""Phase 0 spike — R9~R12 검증 (pytest-httpx mock + asyncio.create_task ack 패턴)."""
import asyncio
import os
import json
import pytest
import httpx
from pytest_httpx import HTTPXMock


# ---------------------------------------------------------------------------
# R12 spike: pytest-httpx import + 기본 mock 동작
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r12_pytest_httpx_basic(httpx_mock: HTTPXMock):
    """R12: pytest-httpx로 Telegram sendMessage를 mock할 수 있다."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.telegram.org/botTEST_TOKEN/sendMessage",
        json={"ok": True, "result": {"message_id": 1}},
    )
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.telegram.org/botTEST_TOKEN/sendMessage",
            json={"chat_id": "123", "text": "hello"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# R9 spike: editMessageText 400 + "message to edit not found" 재현
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r9_edit_message_not_found(httpx_mock: HTTPXMock):
    """R9: Telegram이 400 + message_to_edit_not_found 반환 시 재현 가능."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.telegram.org/botTEST_TOKEN/editMessageText",
        status_code=400,
        json={
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: message to edit not found",
        },
    )
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.telegram.org/botTEST_TOKEN/editMessageText",
            json={"chat_id": "123", "message_id": 9999, "text": "updated"},
        )
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert "message to edit not found" in data["description"]


# ---------------------------------------------------------------------------
# R11 spike: answerCallbackQuery ≤2초 ack + asyncio.create_task 분리 패턴
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r11_immediate_ack_then_slow_task(httpx_mock: HTTPXMock):
    """R11: answerCallbackQuery를 즉시 호출하고 본 작업은 create_task로 분리."""
    ack_called_at: list[float] = []
    task_done_at: list[float] = []

    httpx_mock.add_response(
        method="POST",
        url="https://api.telegram.org/botTEST_TOKEN/answerCallbackQuery",
        json={"ok": True, "result": True},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.telegram.org/botTEST_TOKEN/sendDocument",
        json={"ok": True, "result": {"message_id": 2}},
    )

    async def slow_send_document():
        await asyncio.sleep(0.05)  # simulate short delay
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.telegram.org/botTEST_TOKEN/sendDocument",
                json={"chat_id": "123", "document": "file_id"},
            )
        task_done_at.append(asyncio.get_event_loop().time())

    async def dispatch_callback():
        # 즉시 ack
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.telegram.org/botTEST_TOKEN/answerCallbackQuery",
                json={"callback_query_id": "cq123"},
            )
        ack_called_at.append(asyncio.get_event_loop().time())
        # 본 작업은 별도 task
        asyncio.create_task(slow_send_document())

    start = asyncio.get_event_loop().time()
    await dispatch_callback()
    ack_elapsed = ack_called_at[0] - start
    # ack은 2초 미만이어야 함
    assert ack_elapsed < 2.0, f"ack took {ack_elapsed:.3f}s"
    # task가 완료될 때까지 잠깐 대기
    await asyncio.sleep(0.1)
    assert len(task_done_at) == 1


# ---------------------------------------------------------------------------
# R10 spike: 45MB 초과 판정 로직 (os.path.getsize mock)
# ---------------------------------------------------------------------------

def test_r10_pdf_size_check(tmp_path, monkeypatch):
    """R10: 45MB 초과 시 markdown fallback, 이하면 PDF 첨부."""
    LIMIT = 45 * 1024 * 1024  # 45MB

    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"")  # empty placeholder

    # 실제 프로젝트 PDF는 ~74-80KB → 45MB 훨씬 미만
    small_size = 80 * 1024
    large_size = 50 * 1024 * 1024

    def should_use_markdown_fallback(path: str) -> bool:
        return os.path.getsize(path) > LIMIT

    # 정상 케이스: 작은 PDF → PDF 첨부
    monkeypatch.setattr(os.path, "getsize", lambda p: small_size)
    assert not should_use_markdown_fallback(str(fake_pdf))

    # 초과 케이스: 50MB PDF → markdown fallback
    monkeypatch.setattr(os.path, "getsize", lambda p: large_size)
    assert should_use_markdown_fallback(str(fake_pdf))


# ---------------------------------------------------------------------------
# Fixture 파일 존재 확인
# ---------------------------------------------------------------------------

def test_fixtures_exist():
    """캡처된 fixture JSON 파일들이 존재한다."""
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    assert os.path.exists(os.path.join(base, "telegram_callback_query.json"))
    assert os.path.exists(os.path.join(base, "telegram_message_update.json"))


def test_callback_query_fixture_schema():
    """callback_query fixture가 Telegram Update 스키마를 따른다."""
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, "telegram_callback_query.json")) as f:
        data = json.load(f)
    assert "update_id" in data
    cq = data["callback_query"]
    assert "id" in cq
    assert "data" in cq
    assert cq["data"].startswith(("pdf:", "gen:", "gd:"))
