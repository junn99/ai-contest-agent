"""
Unit tests for WevityCollector — no network calls.
"""

import httpx
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.wevity import (
    WevityCollector,
    _detect_cloudflare,
    _parse_dday,
    _parse_contests,
    _raw_to_contest_info,
)
from src.models.contest import ContestInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

SCRAPED_AT = datetime(2026, 3, 30, 12, 0, 0)

SAMPLE_HTML = """
<html><body>
<ul class="list">
  <li class="top"><div class="tit">제목</div><div class="organ">주최</div><div class="day">마감일</div></li>
  <li>
    <div class="tit"><a href="?c=view&amp;cidx=103334">AI 빅데이터 공모전<span>NEW</span></a></div>
    <div class="organ">한국정보화진흥원</div>
    <div class="day">D-17<span class="dday">접수중</span></div>
  </li>
  <li>
    <div class="tit"><a href="?c=view&amp;cidx=103335">머신러닝 챌린지</a></div>
    <div class="organ">KAIST</div>
    <div class="day">D-6<span class="dday">마감임박</span></div>
  </li>
  <li>
    <div class="tit"><a href="?c=view&amp;cidx=103336">이미 마감된 공모전</a></div>
    <div class="organ">서울시</div>
    <div class="day">D+27<span class="dday">마감</span></div>
  </li>
  <li>
    <div class="tit"><a href="/index_university.php?c=view&amp;cidx=103337">절대경로 공모전</a></div>
    <div class="organ">기관</div>
    <div class="day">D-0<span class="dday">접수중</span></div>
  </li>
</ul>
</body></html>
"""

CLOUDFLARE_HTML = """
<html><body>
<div id="cf-browser-verification">Checking your browser before accessing...</div>
<form class="challenge-form">...</form>
</body></html>
"""

NORMAL_HTML = "<html><body><ul class='list'></ul></body></html>"


# ── _detect_cloudflare ────────────────────────────────────────────────────────

class TestDetectCloudflare:
    def _make_response(self, status_code: int) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        return r

    def test_403_is_blocked(self):
        r = self._make_response(403)
        assert _detect_cloudflare(r, NORMAL_HTML) is True

    def test_200_with_normal_html_is_not_blocked(self):
        r = self._make_response(200)
        assert _detect_cloudflare(r, NORMAL_HTML) is False

    def test_200_with_challenge_page_is_blocked(self):
        r = self._make_response(200)
        assert _detect_cloudflare(r, CLOUDFLARE_HTML) is True

    def test_200_with_cf_spinner_is_blocked(self):
        r = self._make_response(200)
        html = "<html><body><div class='cf-spinner'>loading</div></body></html>"
        assert _detect_cloudflare(r, html) is True

    def test_503_without_challenge_is_not_blocked_by_cf_markers(self):
        r = self._make_response(503)
        assert _detect_cloudflare(r, NORMAL_HTML) is False


# ── _parse_dday ───────────────────────────────────────────────────────────────

class TestParseDday:
    def test_d_minus_17(self):
        d_day, is_closed = _parse_dday("D-17 접수중")
        assert d_day == 17
        assert is_closed is False

    def test_d_minus_6(self):
        d_day, is_closed = _parse_dday("D-6 마감임박")
        assert d_day == 6
        assert is_closed is False

    def test_d_plus_27_is_closed(self):
        d_day, is_closed = _parse_dday("D+27 마감")
        assert d_day == -27
        assert is_closed is True

    def test_d_minus_0(self):
        d_day, is_closed = _parse_dday("D-0")
        assert d_day == 0
        assert is_closed is False

    def test_d_plus_0_not_closed(self):
        # D+0 is the same day, not yet closed
        d_day, is_closed = _parse_dday("D+0")
        assert d_day == 0
        assert is_closed is False

    def test_no_dday_text(self):
        d_day, is_closed = _parse_dday("마감")
        assert d_day is None
        assert is_closed is False

    def test_empty_string(self):
        d_day, is_closed = _parse_dday("")
        assert d_day is None
        assert is_closed is False


# ── _parse_contests ───────────────────────────────────────────────────────────

class TestParseContests:
    def test_parses_contest_count(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        # 4 data items (header li.top is skipped)
        assert len(results) == 4

    def test_title_strip_span(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert results[0]["title"] == "AI 빅데이터 공모전"

    def test_organizer_extracted(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert results[0]["organizer"] == "한국정보화진흥원"

    def test_dday_text_extracted(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert "D-17" in results[0]["dday_text"]

    def test_status_text_extracted(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert results[0]["status_text"] == "접수중"

    def test_relative_url_resolved(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert results[0]["url"].startswith("https://www.wevity.com")
        assert "cidx=103334" in results[0]["url"]

    def test_absolute_path_url_resolved(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        # 4th item uses /index_university.php path
        assert results[3]["url"].startswith("https://www.wevity.com")

    def test_raw_id_extracted(self):
        results = _parse_contests(SAMPLE_HTML, "웹/모바일/IT")
        assert results[0]["raw_id"] == "103334"

    def test_no_ul_list_returns_empty(self):
        html = "<html><body><p>no list here</p></body></html>"
        results = _parse_contests(html, "test")
        assert results == []

    def test_category_attached(self):
        results = _parse_contests(SAMPLE_HTML, "과학/공학")
        assert all(r["category"] == "과학/공학" for r in results)


# ── _raw_to_contest_info ──────────────────────────────────────────────────────

class TestRawToContestInfo:
    def _make_raw(self, **overrides) -> dict:
        base = {
            "raw_id": "103334",
            "title": "AI 빅데이터 공모전",
            "url": "https://www.wevity.com/index_university.php?c=view&cidx=103334",
            "organizer": "한국정보화진흥원",
            "dday_text": "D-17",
            "status_text": "접수중",
            "category": "웹/모바일/IT",
        }
        base.update(overrides)
        return base

    def test_returns_contest_info(self):
        info = _raw_to_contest_info(self._make_raw(), SCRAPED_AT)
        assert isinstance(info, ContestInfo)

    def test_id_format(self):
        info = _raw_to_contest_info(self._make_raw(), SCRAPED_AT)
        assert info.id == "wv_103334"

    def test_platform_is_wevity(self):
        info = _raw_to_contest_info(self._make_raw(), SCRAPED_AT)
        assert info.platform == "wevity"

    def test_d_day_extracted(self):
        info = _raw_to_contest_info(self._make_raw(), SCRAPED_AT)
        assert info.d_day == 17

    def test_deadline_computed(self):
        info = _raw_to_contest_info(self._make_raw(dday_text="D-17"), SCRAPED_AT)
        expected = SCRAPED_AT.date() + timedelta(days=17)
        assert info.deadline == expected

    def test_closed_dday_plus_returns_none(self):
        info = _raw_to_contest_info(self._make_raw(dday_text="D+27", status_text="마감"), SCRAPED_AT)
        assert info is None

    def test_status_from_status_text(self):
        info = _raw_to_contest_info(self._make_raw(status_text="마감임박"), SCRAPED_AT)
        assert info.status == "마감임박"

    def test_status_defaults_to_접수중(self):
        info = _raw_to_contest_info(self._make_raw(status_text=""), SCRAPED_AT)
        assert info.status == "접수중"

    def test_fallback_id_when_no_raw_id(self):
        info = _raw_to_contest_info(self._make_raw(raw_id=None), SCRAPED_AT)
        assert info.id.startswith("wv_")

    def test_scraped_at_preserved(self):
        info = _raw_to_contest_info(self._make_raw(), SCRAPED_AT)
        assert info.scraped_at == SCRAPED_AT


# ── WevityCollector.health_check ──────────────────────────────────────────────

class TestWevityCollectorHealthCheck:
    def test_health_check_returns_true_on_200(self):
        collector = WevityCollector()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = NORMAL_HTML
        mock_response.headers = {}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = collector.health_check()

        assert result is True

    def test_health_check_returns_false_on_cloudflare(self):
        collector = WevityCollector()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = ""

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = collector.health_check()

        assert result is False
        assert collector._blocked is True

    def test_health_check_returns_false_when_already_blocked(self):
        collector = WevityCollector()
        collector._blocked = True
        # Should short-circuit without making any HTTP call
        result = collector.health_check()
        assert result is False

    def test_health_check_returns_false_on_request_error(self):
        collector = WevityCollector()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.RequestError("connection failed")
            mock_client_cls.return_value = mock_client

            result = collector.health_check()

        assert result is False


# ── WevityCollector.discover ──────────────────────────────────────────────────

class TestWevityCollectorDiscover:
    @pytest.mark.anyio
    async def test_discover_returns_contest_infos(self):
        collector = WevityCollector()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_HTML

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await collector.discover()

        assert isinstance(results, list)
        assert all(isinstance(r, ContestInfo) for r in results)

    @pytest.mark.anyio
    async def test_discover_excludes_closed_contests(self):
        collector = WevityCollector()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_HTML

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await collector.discover()

        # D+27 item should be excluded
        titles = [r.title for r in results]
        assert "이미 마감된 공모전" not in titles

    @pytest.mark.anyio
    async def test_discover_deduplicates_by_id(self):
        collector = WevityCollector()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_HTML

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await collector.discover()

        ids = [r.id for r in results]
        assert len(ids) == len(set(ids))

    @pytest.mark.anyio
    async def test_discover_stops_on_cloudflare(self):
        collector = WevityCollector()

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = ""

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await collector.discover()

        assert results == []
        assert collector._blocked is True
