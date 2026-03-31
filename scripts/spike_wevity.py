"""
Phase 0 Spike: 위비티(wevity.com) 크롤링 테스트
IT/웹/과학 카테고리에서 공모전 정보 추출
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

OUTPUT_PATH = Path("/home/jun99/claude/infoke/data/spike_wevity.json")

CATEGORIES = [
    {
        "name": "웹/모바일/IT",
        "cidx": 20,
        "url": "https://www.wevity.com/index_university.php?c=find&s=_university&gub=1&cidx=20",
    },
    {
        "name": "과학/공학",
        "cidx": 22,
        "url": "https://www.wevity.com/index_university.php?c=find&s=_university&gub=1&cidx=22",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    # Accept-Encoding 명시 시 httpx.Client가 gzip 응답을 잘못 처리하므로 제거
    # httpx가 자동으로 디코딩 처리함
    "Connection": "keep-alive",
    "Referer": "https://www.wevity.com/",
}


def detect_cloudflare(response: httpx.Response, html: str) -> dict:
    """Cloudflare 보호 여부 판정"""
    status = response.status_code
    cf_headers = {k: v for k, v in response.headers.items() if "cf-" in k.lower()}

    is_challenge = any(
        marker in html
        for marker in [
            "cf-browser-verification",
            "cf_clearance",
            "Checking your browser",
            "challenge-form",
            "jschl-answer",
            "cf-spinner",
            "Ray ID",
            "__cf_chl",
        ]
    )

    if status == 403:
        verdict = "FAIL"
        reason = "HTTP 403 Forbidden"
    elif status != 200:
        verdict = "FAIL"
        reason = f"HTTP {status}"
    elif is_challenge:
        verdict = "FAIL"
        reason = "Cloudflare challenge page detected"
    else:
        verdict = "PASS"
        reason = "HTTP 200 with real content"

    return {
        "verdict": verdict,
        "reason": reason,
        "status_code": status,
        "cf_headers": cf_headers,
        "is_challenge_page": is_challenge,
    }


def parse_contests(html: str, category_name: str) -> list[dict]:
    """공모전 목록 파싱

    wevity 실제 구조:
      ul.list > li (첫 번째 li.top은 헤더)
        div.tit > a[href]  → 제목 + 링크
        div.organ          → 주최사
        div.day            → D-day 숫자 + span.dday (접수중/마감 등)
    """
    soup = BeautifulSoup(html, "html.parser")
    contests = []

    ul = soup.select_one("ul.list")
    if not ul:
        print("  [parser] ul.list not found", flush=True)
        return contests

    items = ul.select("li")
    # 첫 번째 li는 헤더(class="top") — 건너뜀
    data_items = [li for li in items if "top" not in li.get("class", [])]
    print(f"  [parser] ul.list → {len(data_items)} contest items", flush=True)

    for item in data_items:
        tit_div = item.select_one("div.tit")
        if not tit_div:
            continue

        link_el = tit_div.select_one("a[href]")
        if not link_el:
            continue

        # 제목: a 태그 내 span 제거 후 텍스트
        for span in link_el.select("span"):
            span.decompose()
        title = link_el.get_text(strip=True)

        href = link_el.get("href", "")
        if href.startswith("?"):
            url = "https://www.wevity.com/index_university.php" + href
        elif href.startswith("/"):
            url = "https://www.wevity.com" + href
        else:
            url = href

        # 주최사
        organ_el = item.select_one("div.organ")
        organizer = organ_el.get_text(strip=True) if organ_el else None

        # D-day 및 상태
        day_div = item.select_one("div.day")
        dday = None
        status = None
        if day_div:
            status_el = day_div.select_one("span.dday")
            status = status_el.get_text(strip=True) if status_el else None
            if status_el:
                status_el.decompose()
            dday = day_div.get_text(strip=True)

        if title:
            contests.append(
                {
                    "title": title,
                    "url": url,
                    "organizer": organizer,
                    "dday": dday,
                    "status": status,
                    "category": category_name,
                }
            )

    return contests


def fetch_category(client: httpx.Client, category: dict) -> dict:
    """카테고리 페이지 요청 및 파싱"""
    print(f"\n[fetch] {category['name']} ({category['url']})", flush=True)

    try:
        response = client.get(category["url"], follow_redirects=True)
        html = response.text
        print(f"  status: {response.status_code}, content-length: {len(html)} bytes", flush=True)
    except Exception as e:
        return {
            "category": category["name"],
            "cidx": category["cidx"],
            "cloudflare": {
                "verdict": "FAIL",
                "reason": f"Request error: {e}",
                "status_code": None,
                "cf_headers": {},
                "is_challenge_page": False,
            },
            "contests": [],
            "error": str(e),
        }

    cf_status = detect_cloudflare(response, html)
    print(f"  cloudflare verdict: {cf_status['verdict']} — {cf_status['reason']}", flush=True)

    contests = []
    if cf_status["verdict"] == "PASS":
        contests = parse_contests(html, category["name"])
        print(f"  parsed {len(contests)} contests", flush=True)

    return {
        "category": category["name"],
        "cidx": category["cidx"],
        "cloudflare": cf_status,
        "contests": contests,
    }


def main():
    print("=== 위비티 크롤링 스파이크 ===", flush=True)
    print(f"실행 시각: {datetime.now().isoformat()}", flush=True)

    all_contests = []
    category_results = []

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        for category in CATEGORIES:
            result = fetch_category(client, category)
            category_results.append(result)
            all_contests.extend(result.get("contests", []))

    total = len(all_contests)
    print(f"\n총 추출된 공모전 수: {total}", flush=True)

    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique_contests = []
    for c in all_contests:
        key = c.get("url", c.get("title", ""))
        if key and key not in seen_urls:
            seen_urls.add(key)
            unique_contests.append(c)

    print(f"중복 제거 후: {len(unique_contests)}개", flush=True)

    # 전체 Cloudflare 판정
    all_pass = all(r["cloudflare"]["verdict"] == "PASS" for r in category_results)
    overall_cf = "PASS" if all_pass else "PARTIAL_FAIL" if any(
        r["cloudflare"]["verdict"] == "PASS" for r in category_results
    ) else "FAIL"

    output = {
        "spike": "phase0_wevity",
        "scraped_at": datetime.now().isoformat(),
        "cloudflare_overall": overall_cf,
        "categories": [
            {
                "name": r["category"],
                "cidx": r["cidx"],
                "cloudflare": r["cloudflare"],
                "contest_count": len(r.get("contests", [])),
            }
            for r in category_results
        ],
        "total_contests": len(unique_contests),
        "contests": unique_contests,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {OUTPUT_PATH}", flush=True)

    # 수용 기준 확인
    if overall_cf == "FAIL":
        print("\n[결과] Cloudflare 차단 — 크롤링 불가", flush=True)
        print("  → 모든 카테고리가 차단됨. 별도 우회 방법 필요.", flush=True)
        sys.exit(0)  # 에러로 종료하지 않음
    elif len(unique_contests) >= 5:
        print(f"\n[결과] PASS — {len(unique_contests)}개 공모전 추출 성공", flush=True)
    else:
        print(f"\n[결과] PARTIAL — {len(unique_contests)}개 추출 (목표: 5개 이상)", flush=True)

    # 샘플 출력
    if unique_contests:
        print("\n--- 샘플 (최대 5개) ---", flush=True)
        for c in unique_contests[:5]:
            print(f"  제목: {c['title']}", flush=True)
            print(f"  URL : {c['url']}", flush=True)
            print(f"  D-day: {c['dday']}  상태: {c['status']}", flush=True)
            print(f"  카테고리: {c['category']}", flush=True)
            print("  ---", flush=True)


if __name__ == "__main__":
    main()
