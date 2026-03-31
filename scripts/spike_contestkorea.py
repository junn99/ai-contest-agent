"""
Phase 0 Spike: 콘테스트코리아 IT/과학 카테고리 크롤링 테스트
URL: https://www.contestkorea.com/sub/list.php?int_gbn=1&Txt_bcode=030310001

HTML 구조:
  <ul> (no class) -> <li [class="imminent"]>
    <div class="title"> <a href="view.php?..."> <span class="txt">제목</span>
    <ul class="host">
      <li class="icon_1"> 주최
      <li class="icon_2"> 대상(참가자격)
    <div class="date"> <span class="step-1"> 접수기간
    <div class="d-day"> <span class="day"> D-N </span> <span class="condition"> 상태
"""

import json
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime


BASE_URL = "https://www.contestkorea.com"
LIST_URL = "https://www.contestkorea.com/sub/list.php"
PARAMS_BASE = {
    "int_gbn": "1",
    "Txt_bcode": "030310001",
    "displayrow": "12",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE_URL,
}

OUTPUT_PATH = Path("/home/jun99/claude/infoke/data/spike_contestkorea.json")


def fetch_page(client: httpx.Client, page: int) -> str:
    params = {**PARAMS_BASE, "page": str(page)}
    resp = client.get(LIST_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def find_contest_ul(soup: BeautifulSoup):
    """view.php 링크를 포함하는 공모전 목록 ul을 찾는다."""
    for ul in soup.find_all("ul"):
        if ul.find("a", href=lambda h: h and "view.php" in str(h)):
            return ul
    return None


def parse_item(li) -> dict | None:
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
        url = BASE_URL + href
    else:
        url = BASE_URL + "/sub/" + href

    # D-day
    day_tag = li.select_one("div.d-day span.day")
    dday = day_tag.get_text(strip=True) if day_tag else ""

    # 상태 (접수중 / 마감 등)
    condition_tag = li.select_one("div.d-day span.condition")
    status = condition_tag.get_text(strip=True) if condition_tag else ""

    # 접수 기간 (step-1)
    period_tag = li.select_one("div.date span.step-1")
    if period_tag:
        # <em>접수</em> 03.17~04.21 -> 날짜 부분만
        em = period_tag.find("em")
        if em:
            em.extract()
        deadline = " ".join(period_tag.get_text(separator=" ", strip=True).split())
    else:
        deadline = ""

    # 참가 자격 (host > icon_2)
    target_tag = li.select_one("ul.host li.icon_2")
    if target_tag:
        strong = target_tag.find("strong")
        if strong:
            strong.extract()
        raw = target_tag.get_text(separator=" ", strip=True).lstrip(". ")
        # 쉼표로 분리 후 각 항목 정제, 빈 값 제거
        parts = [p.strip() for p in raw.replace("▶", "").split(",") if p.strip()]
        target = ", ".join(parts)
    else:
        target = ""

    # 주최
    host_tag = li.select_one("ul.host li.icon_1")
    if host_tag:
        strong = host_tag.find("strong")
        if strong:
            strong.extract()
        host = host_tag.get_text(separator=" ", strip=True).lstrip(". ").strip()
    else:
        host = ""

    return {
        "title": title,
        "url": url,
        "dday": dday,
        "deadline": deadline,
        "target": target,
        "host": host,
        "status": status,
    }


def parse_contests(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    ul = find_contest_ul(soup)
    if not ul:
        return []

    contests = []
    for li in ul.find_all("li", recursive=False):
        item = parse_item(li)
        if item:
            contests.append(item)
    return contests


def main():
    contests = []

    with httpx.Client(follow_redirects=True) as client:
        for page in range(1, 4):  # 최대 3페이지 시도
            print(f"Fetching page {page}...")
            try:
                html = fetch_page(client, page)
            except httpx.HTTPError as e:
                print(f"  HTTP error on page {page}: {e}")
                break

            page_contests = parse_contests(html)
            print(f"  Parsed {len(page_contests)} contests from page {page}")

            if not page_contests:
                print("  No contests found, stopping pagination")
                break

            contests.extend(page_contests)

            if len(contests) >= 5:
                break

    print(f"\nTotal contests collected: {len(contests)}")

    # 결과 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "crawled_at": datetime.now().isoformat(),
        "source_url": LIST_URL,
        "category": "IT/과학 (030310001)",
        "total": len(contests),
        "contests": contests,
    }

    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {OUTPUT_PATH}")

    # 샘플 출력
    for i, c in enumerate(contests[:5], 1):
        print(f"\n[{i}] {c['title']}")
        print(f"    URL:    {c['url']}")
        print(f"    D-day:  {c['dday']}  |  마감: {c['deadline']}  |  상태: {c['status']}")
        print(f"    대상:   {c['target']}  |  주최: {c['host']}")


if __name__ == "__main__":
    main()
