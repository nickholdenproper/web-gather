"""Real-browser mode - headless Chromium via Playwright, like a human surfing.

Never opens a window: everything runs in the background. A persistent
``--user-data-dir`` keeps cookies/logins so sites see a returning visitor.
The hybrid fetcher uses fast HTTP first and only switches to the browser for
JS shells / challenge pages / failed statuses (``auto``), or always/never.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .fetch import FetchResult

JS_SHELL_HINTS = re.compile(
    r'id=["\'](root|app|__next|__nuxt)["\']|<div[^>]*data-reactroot|<script[^>]*src=',
    re.I,
)


def looks_like_js_shell(html: str) -> bool:
    """Heuristic: skeletal page waiting for JavaScript to render."""
    return bool(JS_SHELL_HINTS.search(html[:8000]))


class BrowserError(RuntimeError):
    """Browser not installed / misconfigured."""


class BrowserSession:
    """A lazy headless browser with fetch + search support."""

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout_ms: int = 30000,
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self._sync = None
        self._browser = None
        self._context = None

    def _ensure(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "Playwright is not installed. Run: pip install web-gather[browser] "
                "and then: playwright install chromium"
            ) from exc
        self._sync = sync_playwright().start()
        try:
            args = ["--disable-blink-features=AutomationControlled"]
            if self.user_data_dir:
                # Persistent profile: cookies/logins survive, like a real user.
                self._context = self._sync.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                    user_agent=self.user_agent,
                    args=args,
                )
                self._browser = self._context.browser
            else:
                self._browser = self._sync.chromium.launch(
                    headless=self.headless, args=args
                )
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise BrowserError(
                "Could not start Chromium. Run: playwright install chromium"
            ) from exc

    def _context_or_default(self):
        if self._context is not None:
            return self._context
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        return self._context

    def get(self, url: str) -> FetchResult:
        """Open a page like a human and return the fully rendered HTML."""
        self._ensure()
        page = self._context_or_default().new_page()
        status = 200
        final_url = url
        try:
            response = page.goto(
                url, wait_until="domcontentloaded", timeout=self.timeout_ms
            )
            if response is not None:
                status = response.status
                final_url = str(response.url)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:  # noqa: BLE001 - networkidle is best-effort
                pass
            html = page.content()
        except Exception as exc:  # noqa: BLE001
            page.close()
            raise RuntimeError(f"browser navigation failed for {url}: {exc}") from exc
        page.close()
        return FetchResult(url=final_url, status_code=status, headers={}, text=html)

    def search(self, engine: str, query: str, limit: int) -> list[tuple[str, str, str]]:
        """Return (title, url, snippet) results from the live SERP."""
        self._ensure()
        if engine == "google":
            return self._search_google(query, limit)
        if engine == "ddg-browser":
            return self._search_ddg(query)
        raise ValueError(f"unknown browser engine: {engine}")

    def _search_google(self, query: str, limit: int) -> list[tuple[str, str, str]]:
        import urllib.parse

        url = "https://www.google.com/search?" + urllib.parse.urlencode(
            {"q": query, "num": min(limit, 20), "hl": "en"}
        )
        page = self._context_or_default().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            items = page.eval_on_selector_all(
                "a h3",
                "els => els.filter(e => e.innerText).map(e => {"
                " const a = e.closest('a'); return [e.innerText, a ? a.href : '', '']; })",
            )
        except Exception:  # noqa: BLE001
            return []
        finally:
            page.close()
        out: list[tuple[str, str, str]] = []
        for title, href, _snippet in items:
            real = _unwrap_google(href)
            if real and urlparse(real).scheme in ("http", "https"):
                out.append((title, real, ""))
        return out

    def _search_ddg(self, query: str) -> list[tuple[str, str, str]]:
        import urllib.parse

        from .search import parse_ddg

        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        page = self._context_or_default().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            html = page.content()
        finally:
            page.close()
        return [
            (r.title, r.url, r.snippet)
            for r in parse_ddg(html, engine="ddg-browser")
        ]

    def available(self) -> bool:
        try:
            self._ensure()
            return True
        except BrowserError:
            return False

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._sync is not None:
            try:
                self._sync.stop()
            except Exception:  # noqa: BLE001
                pass
            self._sync = None

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _unwrap_google(href: str) -> Optional[str]:
    if href.startswith("/url?q="):
        parsed = parse_qs(urlparse(href).query)
        return parsed.get("q", [None])[0]
    if href.startswith("http") and "google." not in urlparse(href).netloc:
        return href
    return None


class HybridFetcher:
    """HTTP-first fetcher that transparently promotes to the real browser."""

    def __init__(self, http_fetcher, browser: Optional[BrowserSession], mode: str = "auto"):
        self.http = http_fetcher
        self.browser = browser
        self.mode = mode if mode in ("auto", "always", "never") else "auto"

    def get(self, url: str) -> FetchResult:
        if self.mode == "never":
            return self.http.get(url)
        if self.browser is None:
            if self.mode == "always":
                raise BrowserError(
                    "browser mode requested but Chromium is not available. "
                    "Run: pip install web-gather[browser]; playwright install chromium"
                )
            return self.http.get(url)
        if self.mode == "always":
            return self.browser.get(url)
        # auto: fast HTTP first, browser for shells/failures
        try:
            result = self.http.get(url)
        except Exception:  # noqa: BLE001
            return self.browser.get(url)
        if (
            result.status_code == 200
            and len(result.text) > 400
            and not looks_like_js_shell(result.text)
        ):
            return result
        return self.browser.get(url)