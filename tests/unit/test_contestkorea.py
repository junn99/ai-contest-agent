"""단위 테스트: ContestKoreaCollector 파싱 로직"""

import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.contestkorea import (
    _parse_contests_from_html,
    _parse_dday_int,
    _parse_deadline,
    _parse_start_date,
    _parse_eligibility_tags,
    _find_contest_ul,
    ContestKoreaCollector,
)
from src.models.contest import ContestInfo
from bs4 import BeautifulSoup


# ── HTML 픽스처 ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.contestkorea.com"
SCRAPED_AT = datetime(2026, 3, 30, 12, 0, 0)


def _make_li(
    title: str = "테스트 공모전",
    href: str = "view.php?int_gbn=1&Txt_bcode=030310001&str_no=202603180064",
    dday: str = "D-15",
    condition: str = "접수중",
    period: str = "03.01~04.20",
    target: str = "일반인, 재직자",
    host: str = "테스트기관",
) -> str:
    return f"""
    <li>
      <div class="title">
        <a href="{href}">
          <span class="txt">{title}</span>
        </a>
      </div>
      <ul class="host">
        <li class="icon_1"><strong>주최</strong>{host}</li>
        <li class="icon_2"><strong>대상</strong>{target}</li>
      </ul>
      <div class="date">
        <span class="step-1"><em>접수</em>{period}</span>
      </div>
      <div class="d-day">
        <span class="day">{dday}</span>
        <span class="condition">{condition}</span>
      </div>
    </li>
    """


def _make_list_html(*li_strings: str) -> str:
    items = "\n".join(li_strings)
    return f"""
    <html><body>
      <ul>
        {items}
      </ul>
    </body></html>
    """


# ── D-day 파싱 테스트 ──────────────────────────────────────────────────────────

class TestParseDdayInt:
    def test_d_minus_15(self):
        assert _parse_dday_int("D-15") == 15

    def test_d_minus_3(self):
        assert _parse_dday_int("D-3") == 3

    def test_d_minus_0(self):
        assert _parse_dday_int("D-0") == 0

    def test_d_minus_153(self):
        assert _parse_dday_int("D-153") == 153

    def test_closed(self):
        assert _parse_dday_int("접수마감") is None

    def test_empty(self):
        assert _parse_dday_int("") is None

    def test_none_like(self):
        assert _parse_dday_int("접수예정") is None

    def test_en_dash_variant(self):
        # D–15 (en dash)
        assert _parse_dday_int("D\u201315") == 15


# ── 마감일 파싱 테스트 ──────────────────────────────────────────────────────────

class TestParseDeadline:
    def test_standard_period(self):
        d = _parse_deadline("03.01~04.20")
        assert d is not None
        assert d.month == 4
        assert d.day == 20

    def test_period_with_spaces(self):
        d = _parse_deadline("03.17 ~ 04.21")
        assert d is not None
        assert d.month == 4
        assert d.day == 21

    def test_empty_string(self):
        assert _parse_deadline("") is None

    def test_no_tilde(self):
        # 단일 날짜 — 그 날짜가 반환되어야 함
        d = _parse_deadline("04.21")
        assert d is not None
        assert d.month == 4
        assert d.day == 21

    def test_invalid_date(self):
        assert _parse_deadline("13.99") is None


# ── 시작일 파싱 테스트 ──────────────────────────────────────────────────────────

class TestParseStartDate:
    def test_standard(self):
        d = _parse_start_date("03.01~04.20")
        assert d is not None
        assert d.month == 3
        assert d.day == 1

    def test_empty(self):
        assert _parse_start_date("") is None


# ── eligibility 태그 파싱 ─────────────────────────────────────────────────────

class TestParseEligibilityTags:
    def test_multiple_tags(self):
        tags = _parse_eligibility_tags("일반인, 재직자, 대학생")
        assert tags == ["일반인", "재직자", "대학생"]

    def test_single_tag(self):
        assert _parse_eligibility_tags("누구나") == ["누구나"]

    def test_empty(self):
        assert _parse_eligibility_tags("") == []

    def test_strips_whitespace(self):
        tags = _parse_eligibility_tags("  일반인 ,  재직자  ")
        assert tags == ["일반인", "재직자"]


# ── HTML 파싱: 목록 ──────────────────────────────────────────────────────────

class TestParseContestsFromHtml:
    def test_empty_html(self):
        contests = _parse_contests_from_html("<html></html>", BASE_URL, SCRAPED_AT)
        assert contests == []

    def test_single_contest(self):
        html = _make_list_html(_make_li())
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert len(contests) == 1
        c = contests[0]
        assert c.id == "ck_202603180064"
        assert c.title == "테스트 공모전"
        assert c.platform == "contestkorea"
        assert c.category == "IT/과학"

    def test_multiple_contests(self):
        li1 = _make_li(title="공모전1", href="view.php?str_no=111111111111")
        li2 = _make_li(title="공모전2", href="view.php?str_no=222222222222")
        li3 = _make_li(title="공모전3", href="view.php?str_no=333333333333")
        html = _make_list_html(li1, li2, li3)
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert len(contests) == 3
        assert contests[0].title == "공모전1"
        assert contests[1].title == "공모전2"
        assert contests[2].title == "공모전3"

    def test_missing_str_no_skipped(self):
        li = _make_li(href="view.php?int_gbn=1")  # str_no 없음
        html = _make_list_html(li)
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests == []

    def test_no_title_skipped(self):
        # span.txt가 없고 a 태그도 텍스트 없는 경우
        li = """
        <li>
          <div class="title"><a href="view.php?str_no=999999999999"><span class="txt"></span></a></div>
          <div class="d-day"><span class="day">D-5</span><span class="condition">접수중</span></div>
        </li>
        """
        html = _make_list_html(li)
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests == []


# ── ContestInfo 변환 검증 ─────────────────────────────────────────────────────

class TestContestInfoConversion:
    def test_id_format(self):
        html = _make_list_html(
            _make_li(href="view.php?int_gbn=1&Txt_bcode=030310001&str_no=202603180064")
        )
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].id == "ck_202603180064"

    def test_url_relative_path(self):
        """href가 상대경로일 때 BASE_URL + /sub/ 이 붙어야 함."""
        html = _make_list_html(
            _make_li(href="view.php?str_no=202603180064")
        )
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].url.startswith(BASE_URL + "/sub/")

    def test_url_absolute_path(self):
        """href가 /로 시작하면 BASE_URL만 붙어야 함."""
        html = _make_list_html(
            _make_li(href="/sub/view.php?str_no=202603180064")
        )
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].url == BASE_URL + "/sub/view.php?str_no=202603180064"

    def test_dday_parsed(self):
        html = _make_list_html(_make_li(dday="D-26"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].d_day == 26

    def test_status_parsed(self):
        html = _make_list_html(_make_li(condition="접수예정"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].status == "접수예정"

    def test_eligibility_tags_parsed(self):
        html = _make_list_html(_make_li(target="일반인, 재직자"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert "일반인" in contests[0].eligibility_tags
        assert "재직자" in contests[0].eligibility_tags

    def test_organizer_parsed(self):
        html = _make_list_html(_make_li(host="산림교육원"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert "산림교육원" in contests[0].organizer

    def test_deadline_parsed(self):
        html = _make_list_html(_make_li(period="03.01~04.20"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        c = contests[0]
        assert c.deadline is not None
        assert c.deadline.month == 4
        assert c.deadline.day == 20

    def test_scraped_at_set(self):
        html = _make_list_html(_make_li())
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].scraped_at == SCRAPED_AT

    def test_is_valid_contestinfo(self):
        """파싱 결과가 ContestInfo Pydantic 모델로 유효해야 함."""
        html = _make_list_html(_make_li())
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert isinstance(contests[0], ContestInfo)
        # round-trip 검증
        c = contests[0]
        assert ContestInfo.model_validate_json(c.model_dump_json()) == c


# ── D-day 케이스 통합 ──────────────────────────────────────────────────────────

class TestDdayEdgeCases:
    def test_접수마감_status(self):
        html = _make_list_html(_make_li(dday="접수마감", condition="접수마감"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].d_day is None
        assert contests[0].status == "접수마감"

    def test_d3_imminent(self):
        html = _make_list_html(_make_li(dday="D-3", condition="접수중"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].d_day == 3

    def test_접수예정_no_dday(self):
        html = _make_list_html(_make_li(dday="", condition="접수예정"))
        contests = _parse_contests_from_html(html, BASE_URL, SCRAPED_AT)
        assert contests[0].d_day is None
        assert contests[0].status == "접수예정"


# ── health_check 테스트 ──────────────────────────────────────────────────────

class TestHealthCheck:
    def test_health_check_true_when_contests_found(self):
        html = _make_list_html(_make_li())
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html

        collector = ContestKoreaCollector()
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = collector.health_check()

        assert result is True

    def test_health_check_false_when_no_contests(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"

        collector = ContestKoreaCollector()
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = collector.health_check()

        assert result is False

    def test_health_check_false_on_http_error(self):
        import httpx

        collector = ContestKoreaCollector()
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.ConnectError("연결 실패")
            mock_client_class.return_value = mock_client

            result = collector.health_check()

        assert result is False

    def test_health_check_false_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        collector = ContestKoreaCollector()
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = collector.health_check()

        assert result is False
