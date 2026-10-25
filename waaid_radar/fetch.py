"""Download the page: plain HTTP first, an optional headless browser as fallback."""

from __future__ import annotations

import time
from collections.abc import Callable

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36 WaaidRadar/1.0"
)


class FetchError(RuntimeError):
    pass


def fetch_html(
    url: str,
    *,
    user_agent: str | None = None,
    timeout: float = 30,
    attempts: int = 3,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """GET the page, retrying network errors, 429 and 5xx with exponential back-off."""
    http = session or requests.Session()
    headers = {
        "User-Agent": user_agent or USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en;q=0.8",
    }
    problem = "unknown error"
    for attempt in range(attempts):
        try:
            response = http.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200 and response.content:
                # requests assumes ISO-8859-1 when the header has no charset; the page is UTF-8.
                declared = (response.encoding or "").lower()
                encoding = declared if declared and declared != "iso-8859-1" else "utf-8"
                return response.content.decode(encoding, errors="replace")
            problem = f"HTTP {response.status_code}"
            if response.status_code < 500 and response.status_code != 429:
                break  # other 4xx answers will not fix themselves
        except requests.RequestException as exc:
            problem = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            sleep(2 ** (attempt + 1))
    raise FetchError(f"{url}: {problem}")


def fetch_rendered(url: str, *, user_agent: str | None = None, timeout: float = 60) -> str:
    """Render the page in headless Chromium, for when the content needs JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise FetchError("RENDER_JS needs Playwright: pip install playwright && playwright install chromium") from exc
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=user_agent or USER_AGENT, locale="ar-SA")
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            return page.content()
        finally:
            browser.close()
