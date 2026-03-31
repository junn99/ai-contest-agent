"""
위비티(wevity.com) 공모전 수집기
AI/데이터 관련 카테고리(웹/모바일/IT, 과학/공학, 기획/아이디어)에서 공모전을 수집합니다.
"""

import asyncio
import re
from datetime import datetime, date, timedelta

import httpx
import structlog
from bs4 import BeautifulSoup

from src.collectors.base import create_client
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)

# Cloudflare 챌린지 감지 마커
_CF_CHALLENGE_MARKERS = [
    "cf-browser-verification",
    "cf_clearance",
    "Checking your browser",
    "challenge-form",
    "jschl-answer",
    "cf-spinner",
    "__cf_chl",
]

# Accept-Encoding 명시 금지: httpx가 gzip 응답을 잘못 디코딩하므로 제거
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://www.wevity.com/",
}

# D-day 파싱 패턴: "D-17 접수중", "D-6 마감임박", "D+27 마감", "D-0 마감", "D+0"
_DDAY_RE = re.compile(r"D([+-])(\d+)")


def _detect_cloudflare(response: httpx.Response, html: str) -> bool:
    """Cloudflare 차단 여부 반환. True이면 차단됨."""
    if response.status_code == 403:
        return True
    is_challenge = any(marker in html for marker in _CF_CHALLENGE_MARKERS)
    return is_challenge


def _parse_dday(dday_text: str) -> tuple[int | None, bool]:
    """
    D-day 텍스트에서 (d_day, is_closed) 반환.

    - "D-17" → (17, False)
    - "D+27" → (-27, True)   # 마감됨 (양수 D+)
    - "D+0"  → (0, False)    # 당일
    - "D-0"  → (0, False)
    - 파싱 실패 → (None, False)
    """
    m = _DDAY_RE.search(dday_text)
    if not m:
        return None, False
    sign, digits = m.group(1), int(m.group(2))
    if sign == "-":
        d_day = digits
        is_closed = False
    else:
        # D+N: 마감 이후 N일 경과
        d_day = -digits
        is_closed = digits > 0  # D+0은 당일이므로 마감 아님
    return d_day, is_closed


def _parse_contests(html: str, category_name: str) -> list[dict]:
    """
    wevity HTML에서 공모전 raw dict 목록 파싱.

    구조: ul.list > li (첫 번째 li.top은 헤더)
      div.tit > a[href]  → 제목 + 링크
      div.organ          → 주최사
      div.day + span.dday → D-day + 상태
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    ul = soup.select_one("ul.list")
    if not ul:
        logger.warning("wevity.parse.no_ul_list", category=category_name)
        return results

    items = [li for li in ul.select("li") if "top" not in li.get("class", [])]

    for item in items:
        tit_div = item.select_one("div.tit")
        if not tit_div:
            continue

        link_el = tit_div.select_one("a[href]")
        if not link_el:
            continue

        # 제목: span 제거 후 텍스트
        for span in link_el.select("span"):
            span.decompose()
        title = link_el.get_text(strip=True)
        if not title:
            continue

        href = link_el.get("href", "")
        if href.startswith("?"):
            url = "https://www.wevity.com/index_university.php" + href
        elif href.startswith("/"):
            url = "https://www.wevity.com" + href
        else:
            url = href

        # contest_id: URL에서 cidx 파라미터 추출 (예: ?c=view&cidx=103334 → wv_103334)
        cidx_match = re.search(r"[?&]cidx=(\d+)", url)
        raw_id = cidx_match.group(1) if cidx_match else None

        # 주최사
        organ_el = item.select_one("div.organ")
        organizer = organ_el.get_text(strip=True) if organ_el else ""

        # D-day 및 상태
        day_div = item.select_one("div.day")
        dday_text = ""
        status_text = ""
        if day_div:
            status_el = day_div.select_one("span.dday")
            status_text = status_el.get_text(strip=True) if status_el else ""
            if status_el:
                status_el.decompose()
            dday_text = day_div.get_text(strip=True)

        results.append(
            {
                "raw_id": raw_id,
                "title": title,
                "url": url,
                "organizer": organizer,
                "dday_text": dday_text,
                "status_text": status_text,
                "category": category_name,
            }
        )

    return results


def _raw_to_contest_info(raw: dict, scraped_at: datetime) -> ContestInfo | None:
    """raw dict → ContestInfo 변환. 실패 시 None 반환."""
    raw_id = raw.get("raw_id")
    if not raw_id:
        # URL에서 파싱 실패 시 title 해시 기반 fallback
        title_slug = re.sub(r"\W+", "_", raw.get("title", "unknown"))[:20]
        contest_id = f"wv_{title_slug}"
    else:
        contest_id = f"wv_{raw_id}"

    dday_text = raw.get("dday_text", "")
    status_text = raw.get("status_text", "")
    d_day, is_closed = _parse_dday(dday_text)

    # 마감된 공모전(D+ 양수) 제외
    if is_closed:
        return None

    # deadline 추산: d_day가 있으면 today + d_day
    deadline: date | None = None
    if d_day is not None:
        deadline = (scraped_at.date() + timedelta(days=d_day))

    # status 정규화
    if status_text:
        status = status_text
    elif d_day is not None and d_day >= 0:
        status = "접수중"
    else:
        status = "마감"

    organizer = raw.get("organizer") or ""

    return ContestInfo(
        id=contest_id,
        platform="wevity",
        title=raw["title"],
        url=raw["url"],
        organizer=organizer,
        deadline=deadline,
        start_date=None,
        prize=None,
        prize_amount=None,
        eligibility_raw="",
        eligibility_tags=[],
        submission_format=None,
        category=raw.get("category", ""),
        description=None,
        status=status,
        d_day=d_day,
        scraped_at=scraped_at,
    )


class WevityCollector:
    """위비티 AI/데이터 관련 카테고리 수집기"""

    BASE_URL = "https://www.wevity.com"

    # 관련 카테고리 ID
    CATEGORY_IDS = [
        20,  # 웹/모바일/IT
        22,  # 과학/공학
        1,   # 기획/아이디어
    ]

    CATEGORY_NAMES = {
        20: "웹/모바일/IT",
        22: "과학/공학",
        1: "기획/아이디어",
    }

    MAX_PAGES = 3
    REQUEST_DELAY_MIN = 3.0  # seconds
    REQUEST_DELAY_MAX = 5.0  # seconds

    def __init__(self) -> None:
        self._blocked = False

    def _category_url(self, cat_id: int, page: int = 1) -> str:
        base = (
            f"{self.BASE_URL}/index_university.php"
            f"?c=find&s=_university&gub=1&cidx={cat_id}"
        )
        if page > 1:
            base += f"&gp={page}"
        return base

    async def discover(self) -> list[ContestInfo]:
        """진행중인 공모전 목록 수집 (모든 카테고리 + 페이지네이션)"""
        scraped_at = datetime.utcnow()
        contests: list[ContestInfo] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            for cat_id in self.CATEGORY_IDS:
                cat_name = self.CATEGORY_NAMES[cat_id]
                log = logger.bind(category=cat_name, cat_id=cat_id)

                for page in range(1, self.MAX_PAGES + 1):
                    url = self._category_url(cat_id, page)
                    log.info("wevity.discover.fetch", url=url, page=page)

                    try:
                        response = await client.get(url)
                    except httpx.RequestError as exc:
                        log.warning("wevity.discover.request_error", error=str(exc))
                        break

                    html = response.text

                    if _detect_cloudflare(response, html):
                        log.warning(
                            "wevity.discover.cloudflare_blocked",
                            status_code=response.status_code,
                        )
                        self._blocked = True
                        break

                    raw_list = _parse_contests(html, cat_name)
                    log.info("wevity.discover.parsed", count=len(raw_list), page=page)

                    if not raw_list:
                        # 빈 페이지 → 더 이상 데이터 없음
                        break

                    for raw in raw_list:
                        try:
                            info = _raw_to_contest_info(raw, scraped_at)
                        except Exception as exc:
                            log.warning(
                                "wevity.discover.convert_error",
                                title=raw.get("title"),
                                error=str(exc),
                            )
                            continue

                        if info is None:
                            # 마감된 공모전
                            continue

                        if info.id not in seen_ids:
                            seen_ids.add(info.id)
                            contests.append(info)

                    # 마지막 페이지가 아니면 rate limiting
                    if page < self.MAX_PAGES:
                        import random
                        delay = random.uniform(
                            self.REQUEST_DELAY_MIN, self.REQUEST_DELAY_MAX
                        )
                        await asyncio.sleep(delay)

                # 카테고리 간 delay
                if cat_id != self.CATEGORY_IDS[-1]:
                    import random
                    delay = random.uniform(
                        self.REQUEST_DELAY_MIN, self.REQUEST_DELAY_MAX
                    )
                    await asyncio.sleep(delay)

        logger.info("wevity.discover.complete", total=len(contests))
        return contests

    async def fetch_details(self, contest_id: str) -> ContestInfo:
        """
        개별 공모전 상세 정보 추출.

        contest_id: "wv_{cidx}" 형식 (예: wv_103334)
        상세 페이지 URL: /index_university.php?c=view&cidx={cidx}
        현재 list 페이지에서 이미 수집한 정보로 기본 ContestInfo를 반환합니다.
        """
        if not contest_id.startswith("wv_"):
            raise ValueError(f"Invalid wevity contest_id: {contest_id!r}")

        raw_cidx = contest_id[3:]  # "wv_103334" → "103334"
        url = f"{self.BASE_URL}/index_university.php?c=view&cidx={raw_cidx}"

        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            try:
                response = await client.get(url)
            except httpx.RequestError as exc:
                raise RuntimeError(
                    f"Failed to fetch detail for {contest_id}: {exc}"
                ) from exc

        html = response.text

        if _detect_cloudflare(response, html):
            logger.warning(
                "wevity.fetch_details.cloudflare_blocked",
                contest_id=contest_id,
                status_code=response.status_code,
            )
            self._blocked = True
            raise RuntimeError(f"Cloudflare blocked for {contest_id}")

        # 상세 페이지 파싱
        scraped_at = datetime.utcnow()
        soup = BeautifulSoup(html, "html.parser")

        # 제목
        title_el = soup.select_one(".view-tit, .tit, h1, h2")
        title = title_el.get_text(strip=True) if title_el else contest_id

        # 주최사
        organ_el = soup.select_one(".organ, .organizer")
        organizer = organ_el.get_text(strip=True) if organ_el else ""

        return ContestInfo(
            id=contest_id,
            platform="wevity",
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
            category="",
            description=None,
            status="접수중",
            d_day=None,
            scraped_at=scraped_at,
        )

    def health_check(self) -> bool:
        """사이트 접근 가능 + Cloudflare 미차단 확인"""
        if self._blocked:
            return False

        try:
            with httpx.Client(
                headers=_HEADERS,
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                response = client.get(f"{self.BASE_URL}/")
                html = response.text

            if _detect_cloudflare(response, html):
                logger.warning(
                    "wevity.health_check.cloudflare_blocked",
                    status_code=response.status_code,
                )
                self._blocked = True
                return False

            return response.status_code == 200

        except httpx.RequestError as exc:
            logger.warning("wevity.health_check.error", error=str(exc))
            return False
