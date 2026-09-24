"""Research orchestrator - the full "AI research agent" pipeline.

goal -> queries (planner) -> search (free engines) -> choose sites (selector)
-> visit & find what you need (browser/HTTP + targeter) -> bring it back
(evidence items + findings.json/report.md).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .blocks import BlockList
from .browser import BrowserSession, HybridFetcher
from .evidence import EvidenceItem, extract_findings, write_findings
from .extract import extract_page
from .fetch import Fetcher
from .llm import LLMClient
from .planner import plan_queries
from .search import search_web
from .select import SelectedSite, select_sites


@dataclass
class ResearchOptions:
    goal: str
    engine: str = "auto"
    max_queries: int = 4
    max_sites: int = 6
    min_score: int = 30
    max_findings_per_site: int = 3
    browser_mode: str = "auto"
    use_llm: bool = False
    blocked: Optional[list[str]] = None
    allowed: Optional[list[str]] = None
    out_dir: Optional[Path] = None


@dataclass
class ResearchResult:
    goal: str
    queries: list[str] = field(default_factory=list)
    selected: list[SelectedSite] = field(default_factory=list)
    findings: list[EvidenceItem] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str = ""
    engine: str = "auto"

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "engine": self.engine,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "queries": self.queries,
            "selected": [s.to_dict() for s in self.selected],
            "findings": [f.to_dict() for f in self.findings],
            "written": [str(w) for w in self.written],
        }


def research(
    goal: str,
    opts: Optional[ResearchOptions] = None,
    llm: Optional[LLMClient] = None,
    browser: Optional[BrowserSession] = None,
    get_body=None,
    http_fetcher: Optional[Fetcher] = None,
) -> ResearchResult:
    """Run the research pipeline end to end (heuristic default, LLM optional)."""
    opts = opts or ResearchOptions(goal=goal)
    result = ResearchResult(goal=goal, engine=opts.engine)
    block = BlockList(blocked=opts.blocked, allowed=opts.allowed)

    # 1. What to google.
    planner_llm = llm if opts.use_llm else None
    queries = plan_queries(goal, opts.max_queries, llm=planner_llm)
    result.queries = queries

    # 2. What websites to choose.
    all_results = []
    for query in queries[: opts.max_queries]:
        try:
            all_results.extend(search_web(query, engine=opts.engine, limit=8, get_body=get_body, blocklist=block))
        except Exception:  # noqa: BLE001
            continue
    selected = select_sites(all_results, goal, min_score=opts.min_score, max_sites=opts.max_sites)
    result.selected = selected

    # 3. Visit & find / 4. bring it back.
    fetcher = http_fetcher or Fetcher(delay=1.0, concurrency_per_domain=2, retries=1)
    active = None
    if opts.browser_mode != "never":
        active = HybridFetcher(fetcher, browser, opts.browser_mode)

    uses_llm = llm if opts.use_llm else None
    for site in selected:
        try:
            raw = (active or fetcher).get(site.url)
            if raw.status_code != 200:
                continue
            extracted = extract_page(raw.text, raw.url)
            text = (extracted.get("text") or "").strip()
            if not text:
                continue
            items = extract_findings(
                goal,
                text,
                title=extracted.get("title") or site.title,
                source_url=site.url,
                llm=uses_llm,
                max_findings=opts.max_findings_per_site,
            )
            for item in items:
                item.engine = ",".join(site.engines)
                item.confidence = round(
                    min(1.0, item.confidence * 0.8 + site.score / 200), 2
                )
                result.findings.append(item)
        except Exception:  # noqa: BLE001 - one bad site mustn't kill research
            continue

    # 5. Write it down.
    out_dir = opts.out_dir or Path.cwd() / "research_jobs"
    report_md = None
    if uses_llm is not None:
        report_md = _summarize(uses_llm, result)
    result.written = write_findings(
        out_dir,
        result.findings,
        meta=result.to_dict(),
        report_md=report_md,
    )
    result.finished_at = datetime.now(timezone.utc).isoformat()
    return result


def _summarize(llm: LLMClient, result: ResearchResult) -> str:
    digest = "\n".join(
        f"- {f.finding} [{f.source_url}] (confidence {f.confidence})\n  quote: {f.quote[:200]}"
        for f in result.findings[:20]
    )
    if not digest:
        return "No findings were extracted for this goal."
    prompt = {
        "role": "user",
        "content": (
            f"Research goal: {result.goal}\n\nEvidence collected:\n{digest}\n\n"
            "Write a short, factual summary report in Markdown. Head it '## Summary' "
            "and say what the evidence supports, then list open weak spots. "
            "Only use the evidence above."
        ),
    }
    try:
        return llm.complete(
            [{"role": "system", "content": "You are a careful research assistant."}, prompt]
        )
    except Exception:  # noqa: BLE001
        return ""