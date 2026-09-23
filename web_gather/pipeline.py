"""Crawl orchestration: frontier, discovery loop, extraction, dedupe, outputs."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .dedupe import content_fingerprint, normalize_url
from .discover import (
    feed_entries,
    is_feed_payload,
    looks_like_feed,
    looks_like_sitemap,
    page_links,
    sitemap_urls,
)
from .extract import extract_page
from .fetch import Fetcher, host_of, same_domain
from .models import Article, CrawlStatus

DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_DEPTH = 3


class PipelineOptions:
    def __init__(
        self,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        same_domain: bool = True,
        delay: float = 1.0,
        concurrency: int = 4,
        timeout: float = 20.0,
        retries: int = 2,
        ignore_robots: bool = False,
        follow_feed_sitemap: bool = True,
        out_dir: Optional[Path] = None,
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.delay = delay
        self.concurrency = concurrency
        self.timeout = timeout
        self.retries = retries
        self.ignore_robots = ignore_robots
        self.follow_feed_sitemap = follow_feed_sitemap
        self.out_dir = out_dir or Path.cwd() / "output"


class PipelineResult:
    def __init__(self, articles: list[Article], status: CrawlStatus, written: list[Path]):
        self.articles = articles
        self.status = status
        self.written = written

    def to_dict(self) -> dict:
        return {
            "status": self.status.to_dict(),
            "articles": [a.to_dict() for a in self.articles],
            "written": [str(w) for w in self.written],
        }


def crawl(
    sources: list[str],
    opts: Optional[PipelineOptions] = None,
    fetcher: Optional[Fetcher] = None,
) -> PipelineResult:
    """Crawl ``sources`` (URLs, feeds, sitemaps) and return processed articles."""
    opts = opts or PipelineOptions()
    fetcher = fetcher or Fetcher(
        delay=opts.delay,
        concurrency_per_domain=2,
        timeout=opts.timeout,
        retries=opts.retries,
        ignore_robots=opts.ignore_robots,
    )

    status = CrawlStatus(queued=len(sources))
    state_lock = threading.Lock()
    stats_lock = threading.Lock()

    def bump(**changes) -> None:
        with stats_lock:
            for key, value in changes.items():
                setattr(status, key, getattr(status, key) + value)

    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    results: list[Article] = []
    frontier: "queue.Queue[tuple[str, int]]" = queue.Queue()

    def enqueue(url: str, depth: int) -> None:
        norm = normalize_url(url)
        with state_lock:
            if norm in seen_urls:
                return
            seen_urls.add(norm)
        if depth > opts.max_depth:
            bump(skipped_depth=1)
            return
        frontier.put((url, depth))

    def read_feed_or_sitemap(url: str, body: str) -> None:
        if is_feed_payload(body):
            for entry in feed_entries(body):
                enqueue(entry, 1)
        elif looks_like_sitemap(url):
            pages, nested = sitemap_urls(body, url)
            for page in pages:
                enqueue(page, 1)
            for sub in nested:
                enqueue(sub, 0)

    def process(url: str, depth: int) -> Optional[Article]:
        now = datetime.now(timezone.utc).isoformat()
        try:
            raw = fetcher.get(url)
            if raw.status_code != 200:
                raise IOError(f"HTTP {raw.status_code}")
            body = raw.text

            if opts.follow_feed_sitemap:
                read_feed_or_sitemap(url, body)

            domain = host_of(raw.url)
            extracted = extract_page(body, raw.url)
            text = (extracted.get("text") or "").strip()
            if not text:
                return Article(
                    url=raw.url,
                    domain=domain,
                    status="empty",
                    error="no clean text extracted",
                    title=extracted.get("title"),
                    fetched_at=now,
                )

            fp = content_fingerprint(text)
            with state_lock:
                dup = fp and fp in seen_hashes
                if not dup and fp:
                    seen_hashes.add(fp)
            if dup:
                bump(duplicates=1)
                return None

            links = []
            for link in page_links(body, raw.url):
                if opts.same_domain and not same_domain(raw.url, link):
                    continue
                links.append(link)
                enqueue(link, depth + 1)

            return Article(
                url=raw.url,
                domain=domain,
                canonical=normalize_url(extracted.get("canonical") or raw.url),
                title=extracted.get("title"),
                byline=extracted.get("byline"),
                published_utc=extracted.get("published_utc"),
                language=extracted.get("language"),
                summary=extracted.get("summary"),
                text=extracted.get("text"),
                body_md=extracted.get("body_md"),
                headings=extracted.get("headings") or [],
                links=links,
                images=extracted.get("images") or [],
                fetched_at=now,
                content_hash=fp,
            )
        except Exception as exc:  # noqa: BLE001 - one bad page mustn't kill the crawl
            return Article(
                url=url,
                domain=host_of(url),
                status="error",
                error=str(exc),
                fetched_at=now,
            )

    def store(article: Optional[Article]) -> None:
        if article is None:
            return
        with state_lock:
            results.append(article)
        bump(visited=1)
        if article.status == "ok":
            bump(ok=1)
        elif article.status == "empty":
            bump(empty=1)
        else:
            bump(errors=1)

    for src in sources:
        enqueue(src, 0)

    with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
        pending: dict = {}
        while True:
            # Top up the pool from the frontier.
            while (
                len(pending) < max(1, opts.concurrency) and not frontier.empty() and status.visited < opts.max_pages
            ):
                url, depth = frontier.get_nowait()
                pending[pool.submit(process, url, depth)] = url
            if not pending:
                break  # nothing running and nothing queued -> done
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                store(fut.result())
                pending.pop(fut)

    from .output import write_outputs

    written = write_outputs(opts.out_dir, results, status, _opts_dict(opts))
    return PipelineResult(results, status, written)


def _opts_dict(opts: PipelineOptions) -> dict:
    return {
        "max_pages": opts.max_pages,
        "max_depth": opts.max_depth,
        "same_domain": opts.same_domain,
        "delay": opts.delay,
        "concurrency": opts.concurrency,
        "timeout": opts.timeout,
        "retries": opts.retries,
        "ignore_robots": opts.ignore_robots,
        "follow_feed_sitemap": opts.follow_feed_sitemap,
        "out_dir": str(opts.out_dir),
    }