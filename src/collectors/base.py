import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=30.0,
        follow_redirects=True,
    )
