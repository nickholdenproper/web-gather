"""webgather command-line interface."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import List, Optional

import typer

from . import __version__
from .llm import resolve_client
from .pipeline import PipelineOptions, crawl
from .research import ResearchOptions
from .research import research as run_research
from .search import KEYLESS_ENGINES, search_web

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is a core dep; keep CLI usable
    pass

app = typer.Typer(
    help="LLM-style web scraper & research agent - crawl feeds/sitemaps/links, "
    "search the web free (no API keys), and research goals into verifiable "
    "evidence. Browser/Search GUI + REST API + MCP tools.",
    add_completion=False,
)

_SEARCH_ENGINES = "auto|ddg|googlenews|bingnews|mojeek|marginalia|reddit|google|ddg-browser"


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
    browser_mode: str = typer.Option(
        "auto",
        "--browser",
        help="auto (HTTP first, browser only when needed) | always | never.",
    ),
    block: str = typer.Option("", "--block", help="Comma-separated domains/globs to block."),
    allow_only: str = typer.Option("", "--allow-only", help="Comma-separated domains/globs to allow only."),
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
        browser_mode=browser_mode,
        blocked=_split(block),
        allowed=_split(allow_only),
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
def search(
    query: str = typer.Argument(..., help="Search query."),
    engine: str = typer.Option("auto", "--engine", help=_SEARCH_ENGINES),
    limit: int = typer.Option(8, "--limit", help="Max results."),
    block: str = typer.Option("", "--block", help="Comma-separated domains/globs to block."),
) -> None:
    """Search the web free - no API keys (browser engines optional)."""
    from .blocks import BlockList

    if engine == "google" and __import__("os").getenv("WEBGATHER_GOOGLE_ENGINE") != "1":
        typer.echo(
            "google engine is off by default (ToS/politeness). Use "
            "WEBGATHER_GOOGLE_ENGINE=1 to enable it (requires the browser mode)."
        )
        engine = "auto"
    results = search_web(query, engine=engine, limit=limit, blocklist=BlockList(blocked=_split(block)))
    typer.echo(f"engine={engine} results={len(results)}")
    for i, r in enumerate(results, start=1):
        typer.echo(f"  {i}. {r.title}")
        typer.echo(f"     {r.url}")
        if r.snippet:
            typer.echo(f"     {r.snippet[:160]}")


@app.command()
def research(
    goal: str = typer.Argument(..., help="Research goal; e.g. What are the newest leaks on Windows 13?"),
    engine: str = typer.Option("auto", "--engine", help=_SEARCH_ENGINES),
    max_sites: int = typer.Option(6, "--max-sites", help="Pages to read."),
    min_score: int = typer.Option(30, "--min-score", help="Site selection cutoff."),
    browser_mode: str = typer.Option("auto", "--browser", help="auto | always | never"),
    use_llm: bool = typer.Option(
        False,
        "--llm",
        help="Use a free Ollama model (cloud with OLLAMA_API_KEY, or local) for "
        "planning, extraction and the summary report.",
    ),
) -> None:
    """Research a goal into verifiable evidence (heuristic by default)."""
    llm = resolve_client() if use_llm else None
    opts = ResearchOptions(
        goal=goal,
        engine=engine,
        min_score=min_score,
        browser_mode=browser_mode,
        use_llm=use_llm,
    )
    typer.echo(f"researching: {goal}")
    result = run_research(goal, opts, llm=llm)
    typer.echo(f"queries: {result.queries}")
    typer.echo(f"sites selected: {len(result.selected)}")
    for i, item in enumerate(result.findings, start=1):
        typer.echo(f"  {i}. [{item.confidence:.2f}] {item.finding}")
        if item.quote:
            typer.echo(f"     \"{item.quote[:120]}...\"")
        typer.echo(f"     {item.source_url}")
    typer.echo(f"wrote {len(result.written)} files")
    for path in result.written:
        typer.echo(f"  {path}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8001, "--port"),
    open_browser: bool = typer.Option(False, "--open", "-O", help="Open the web GUI in a browser."),
    cors_origin: List[str] = typer.Option(
        None, "--cors-origin", help="Restrict CORS to this origin (repeatable). Default: open (*)."
    ),
) -> None:
    """Serve the web GUI + REST API + MCP-friendly endpoints."""
    import uvicorn

    from .api import create_app

    cors = list(cors_origin) or None
    app = create_app(cors_origins=cors)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{_host(host)}:{port}/")).start()
    uvicorn.run(app, host=host, port=port)


def _split(value: str) -> Optional[List[str]]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _host(host: str) -> str:
    return host if host not in ("0.0.0.0", "::") else "127.0.0.1"


def _report(result) -> None:
    s = result.status
    typer.echo(
        f"visited={s.visited} ok={s.ok} empty={s.empty} errors={s.errors} "
        f"duplicates={s.duplicates} blocked={s.blocked} skipped_depth={s.skipped_depth}"
    )
    typer.echo(f"wrote {len(result.written)} files to output")
    for path in result.written:
        typer.echo(f"  {path}")


if __name__ == "__main__":
    app()