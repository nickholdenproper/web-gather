"""Free web search - no API keys.

Keyless HTTP engines: DuckDuckGo HTML, Google News RSS, Bing News RSS, Mojeek,
Marginalia, Reddit JSON. Browser engines require the real-browser mode:
``google`` (real Google SERP, opt-in), ``ddg-browser``. ``auto`` tries the
keyless engines in priority order and merges results (cross-engine agreement
is later used by the selector).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import parse_qs, quote, urlparse

import feedparser
from bs4 import BeautifulSoup

from .blocks import BlockList
from .browser import BrowserSession

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

KEYLESS_ENGINES = ("ddg", "googlenews", "bingnews", "mojeek", "marginalia", "reddit")
BROWSER_ENGINES = ("google", "ddg-browser")
ALL_ENGINES = KEYLESS_ENGINES + BROWSER_ENGINES


@dataclass
class SearchResult:
    engine: str
    title: str
    url: str
    snippet: str
    position: int
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


GetBody = Callable[[str], str]


def _plain_get(url: str) -> str:
    import httpx

    resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


# ---------- parsers (testable off-network on fixtures) ----------

def parse_ddg(html: str, engine: str = "ddg") -> list["SearchResult"]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for i, a in enumerate(soup.select("a.result__a")):
        url = a.get("href")
        if not url:
            continue
        url = _real_url(url)
        if url.startswith("//") or not urlparse(url).scheme:
            url = "https:" + url if url.startswith("//") else "https://" + url
        title = " ".join(a.get_text(" ", strip=True).split())
        parent = a.find_parent()
        snippet_el = parent.find(class_="result__snippet") if parent else None
        snippet = " ".join(snippet_el.get_text(" ", strip=True).split()) if snippet_el else ""
        out.append(SearchResult(engine, title, url, snippet, i + 1))
    return out


def _real_url(href: str) -> str:
    """Unwrap DuckDuckGo /l/?uddg=... redirect links to the real target URL.

    DDG serves results via https://duckduckgo.com/l/?uddg=<urlencode(target)>;
    fetching those links asks DuckDuckGo's robots.txt (which forbids /l/) and
    breaks the crawl. The underlying engines return real links already.
    """
    parsed = urlparse(href)
    if parsed.netloc == "duckduckgo.com" and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def parse_feed(body: str, engine: str) -> list["SearchResult"]:
    parsed = feedparser.parse(body)
    out = []
    for i, entry in enumerate(parsed.entries):
        url = getattr(entry, "link", None)
        if not url:
            continue
        title = getattr(entry, "title", "") or ""
        snippet = (getattr(entry, "summary", "") or "")
        snippet = re.sub(r"<[^>]+>", " ", snippet)
        snippet = " ".join(snippet.split())[:300]
        out.append(SearchResult(engine, title, url, snippet, i + 1))
    return out


def parse_mojeek(html: str, engine: str = "mojeek") -> list["SearchResult"]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for i, li in enumerate(soup.select("ul.results li")):
        a = li.find("h2")
        a = a.find("a") if a else None
        if a is None:
            a = li.find("a", href=True)
        if not a or not a.get("href"):
            continue
        p = li.find("p", class_="s")
        snippet = " ".join(p.get_text(" ", strip=True).split()) if p else ""
        title = " ".join(a.get_text(" ", strip=True).split()) or snippet[:80]
        out.append(SearchResult(engine, title, a["href"], snippet, i + 1))
    return out


def parse_marginalia(html: str, engine: str = "marginalia") -> list["SearchResult"]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    items = soup.select(".search-result")
    if not items:
        items = soup.select(".results .result")
    for i, item in enumerate(items):
        a = item.select_one(".title a, a[href]")
        if not a or not a.get("href"):
            continue
        snippets = item.select_one("p, .snippet")
        snippet = " ".join(snippets.get_text(" ", strip=True).split()) if snippets else ""
        title = " ".join(a.get_text(" ", strip=True).split()) or snippet[:80]
        out.append(SearchResult(engine, title, a["href"], snippet, i + 1))
    return out


def parse_reddit_json(text: str, engine: str = "reddit") -> list["SearchResult"]:
    import json

    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    out = []
    children = (data.get("data") or {}).get("children") or []
    for i, child in enumerate(children):
        post = (child.get("data") or {} if isinstance(child, dict) else {})
        url = post.get("url")
        title = post.get("title")
        if not url:
            continue
        snippet = (post.get("selftext") or "")[:300]
        out.append(SearchResult(engine, title or "", url, snippet, i + 1))
    return out


# ---------- engine registry ----------

def _keyless(query: str, engine: str) -> Optional[tuple[str, Callable[[str], list["SearchResult"]]]]:
    q = quote(query)
    if engine == "ddg":
        return f"https://html.duckduckgo.com/html/?q={q}", parse_ddg
    if engine == "googlenews":
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        return url, lambda body: parse_feed(body, "googlenews")
    if engine == "bingnews":
        return f"https://www.bing.com/news/search?q={q}&format=rss", lambda body: parse_feed(body, "bingnews")
    if engine == "mojeek":
        return f"https://www.mojeek.com/search?q={q}", parse_mojeek
    if engine == "marginalia":
        return f"https://search.marginalia.nu/search?query={q}", parse_marginalia
    if engine == "reddit":
        return f"https://www.reddit.com/search.json?q={q}&limit=25&sort=relevance", parse_reddit_json
    return None


# ---------- main entry points ----------

def search_web(
    query: str,
    engine: str = "auto",
    limit: int = 10,
    get_body: Optional[GetBody] = None,
    blocklist: Optional[BlockList] = None,
) -> list[SearchResult]:
    """Search free engines and return deduplicated ranked results."""
    get_body = get_body or _plain_get
    block = blocklist or BlockList()

    if engine in KEYLESS_ENGINES:
        builder = _keyless(query, engine)
        results = _run_one(builder, get_body, block)
    elif engine in BROWSER_ENGINES:
        raise RuntimeError(
            f"engine '{engine}' needs a browser session; pass one to search_browser()."
        )
    else:  # auto: merge in priority order, keep the best N
        results = []
        for name in KEYLESS_ENGINES:
            builder = _keyless(query, name)
            results.extend(_run_one(builder, get_body, block))
            if len(results) >= limit:
                break
    return _dedupe(results)[:limit]


def search_browser(
    session: BrowserSession,
    query: str,
    engine: str = "google",
    limit: int = 10,
    blocklist: Optional[BlockList] = None,
) -> list[SearchResult]:
    """Search via the real browser (Google SERP or DuckDuckGo)."""
    block = blocklist or BlockList()
    raw = session.search(engine, query, limit + 5)
    results = [
        SearchResult(engine, title, url, snippet, pos)
        for pos, (title, url, snippet) in enumerate(raw, start=1)
    ]
    results = [r for r in results if not block.blocks(r.url)]
    return _dedupe(results)[:limit]


def _run_one(
    builder: Optional[tuple[str, Callable[[str], list["SearchResult"]]]],
    get_body: GetBody,
    block: BlockList,
) -> list[SearchResult]:
    if not builder:
        return []
    url, parser = builder
    try:
        body = get_body(url)
        results = parser(body)
    except Exception:  # noqa: BLE001 - a single failed engine never kills a search
        return []
    return [r for r in results if not block.blocks(r.url)]


def _dedupe(results: list[SearchResult]) -> list[SearchResult]:
    from .dedupe import normalize_url

    seen = set()
    out = []
    for r in results:
        n = normalize_url(r.url) or r.url
        if n in seen:
            continue
        seen.add(n)
        out.append(r)
    return out