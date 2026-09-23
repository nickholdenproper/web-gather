"""Site-agnostic content extraction - the "LLM-style" reader.

Primary: trafilatura (density-based, no site-specific selectors).
Fallback: readability-lxml when trafilatura finds nothing article-like.
Metadata enrichment: JSON-LD, OpenGraph and <meta> for title/byline/date/image.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def _json_texts(html: str) -> list[dict]:
    """Pull JSON-LD blocks out of the page."""
    blocks = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.S,
    )
    out: list[dict] = []
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, list):
            out.extend(data)
        elif isinstance(data, dict):
            out.append(data)
    return out


def _first(entries: list, key: str) -> Optional[str]:
    for e in entries:
        value = e.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0].strip()
    return None


def _byline_text(value) -> Optional[str]:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    names.append(name)
        return ", ".join(names) or None
    return None


def _normalize_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    # Keep only the leading ISO-ish token (no parsing of exotic formats).
    m = re.match(r"(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?)", value.strip())
    return m.group(1) if m else value.strip()


def extract_page(html: str, base_url: str) -> dict:
    """Return a dict with text, body_md, title, byline, published_utc,
    language, summary, headings, links, images."""

    result: dict = {
        "text": None,
        "body_md": None,
        "title": None,
        "byline": None,
        "published_utc": None,
        "language": None,
        "summary": None,
        "headings": [],
        "links": [],
        "images": [],
    }

    # 1) trafilatura first - the general-purpose extractor.
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata
        from trafilatura.settings import use_config

        cfg = use_config()
        cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "10")
        extracted = trafilatura.extract(
            html, include_links=True, favor_precision=True, config=cfg
        )
        result["text"] = extracted.strip() if extracted else None
        result["body_md"] = result["text"]
        meta = extract_metadata(html, default_url=base_url)
        if meta is not None:
            result["title"] = meta.title
            result["byline"] = meta.author
            result["published_utc"] = _normalize_date(meta.date)
            result["language"] = meta.language
            if meta.description:
                result["summary"] = meta.description.strip()
    except Exception:  # noqa: BLE001 - fall back to readability
        result["text"] = None

    # 2) readability fallback when trafilatura found nothing.
    if not result["text"]:
        try:
            from readability import Document

            doc = Document(html, url=base_url)
            cleaned = doc.summary(html_partial=True)
            result["body_md"] = _html_to_markdown(cleaned, base_url)
            if not result["title"]:
                result["title"] = doc.short_title()
        except Exception:  # noqa: BLE001
            pass

    # 3) metadata enrichment from JSON-LD / OpenGraph.
    ld = _json_texts(html)
    ld_date = _normalize_date(_first(ld, "datePublished"))
    if not result["title"]:
        result["title"] = _first(ld, "headline")
    if not result["byline"]:
        author = None
        for e in ld:
            if isinstance(e.get("author"), dict):
                author = e["author"].get("name")
            elif isinstance(e.get("author"), list):
                author = _byline_text(e["author"])
            if author:
                break
        result["byline"] = author
    if ld_date:
        # JSON-LD carries the precise instant; trafilatura only gives the date.
        result["published_utc"] = ld_date
    if not result["summary"]:
        result["summary"] = _first(ld, "description")

    # 4) DOM pass for headings / links / images / OG-sourced fields.
    soup = _soup(html)

    og_title = _og(soup, "og:title")
    if og_title and not result["title"]:
        result["title"] = og_title
    og_image = _og(soup, "og:image")
    if og_image:
        result["images"].append(urljoin(base_url, og_image))
    if not result["summary"]:
        og_desc = _og(soup, "og:description")
        if og_desc:
            result["summary"] = og_desc
    og_time = _og(soup, "article:published_time")
    if og_time:
        result["published_utc"] = _normalize_date(og_time)
    if not result["byline"]:
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            result["byline"] = meta_author["content"].strip()

    for h in soup.find_all(["h1", "h2", "h3"]):
        text = " ".join(h.get_text(" ", strip=True).split())
        if text:
            result["headings"].append(f"{h.name.upper()}: {text}")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        real = urljoin(base_url, href)
        if urlparse(real).scheme in ("http", "https"):
            result["links"].append(real)

    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        real = urljoin(base_url, src)
        if urlparse(real).scheme in ("http", "https"):
            if real not in result["images"]:
                result["images"].append(real)

    # Min-length guard: parked/nav-only fragments aren't articles.
    if result["text"] and len(result["text"].strip()) < 40:
        result["text"] = None
        result["body_md"] = None

    # Summary fallback: first sentences of clean text.
    if not result["summary"] and result["text"]:
        plain = re.sub(r"\s+", " ", result["text"]).strip()
        if len(plain) > 300:
            result["summary"] = plain[:300].rsplit(".", 1)[0] + "."
        else:
            result["summary"] = plain[:300]

    return result


def _soup(html: str):
    import warnings

    from bs4 import XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, "html.parser")


def _og(soup, prop: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find(
        "meta", attrs={"name": prop}
    )
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _html_to_markdown(html: str, base_url: str) -> str:
    """Crude-but-safe HTML->Markdown for the readability fallback path."""
    soup = BeautifulSoup(html, "html.parser")
    md_lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "pre"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text:
            continue
        if el.name in ("h1", "h2", "h3"):
            md_lines.append(f"{'#' * int(el.name[1])} {text}")
        elif el.name in ("p", "blockquote"):
            md_lines.append(f"> {text}" if el.name == "blockquote" else text)
        elif el.name == "li":
            md_lines.append(f"- {text}")
        elif el.name == "pre":
            md_lines.append(f"```\n{text}\n```")
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if text:
            md_lines.append(f"[{text}]({urljoin(base_url, a['href'])})")
    return "\n\n".join(md_lines)