"""URL discovery: seed expansion via RSS/Atom feeds, sitemaps and in-page links."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def is_feed_payload(body: str) -> bool:
    head = body[:2000].lstrip().lower()
    return head.startswith("<?xml") and "<rss" in head or "<feed" in head


def feed_entries(html_or_xml: str) -> list[str]:
    """Return article URLs from an RSS/Atom feed body."""
    import feedparser  # local import keeps crawler start cheap

    parsed = feedparser.parse(html_or_xml)
    urls: list[str] = []
    for entry in parsed.entries:
        if getattr(entry, "link", None):
            urls.append(entry.link)
    return urls


def sitemap_urls(xml: str, base_url: str) -> tuple[list[str], list[str]]:
    """Parse a sitemap: return (page_urls, nested_sitemap_urls)."""
    soup = BeautifulSoup(xml, "xml")
    pages: list[str] = []
    nested: list[str] = []
    root = soup.find()
    is_index = root is not None and root.name == "sitemapindex"
    for loc in soup.find_all("loc"):
        url = urljoin(base_url, loc.get_text(strip=True))
        if urlparse(url).scheme in ("http", "https"):
            (nested if is_index else pages).append(url)
    return pages, nested


def page_links(html: str, base_url: str) -> list[str]:
    """Extract absolute http(s) links from a page body (for frontier crawling)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        real = urljoin(base_url, a["href"].strip())
        if urlparse(real).scheme in ("http", "https"):
            out.append(real)
    return out


_SITEMAP_RE = re.compile(r"sitemap[^/.\\\\]*\.xml$", re.I)


def looks_like_sitemap(url: str) -> bool:
    return bool(_SITEMAP_RE.search(urlparse(url).path))


def looks_like_feed(url: str) -> bool:
    return urlparse(url).path.rstrip("/").endswith(("/feed", "/rss", "/atom", ".xml"))