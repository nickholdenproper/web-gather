"""MCP (Model Context Protocol) server - connect any AI to web-gather.

Run: ``webgather mcp`` (stdio by default) or ``webgather mcp --transport sse``.
Works in Claude Desktop, Cursor and other MCP clients. Optional extra:
``pip install web-gather[mcp]`` (the mcp package is free/MIT).
"""

from __future__ import annotations

import sys
from typing import List, Optional

from .llm import resolve_client
from .tools import call_tool


def create_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "MCP support not installed. Run: pip install web-gather[mcp]"
        ) from exc

    mcp = FastMCP("web-gather")

    @mcp.tool()
    def web_search(query: str, engine: str = "auto", limit: int = 8) -> dict:
        """Search the web for free and return ranked results (no API keys)."""
        return call_tool("web_search", {"query": query, "engine": engine, "limit": limit})

    @mcp.tool()
    def fetch_url(url: str, browser_mode: str = "auto") -> dict:
        """Open a page like a human browser and return cleaned text + metadata."""
        return call_tool("fetch_url", {"url": url, "browser_mode": browser_mode})

    @mcp.tool()
    def crawl(sources: List[str], max_pages: int = 20, browser_mode: str = "auto") -> dict:
        """Crawl seeds (URLs, feeds, sitemaps) and build an article corpus."""
        return call_tool(
            "crawl", {"sources": sources, "max_pages": max_pages, "browser_mode": browser_mode}
        )

    @mcp.tool()
    def research(goal: str, max_sites: int = 6, browser_mode: str = "auto", use_llm: bool = True) -> dict:
        """Autonomously research a goal: plan searches, pick best sites, extract verifiable evidence."""
        llm = resolve_client() if use_llm else None
        return call_tool(
            "research",
            {"goal": goal, "max_sites": max_sites, "browser_mode": browser_mode},
            llm=llm,
        )

    return mcp


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("stdio", "sse") else "stdio"
    mcp = create_mcp_server()
    if transport == "sse":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")