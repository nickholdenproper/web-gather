"""Shared data models for scraped documents."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Article:
    """A normalized scraped document."""

    url: str
    domain: str
    status: str = "ok"  # ok | error | empty
    error: Optional[str] = None
    title: Optional[str] = None
    canonical: Optional[str] = None
    byline: Optional[str] = None
    published_utc: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    text: Optional[str] = None
    body_md: Optional[str] = None
    headings: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    fetched_at: str = ""
    content_hash: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CrawlStatus:
    """Discovered vs produced counts for a crawl run."""

    queued: int = 0
    visited: int = 0
    ok: int = 0
    empty: int = 0
    errors: int = 0
    duplicates: int = 0
    blocked: int = 0
    skipped_depth: int = 0

    def to_dict(self) -> dict:
        return asdict(self)