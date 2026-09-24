"""Machine-readable tools for LLMs and agents.

The same three (well, four) tools are exposed as: JSON schema via ``/v1/tools``
(REST) and as native tools via ``webgather mcp`` (Model Context Protocol), so
any AI - Claude Desktop, Cursor, a custom agent - can search and gather data
with no API keys.
"""

from __future__ import annotations

from typing import Optional

from .browser import BrowserSession
from .llm import LLMClient
from .models import Article
from .pipeline import PipelineOptions, crawl as run_crawl
from .research import ResearchOptions, research as run_research
from .search import search_browser, search_web

TOOLS: list[dict] = [
    {
        "name": "web_search",
        "description": "Search the web for free (no API keys) and return ranked results with titles, URLs and snippets. Engines: auto, ddg, googlenews, bingnews, mojeek, marginalia, reddit, google (browser).",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "engine": {"type": "string", "default": "auto"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Open a page like a human browser (rendered headlessly) and return the cleaned article text plus metadata.",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "browser_mode": {"type": "string", "default": "auto", "enum": ["auto", "always", "never"]},
            },
            "required": ["url"],
        },
    },
    {
        "name": "crawl",
        "description": "Crawl seeds (URLs, RSS/Atom feeds, sitemaps) following same-domain links, and write an article corpus.",
        "schema": {
            "type": "object",
            "properties": {
                "sources": {"type": "array", "items": {"type": "string"}},
                "max_pages": {"type": "integer", "default": 20},
                "browser_mode": {"type": "string", "default": "auto", "enum": ["auto", "always", "never"]},
            },
            "required": ["sources"],
        },
    },
    {
        "name": "research",
        "description": "Fully autonomous research: plans searches from a goal, picks the best sites from many engines, finds goal-relevant evidence on each page, and returns verifiable evidence items.",
        "schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "max_sites": {"type": "integer", "default": 6},
                "browser_mode": {"type": "string", "default": "auto", "enum": ["auto", "always", "never"]},
            },
            "required": ["goal"],
        },
    },
]


def call_tool(name: str, args: dict, llm: Optional[LLMClient] = None, browser: Optional[BrowserSession] = None) -> dict:
    """Execute a tool by name (used by the API and the MCP server)."""
    if name == "web_search":
        results = search_web(
            args["query"],
            engine=args.get("engine", "auto"),
            limit=int(args.get("limit", 8)),
        )
        return {"results": [r.to_dict() for r in results]}

    if name == "fetch_url":
        url = args["url"]
        mode = args.get("browser_mode", "auto")
        from .browser import HybridFetcher
        from .fetch import Fetcher

        fetcher = HybridFetcher(Fetcher(delay=0.5, retries=1), browser, mode)
        raw = fetcher.get(url)
        if raw.status_code != 200:
            return {"url": url, "status": raw.status_code, "error": "non-200 response"}
        from .extract import extract_page

        extracted = extract_page(raw.text, raw.url)
        return {"url": raw.url, "status": raw.status_code, **extracted}

    if name == "crawl":
        opts = PipelineOptions(
            max_pages=int(args.get("max_pages", 20)),
            max_depth=int(args.get("max_depth", 2)),
            browser_mode=args.get("browser_mode", "auto"),
        )
        result = run_crawl(args["sources"], opts, browser=browser)
        return result.to_dict()

    if name == "research":
        opts = ResearchOptions(
            goal=args["goal"],
            max_sites=int(args.get("max_sites", 6)),
            browser_mode=args.get("browser_mode", "auto"),
            use_llm=llm is not None,
        )
        result = run_research(args["goal"], opts, llm=llm, browser=browser)
        return result.to_dict()

    raise KeyError(f"unknown tool: {name}")