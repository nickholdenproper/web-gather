"""webgather command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from . import __version__
from .pipeline import PipelineOptions, crawl

app = typer.Typer(
    help="LLM-style web scraper - crawl feeds/sitemaps/links, clean pages to "
    "readable articles and build a plain-text corpus. Free, no API keys.",
    add_completion=False,
)


@app.command("crawl")
def crawl_cmd(
    sources: List[str] = typer.Argument(
        ..., help="Seed URLs - pages, RSS/Atom feeds, or sitemap.xml files."
    ),
    max_pages: int = typer.Option(50, "--max-pages", help="Stop after N visited URLs."),
    max_depth: int = typer.Option(3, "--max-depth", help="Max link-following depth."),
    any_domain: bool = typer.Option(
        False, "--any-domain", help="Allow leaving the seed domains (default: same-domain only)."
    ),
    delay: float = typer.Option(1.0, "--delay", help="Polite delay seconds between requests to one domain."),
    concurrency: int = typer.Option(4, "--concurrency", help="Parallel workers."),
    timeout: float = typer.Option(20.0, "--timeout", help="Per-request timeout seconds."),
    retries: int = typer.Option(2, "--retries", help="Retries on 5xx/network errors."),
    ignore_robots: bool = typer.Option(
        False, "--ignore-robots", help="Disable robots.txt honoring (use responsibly)."
    ),
    out_dir: Path = typer.Option(
        Path("output"), "--out", "--out-dir", help="Directory to write corpus output."
    ),
) -> None:
    """Crawl one or more seeds and write a corpus to --out."""
    opts = PipelineOptions(
        max_pages=max_pages,
        max_depth=max_depth,
        same_domain=not any_domain,
        delay=delay,
        concurrency=concurrency,
        timeout=timeout,
        retries=retries,
        ignore_robots=ignore_robots,
        out_dir=out_dir,
    )
    result = crawl(sources, opts)
    _report(result)


@app.command()
def url(
    url: str,
    out_dir: Path = typer.Option(Path("output"), "--out", "--out-dir"),
) -> None:
    """Scrape a single page."""
    opts = PipelineOptions(max_pages=1, max_depth=0, out_dir=out_dir)
    result = crawl([url], opts)
    _report(result)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8001, "--port"),
) -> None:
    """Serve the REST API (FastAPI) for programmatic crawling."""
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(), host=host, port=port)


def _report(result) -> None:
    s = result.status
    typer.echo(
        f"visited={s.visited} ok={s.ok} empty={s.empty} errors={s.errors} "
        f"duplicates={s.duplicates} skipped_depth={s.skipped_depth}"
    )
    typer.echo(f"wrote {len(result.written)} files to output")
    for path in result.written:
        typer.echo(f"  {path}")


if __name__ == "__main__":
    app()