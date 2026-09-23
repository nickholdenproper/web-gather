"""Write scraped corpus to disk: per-article JSON + Markdown, index and a
plain-text corpus dump."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Article, CrawlStatus


def write_outputs(
    out_dir: Path,
    articles: list[Article],
    status: CrawlStatus,
    opts: dict,
) -> list[Path]:
    """Write all corpus files; returns created paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    index = {
        "crawl": status.to_dict(),
        "options": opts,
        "articles": [a.to_dict() for a in articles],
    }
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(index_path)

    for i, article in enumerate(articles, start=1):
        slug = _slug(article.title or article.url) or f"article-{i}"
        base = out_dir / f"{i:04d}-{slug}"
        json_path = base.with_suffix(".json")
        json_path.write_text(
            json.dumps(article.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(json_path)
        md_path = base.with_suffix(".md")
        md_path.write_text(_article_markdown(article), encoding="utf-8")
        written.append(md_path)

    corpus_path = out_dir / "corpus.txt"
    corpus_path.write_text(_corpus(articles), encoding="utf-8")
    written.append(corpus_path)

    return written


def _slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60]


def _article_markdown(article: Article) -> str:
    lines = [f"# {article.title or article.url}", ""]
    if article.byline:
        lines.append(f"- By: {article.byline}")
    if article.published_utc:
        lines.append(f"- Published: {article.published_utc}")
    if article.domain:
        lines.append(f"- Domain: {article.domain}")
    if article.summary:
        lines.append("")
        lines.append(f"> {article.summary}")
    if article.body_md:
        lines += ["", article.body_md]
    else:
        lines += ["", "(no clean text extracted)"]
    if article.images:
        lines += ["", "## Images", ""]
        lines += [f"- {url}" for url in article.images]
    return "\n".join(lines)


def _corpus(articles: list[Article]) -> str:
    """Concatenated plain-text corpus (LLM-training-dump style)."""
    blocks: list[str] = []
    for article in articles:
        if not article.text:
            continue
        blocks.append(
            "<article>\n"
            f"<url>{article.url}</url>\n"
            f"<title>{article.title or ''}</title>\n"
            f"<text>\n{article.text}\n</text>\n"
            "</article>"
        )
    return "\n\n".join(blocks)