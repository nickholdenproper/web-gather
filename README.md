# Web Gather

A free, LLM-style **web search + research agent + scraper**. No API keys, no paid
services, no per-site selectors.

- **Crawl** seeds (pages, RSS/Atom feeds, `sitemap.xml`) into a clean article corpus
  (`index.json`, per-article `.json`/`.md`, `corpus.txt`).
- **Search** the web free across DuckDuckGo, Google News RSS, Bing News RSS, Mojeek,
  Marginalia and Reddit — or real-browser Google/DuckDuckGo (opt-in, headless, never
  opens a window).
- **Research** any goal: plans search queries, picks the best sites across engines,
  reads them, and returns **verifiable evidence** — claim + exact quote + source +
  confidence (`findings.json`, `findings.md`, `report.md`). Heuristic by default;
  optional free LLM via Ollama (cloud or local).
- **Ask** a question: gathers pages, extracts the evidence, and answers in **one
  AI-written paragraph** with sources (free Ollama LLM; falls back to a compiled
  paragraph when unconfigured).
- **Connectable**: browser GUI, REST API with open CORS (any website can call it),
  and an MCP server so Claude/Cursor/any AI can use the tools.

## Quick start

Double-click `run.bat` (Windows) — it sets up a venv and opens the web GUI at
[http://localhost:8001](http://localhost:8001). Everything works with zero setup.

### CLI

```powershell
# Scrape one URL
webgather url https://news.com/story-123

# Crawl a feed + sitemap, follow links
webgather crawl https://news.com/feed https://news.com/sitemap.xml --max-pages 200

# Search the web free
webgather search "newest Windows 13 leaks"

# Research a goal into evidence (heuristic, offline)
webgather research "Are ultra-processed foods linked to heart disease?"

# Ask a question -> one AI-paragraph answer with sources
# (heuristic compiled paragraph until you set OLLAMA_API_KEY in .env)
webgather ask "Are ultra-processed foods linked to heart disease?"

# Research with a free LLM (set OLLAMA_API_KEY in .env for cloud, or run Ollama locally)
webgather research "..." --llm

# Serve web GUI + REST API + open CORS
webgather serve --open

# MCP server for AI clients (stdio; use --transport sse for streamable-http)
webgather mcp
```

Copy `.env.example` to `.env` for the optional LLM (cloud: `OLLAMA_API_KEY`,
default model `gpt-oss:20b-cloud`; or local Ollama at `http://localhost:11434`).

### CLI options (crawl)

| Option | Default | Meaning |
| --- | --- | --- |
| `--max-pages` / `--max-depth` | 50 / 3 | scope of the crawl |
| `--any-domain` | off | allow leaving seed domains (default same-domain only) |
| `--delay` / `--concurrency` | 1.0 / 4 | politeness & parallel workers |
| `--timeout` / `--retries` | 20 / 2 | per-request settings |
| `--ignore-robots` | off | disable robots.txt honoring (use responsibly) |
| `--browser` | auto | `auto` (HTTP first, browser only for JS shells/challenges), `always`, `never` |
| `--block a.com,b.net` | none | domains/globs to never visit |
| `--allow-only a.com` | none | visit ONLY these domains |
| `--out` / `--out-dir` | `output` | corpus destination |

## REST API (`webgather serve`)

CORS is **open by default** so any website can call it; lock it down with
`webgather serve --cors-origin https://yoursite.com` (repeatable).

```
GET  /v1/search?q=...&engine=auto&limit=8       free search (synchronous)
POST /v1/jobs                                   {"sources":[...],"options":{...}}
GET  /v1/jobs/{id}                              status + summary
GET  /v1/jobs/{id}/files/{name}                 download corpus files
POST /v1/search-and-crawl                       search intent -> crawl corpus
GET  /v1/tools                                  machine-readable AI tool schema
POST /v1/research                               {"goal":"...","options":{...}}
GET  /v1/research/{id}                          evidence findings
GET  /v1/research/{id}/files/{name}             findings.json / report.md
POST /v1/ask                                    {"question":"...","use_llm":true} -> one answer paragraph
```

Every run is saved under `api_jobs/<job_id>/` or `research_jobs/<job_id>/`.
Interactive Swagger docs at `/docs`.

## Browser mode

Real Chromium (Playwright, free/MIT) renders pages headlessly — never opens a
window. Optional:

```powershell
pip install web-gather[browser]
playwright install chromium
```

`--browser auto` (default) stays on fast HTTP and only upgrades to a real browser
for JS-heavy shells, bot challenges, or the opt-in Google engine. Sessions can
persist via `--user-data-dir`.

## Free LLM (optional)

Planning queries, extracting exact supporting quotes, and writing the summary
report can use any free Ollama model — cloud
(`OLLAMA_API_KEY` + `OLLAMA_BASE_URL=https://ollama.com`) or local
(`http://localhost:11434`). Without it, everything is deterministic, offline
heuristics: still full searches + evidence, just no prose report.

## How it works

1. **Fetch** — `httpx` with retries, `robots.txt` respect, per-domain pacing; optional headless-browser upgrade via `HybridFetcher`.
2. **Discover** — seeds can be feeds, sitemaps or pages; links extend the frontier up to `--max-depth`.
3. **Search** — keyless engines merged in `auto` mode; blocklist/allowlist enforced before any request, in every mode.
4. **Extract** — site-agnostic readability (`trafilatura`, `readability-lxml` fallback) + JSON-LD/OG/meta enrichment.
5. **Choose** — cross-engine agreement + goal relevance + freshness penalties.
6. **Target** — goal-aware extraction keeps only goal-relevant passages.
7. **Clean+Output** — normalization + fingerprints collapse duplicates; every finding ships as an `EvidenceItem` with an exact quote and confidence.

## License

Free-to-Use License (FUL) 1.0 — see `LICENSE`. Free to use, modify and embed in
commercial products; not for standalone resale. Copyright (c) 2026 Hindham A.F.