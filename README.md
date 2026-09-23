# Web Gather

LLM-style web scraper. You give it seeds (a page, an RSS/Atom feed, a `sitemap.xml`, or several — any site, no per-site selectors), it fetches, cleans each page into a readable article, follows links within the same domain, and writes a corpus:

- `index.json` — crawl stats + every article (full metadata + clean text)
- `NNNN-<slug>.json` / `NNNN-<slug>.md` — one file per article (Markdown human-readable)
- `corpus.txt` — plain-text `<article>` blocks, ready to feed an LLM

Everything is free and open-source. No API keys. No paid services.

## Install

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[all]
```

## CLI

```powershell
# Scrape one URL
webgather url https://news.com/story-123

# Crawl a feed (or several) and follow links
webgather crawl https://news.com/feed https://news.com/rss --max-pages 200

# Crawl via sitemap
webgather crawl https://news.com/sitemap.xml --max-depth 3

# Typical news crawl: feed in, corpus out
webgather crawl https://publisher.com/feed --out output --max-pages 500
```

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--max-pages` | 50 | stop after N visited URLs |
| `--max-depth` | 3 | max link-following hops from the seed |
| `--any-domain` | off | allow leaving the seed domains (default: same-domain only) |
| `--delay` | 1.0 | polite seconds between requests to one domain |
| `--concurrency` | 4 | parallel workers |
| `--timeout` / `--retries` | 20 / 2 | per-request settings |
| `--ignore-robots` | off | disable robots.txt honoring (use responsibly) |
| `--out` / `--out-dir` | `output` | corpus destination |

## REST API

```powershell
webgather serve --port 8001
```

```bash
# Start a job
curl -X POST localhost:8001/v1/jobs -H "Content-Type: application/json" \
  -d '{"sources":["https://news.com/feed"],"options":{"max_pages":200}}'
# -> {"job_id":"abc123"}

# Poll
curl localhost:8001/v1/jobs/abc123

# Download corpus files
curl -o index.json localhost:8001/v1/jobs/abc123/files/index.json
curl -o corpus.txt localhost:8001/v1/jobs/abc123/files/corpus.txt
```

Every run is saved under `api_jobs/<job_id>/`.

## How it works

1. **Fetch** — `httpx` with retries, respect for `robots.txt` and courteous per-domain pacing.
2. **Discover** — seeds can be feeds (many articles), sitemaps (many URLs), or pages; links on pages extend the frontier up to `--max-depth`.
3. **Extract** — site-agnostic "readability": `trafilatura` first, `readability-lxml` fallback; metadata enriched from JSON-LD / OpenGraph / `<meta>`.
4. **Clean** — URL normalization (anti-tracking, schema/case) and content fingerprinting collapse duplicates.
5. **Output** — normalized `Article` JSON + Markdown + `corpus.txt`.

None of it depends on scrapers for specific sites — it's the same "give me the prose" approach LLMs use.

## Roadmap

- **Ship-2** — Playwright JS-rendering fallback (`--js`), per-site profile files.
- **Ship-3** — search-engine query plugins (Google News RSS, DuckDuckGo, Bing News, Mojeek, Marginalia).

## License

Free-to-Use License (FUL) 1.0 — see `LICENSE`. Free to use, modify and embed in commercial products; not for standalone resale. Copyright (c) 2026 Hindham A.F.