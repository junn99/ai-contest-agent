"""콘테스트코리아 IT/과학 카테고리 수집기"""

import asyncio
import re
from datetime import date, datetime
from urllib.parse import urlencode, urlparse, parse_qs

import structlog
from bs4 import BeautifulSoup

from src.collectors.base import create_client
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


def _extract_str_no(url: str) -> str | None:
    """URL에서 str_no 파라미터 추출."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    values = qs.get("str_no", [])
    return values[0] if values else None


def _parse_dday_int(dday_text: str) -> int | None:
    """'D-15', 'D-3', 'D-0', '접수마감' 등을 정수로 변환."""
    if not dday_text:
        return None
    match = re.search(r"D[-–](\d+)", dday_text)
    if match:
        return int(match.group(1))
    return None


def _parse_deadline(period_text: str) -> date | None:
    """
    '03.17~04.21' 또는 '03.01~04.20' 형태에서 마감일 추출.
    연도는 현재 연도 기준으로 결정 (월이 현재보다 이전이면 다음 해).
    """
    if not period_text:
        return None
    # 기간 중 마지막 날짜 (~ 이후 부분)
    parts = period_text.split("~")
    end_str = parts[-1].strip() if len(parts) >= 2 else parts[0].strip()
    match = re.match(r"(\d{2})\.(\d{2})", end_str)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    today = datetime.utcnow().date()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    # 마감일이 오늘보다 많이 이전이면 (90일 초과) 다음 해로 추정
    if (today - candidate).days > 90:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _parse_start_date(period_text: str) -> date | None:
    """'03.17~04.21' 형태에서 시작일 추출."""
    if not period_text:
        return None
    parts = period_text.split("~")
    start_str = parts[0].strip()
    match = re.match(r"(\d{2})\.(\d{2})", start_str)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    today = datetime.utcnow().date()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if (today - candidate).days > 180:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _parse_eligibility_tags(raw: str) -> list[str]:
    """쉼표로 구분된 자격 문자열을 태그 리스트로 변환."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _find_contest_ul(soup: BeautifulSoup):
    """view.php 링크를 포함하는 공모전 목록 ul을 찾는다."""
    for ul in soup.find_all("ul"):
        if ul.find("a", href=lambda h: h and "view.php" in str(h)):
            return ul
    return None


def _parse_item_to_contest(li, base_url: str, scraped_at: datetime) -> ContestInfo | None:
    """li 요소 하나를 ContestInfo로 변환. 파싱 실패 시 None 반환."""
    # 제목 + URL
    title_tag = li.select_one("div.title a")
    if not title_tag:
        return None

    txt_span = title_tag.select_one("span.txt")
    title = txt_span.get_text(strip=True) if txt_span else title_tag.get_text(strip=True)
    if not title:
        return None

    href = title_tag.get("href", "")
    if href.startswith("http"):
        url = href
    elif href.startswith("/"):
        url = base_url + href
    else:
        url = base_url + "/sub/" + href

    str_no = _extract_str_no(url)
    if not str_no:
        return None
    contest_id = f"ck_{str_no}"

    # D-day
    day_tag = li.select_one("div.d-day span.day")
    dday_text = day_tag.get_text(strip=True) if day_tag else ""
    d_day = _parse_dday_int(dday_text)

    # 상태
    condition_tag = li.select_one("div.d-day span.condition")
    status = condition_tag.get_text(strip=True) if condition_tag else "접수중"
    if not status:
        status = "접수중"

    # 접수 기간 (step-1)
    period_tag = li.select_one("div.date span.step-1")
    period_text = ""
    if period_tag:
        em = period_tag.find("em")
        if em:
            em.extract()
        period_text = " ".join(period_tag.get_text(separator=" ", strip=True).split())

    deadline = _parse_deadline(period_text)
    start_date = _parse_start_date(period_text)

    # 참가 자격 (host > icon_2)
    target_tag = li.select_one("ul.host li.icon_2")
    eligibility_raw = ""
    if target_tag:
        strong = target_tag.find("strong")
        if strong:
            strong.extract()
        raw = target_tag.get_text(separator=" ", strip=True).lstrip(". ")
        parts = [p.strip() for p in raw.replace("▶", "").split(",") if p.strip()]
        eligibility_raw = ", ".join(parts)

    eligibility_tags = _parse_eligibility_tags(eligibility_raw)

    # 주최
    host_tag = li.select_one("ul.host li.icon_1")
    organizer = ""
    if host_tag:
        strong = host_tag.find("strong")
        if strong:
            strong.extract()
        organizer = host_tag.get_text(separator=" ", strip=True).lstrip(". ").strip()

    return ContestInfo(
        id=contest_id,
        platform="contestkorea",
        title=title,
        url=url,
        organizer=organizer,
        deadline=deadline,
        start_date=start_date,
        prize=None,
        prize_amount=None,
        eligibility_raw=eligibility_raw,
        eligibility_tags=eligibility_tags,
        submission_format=None,
        category="IT/과학",
        description=None,
        status=status,
        d_day=d_day,
        scraped_at=scraped_at,
    )


def _parse_contests_from_html(html: str, base_url: str, scraped_at: datetime) -> list[ContestInfo]:
    """HTML에서 공모전 목록을 파싱하여 ContestInfo 리스트 반환."""
    soup = BeautifulSoup(html, "html.parser")
    ul = _find_contest_ul(soup)
    if not ul:
        return []

    contests = []
    for li in ul.find_all("li", recursive=False):
        try:
            item = _parse_item_to_contest(li, base_url, scraped_at)
            if item:
                contests.append(item)
        except Exception as exc:
            logger.warning("item_parse_error", error=str(exc))
    return contests


class ContestKoreaCollector:
    """콘테스트코리아 IT/과학 카테고리 수집기"""

    BASE_URL = "https://www.contestkorea.com"
    LIST_URL = "/sub/list.php"

    # IT/과학 카테고리 코드들 (AI/데이터 관련)
    CATEGORY_CODES = [
        "030310001",  # 학문·과학·IT
    ]

    MAX_PAGES = 5
    REQUEST_DELAY_MIN = 2.0
    REQUEST_DELAY_MAX = 3.0

    async def discover(self) -> list[ContestInfo]:
        """진행중인 공모전 목록 수집 (여러 페이지 순회)"""
        all_contests: list[ContestInfo] = []
        scraped_at = datetime.utcnow()

        async with create_client() as client:
            for category_code in self.CATEGORY_CODES:
                for page in range(1, self.MAX_PAGES + 1):
                    params = {
                        "int_gbn": "1",
                        "Txt_bcode": category_code,
                        "displayrow": "12",
                        "page": str(page),
                    }
                    url = self.BASE_URL + self.LIST_URL + "?" + urlencode(params)
                    logger.info(
                        "fetching_page",
                        category=category_code,
                        page=page,
                        url=url,
                    )

                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                    except Exception as exc:
                        logger.error(
                            "page_fetch_error",
                            category=category_code,
                            page=page,
                            error=str(exc),
                        )
                        break

                    contests = _parse_contests_from_html(
                        resp.text, self.BASE_URL, scraped_at
                    )
                    logger.info(
                        "page_parsed",
                        category=category_code,
                        page=page,
                        count=len(contests),
                    )

                    if not contests:
                        logger.info(
                            "no_contests_stopping_pagination",
                            category=category_code,
                            page=page,
                        )
                        break

                    all_contests.extend(contests)

                    if page < self.MAX_PAGES:
                        delay = self.REQUEST_DELAY_MIN + (
                            (self.REQUEST_DELAY_MAX - self.REQUEST_DELAY_MIN) * 0.5
                        )
                        await asyncio.sleep(delay)

        # 중복 제거 (동일 id)
        seen: set[str] = set()
        unique: list[ContestInfo] = []
        for c in all_contests:
            if c.id not in seen:
                seen.add(c.id)
                unique.append(c)

        logger.info("discover_complete", total=len(unique))
        return unique

    async def fetch_details(self, contest_id: str) -> ContestInfo:
        """개별 공모전 상세 정보 추출 (현재는 목록 정보를 그대로 반환)."""
        # str_no 추출: "ck_202603180064" -> "202603180064"
        str_no = contest_id.removeprefix("ck_")
        url = (
            self.BASE_URL
            + "/sub/view.php?int_gbn=1"
            + f"&Txt_bcode={self.CATEGORY_CODES[0]}"
            + f"&str_no={str_no}"
        )
        scraped_at = datetime.utcnow()

        async with create_client() as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.error(
                    "fetch_details_error", contest_id=contest_id, error=str(exc)
                )
                raise

        soup = BeautifulSoup(resp.text, "html.parser")

        # 제목 추출 (상세 페이지)
        title_tag = soup.select_one("div.view-title") or soup.select_one("h1") or soup.select_one("h2")
        title = title_tag.get_text(strip=True) if title_tag else contest_id

        # 주최
        organizer = ""
        for row in soup.select("table tr, dl dt"):
            text = row.get_text(strip=True)
            if "주최" in text or "주관" in text:
                sibling = row.find_next_sibling()
                if sibling:
                    organizer = sibling.get_text(strip=True)
                break

        return ContestInfo(
            id=contest_id,
            platform="contestkorea",
            title=title,
            url=url,
            organizer=organizer,
            deadline=None,
            start_date=None,
            prize=None,
            prize_amount=None,
            eligibility_raw="",
            eligibility_tags=[],
            submission_format=None,
            category="IT/과학",
            description=None,
            status="접수중",
            d_day=None,
            scraped_at=scraped_at,
        )

    def health_check(self) -> bool:
        """사이트 접근 가능 여부 확인 (HTTP 200 + 공모전 1개 이상)."""
        import httpx as _httpx
        from src.collectors.base import DEFAULT_HEADERS

        params = {
            "int_gbn": "1",
            "Txt_bcode": self.CATEGORY_CODES[0],
            "displayrow": "12",
            "page": "1",
        }
        url = self.BASE_URL + self.LIST_URL + "?" + urlencode(params)
        try:
            with _httpx.Client(
                headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True
            ) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "health_check_bad_status", status=resp.status_code
                    )
                    return False
                contests = _parse_contests_from_html(
                    resp.text, self.BASE_URL, datetime.utcnow()
                )
                ok = len(contests) >= 1
                logger.info("health_check_result", ok=ok, contest_count=len(contests))
                return ok
        except Exception as exc:
            logger.error("health_check_error", error=str(exc))
            return False
