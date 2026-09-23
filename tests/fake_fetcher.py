"""Shared fake fetcher for offline pipeline tests."""

from __future__ import annotations

from web_gather.fetch import FetchResult


class FakeFetcher:
    """In-memory fetcher: maps url -> (status, headers, body)."""

    def __init__(self, pages: dict | None = None):
        self.pages: dict[str, tuple[int, dict, str]] = pages or {}
        self.requests: list[str] = []
        self.blocked: set[str] = set()

    def add(self, url: str, body: str, status: int = 200, headers: dict | None = None) -> None:
        self.pages[url] = (status, headers or {"content-type": "text/html"}, body)

    def get(self, url: str) -> FetchResult:
        self.requests.append(url)
        if url in self.blocked:
            raise OSError("blocked")
        status, headers, body = self.pages.get(
            url, (404, {"content-type": "text/html"}, "not found")
        )
        # follow plain redirects for tests that rely on it
        while status in (301, 302) and headers.get("location"):
            url = headers["location"]
            if url in self.blocked:
                raise OSError("blocked")
            status, headers, body = self.pages.get(
                url, (404, {"content-type": "text/html"}, "not found")
            )
        return FetchResult(url=url, status_code=status, headers=headers, text=body)