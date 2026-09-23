"""Fetching with politeness: retries, browser-like UA, robots.txt and
per-domain rate limits. All courtesy checks are on by default but can be
disabled explicitly (``ignore_robots``) - the user owns their compliance.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib import robotparser
from urllib.parse import urlparse

USER_AGENT = "web-gather/0.1 (+friendly open web crawler)"


@dataclass
class FetchResult:
    url: str
    status_code: int
    headers: dict
    text: str


class Fetcher:
    """HTTP fetcher with retries, polite per-domain pacing and opt-in robots."""

    def __init__(
        self,
        delay: float = 1.0,
        concurrency_per_domain: int = 2,
        timeout: float = 20.0,
        retries: int = 2,
        ignore_robots: bool = False,
        user_agent: str = USER_AGENT,
    ):
        self.delay = delay
        self.concurrency_per_domain = max(1, concurrency_per_domain)
        self.timeout = timeout
        self.retries = retries
        self.ignore_robots = ignore_robots
        self.user_agent = user_agent

        import httpx  # local import keeps module import cheap when not fetching

        self._httpx = httpx
        self._robots_cache: dict[str, Optional[robotparser.RobotFileParser]] = {}
        self._lock = threading.Lock()
        self._last_fetch: dict[str, float] = {}
        self._active: dict[str, int] = {}

    def _httpx_get(self, url: str) -> FetchResult:
        with self._httpx.Client(
            follow_redirects=True,
            timeout=self._httpx.Timeout(self.timeout),
            headers={"User-Agent": self.user_agent},
        ) as client:
            resp = client.get(url)
            return FetchResult(
                url=str(resp.url),
                status_code=resp.status_code,
                headers=dict(resp.headers),
                text=resp.text,
            )

    def _can_start(self, netloc: str) -> bool:
        with self._lock:
            if self._active.get(netloc, 0) >= self.concurrency_per_domain:
                return False
            self._active[netloc] = self._active.get(netloc, 0) + 1
            return True

    def _finish(self, netloc: str) -> None:
        with self._lock:
            self._active[netloc] = max(0, self._active.get(netloc, 0) - 1)

    def _pace(self, netloc: str) -> None:
        while not self._can_start(netloc):
            time.sleep(0.1)
        with self._lock:
            last = self._last_fetch.get(netloc, 0.0)
            now = time.monotonic()
            wait = self.delay - (now - last)
        if wait > 0:
            time.sleep(wait)
        with self._lock:
            self._last_fetch[netloc] = time.monotonic()

    def _robots(self, netloc: str) -> Optional[robotparser.RobotFileParser]:
        with self._lock:
            if netloc not in self._robots_cache:
                self._robots_cache[netloc] = self._load_robots(netloc)
            return self._robots_cache[netloc]

    def _load_robots(self, netloc: str) -> Optional[robotparser.RobotFileParser]:
        rp = robotparser.RobotFileParser()
        try:
            result = self._httpx_get(f"https://{netloc}/robots.txt")
            rp.parse(result.text.splitlines())
            return rp
        except Exception:  # noqa: BLE001 - robots failures never block crawling
            return None

    def _allowed(self, url: str) -> bool:
        if self.ignore_robots:
            return True
        rp = self._robots(urlparse(url).netloc)
        return rp is None or rp.can_fetch(self.user_agent, url)

    def get(self, url: str) -> FetchResult:
        """Fetch ``url`` with per-domain pacing, robots check and retries."""
        netloc = urlparse(url).netloc
        self._pace(netloc)
        try:
            if not self._allowed(url):
                raise PermissionError(f"blocked by robots.txt: {url}")
            last_exc: Optional[Exception] = None
            for attempt in range(self.retries + 1):
                try:
                    result = self._httpx_get(url)
                    if result.status_code >= 500 and attempt < self.retries:
                        raise IOError(f"server error {result.status_code}")
                    return result
                except PermissionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    time.sleep(0.5 * (attempt + 1))
            raise IOError(f"fetch failed: {last_exc}")
        finally:
            self._finish(netloc)


def host_of(url: str) -> str:
    return urlparse(url).netloc


def same_domain(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc