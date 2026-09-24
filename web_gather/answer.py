"""Ask - the "type a question, get a paragraph" answer mode.

Runs the full research pipeline (search -> choose -> extract evidence), then
compiles the evidence into ONE answer paragraph. With the free Ollama LLM
configured (OLLAMA_API_KEY or local) the paragraph is genuinely AI-written and
grounded in the exact quotes gathered; without it, a deterministic
evidence-compiled paragraph is produced. Sources are always returned.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional

from .browser import BrowserSession
from .evidence import EvidenceItem, clean_snippet
from .llm import LLMClient, local_available, resolve_client
from .research import ResearchOptions, ResearchResult, research as run_research
from .select import SelectedSite

_CLICKBAIT = re.compile(r"\$\s*\d[\d,]*|top\s+\d+\b|\d+\s+ways?\b|shocking|nightmare|bombshell")


@dataclass
class AskOptions:
    engine: str = "auto"
    max_sites: int = 6
    browser_mode: str = "auto"
    use_llm: bool = True


@dataclass
class AnswerSource:
    title: str
    url: str
    engines: list[str] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnswerResult:
    question: str
    paragraph: str
    sources: list[AnswerSource] = field(default_factory=list)
    findings: list[EvidenceItem] = field(default_factory=list)
    used_llm: bool = False
    built_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "paragraph": self.paragraph,
            "sources": [s.to_dict() for s in self.sources],
            "findings": [f.to_dict() for f in self.findings],
            "used_llm": self.used_llm,
            "built_at": self.built_at,
        }


def ask(
    question: str,
    opts: Optional[AskOptions] = None,
    llm: Optional[LLMClient] = None,
    get_body=None,
    http_fetcher=None,
    browser: Optional[BrowserSession] = None,
) -> AnswerResult:
    """Research a question and return one compiled paragraph + sources."""
    opts = opts or AskOptions()

    # Gathering: heuristic (fast, no extra LLM turns). One LLM call for the paragraph.
    research_opts = ResearchOptions(
        goal=question,
        engine=opts.engine,
        max_queries=3,
        max_sites=opts.max_sites,
        min_score=20,
        max_findings_per_site=3,
        browser_mode=opts.browser_mode,
        use_llm=False,
    )
    gathered: ResearchResult = run_research(
        question,
        research_opts,
        llm=None,
        get_body=get_body,
        http_fetcher=http_fetcher,
        browser=browser,
    )

    model = llm if opts.use_llm else None
    paragraph, used_llm = _paragraph(question, gathered.findings, gathered.selected, model)

    sources = [
        AnswerSource(title=s.title, url=s.url, engines=s.engines, score=s.score)
        for s in gathered.selected[:10]
    ]
    return AnswerResult(
        question=question,
        paragraph=paragraph,
        sources=sources,
        findings=gathered.findings,
        used_llm=used_llm,
    )


def client_if_available(use_llm: bool) -> Optional[LLMClient]:
    """Return a configured LLM client without burning time when unconfigured."""
    if not use_llm:
        return None
    if os.getenv("OLLAMA_API_KEY"):
        return resolve_client()
    return resolve_client() if local_available() else None


def _paragraph(
    question: str,
    findings: list[EvidenceItem],
    selected: list[SelectedSite],
    llm: Optional[LLMClient],
) -> tuple[str, bool]:
    if llm is not None:
        text = _paragraph_with_llm(llm, question, findings, selected)
        if text:
            return text, True
    return _paragraph_heuristic(question, findings, selected), False


def _paragraph_with_llm(
    llm: LLMClient, question: str, findings: list[EvidenceItem], selected: list[SelectedSite]
) -> str:
    if not findings:
        return ""
    titled = {s.url: s.title for s in selected}
    digest = []
    for i, f in enumerate(findings, start=1):
        title = titled.get(f.source_url, "")
        digest.append(
            f"{i}. {f.finding}  (source {i}: {title or f.source_url}, "
            f'quote: "{f.quote[:220]}", confidence {f.confidence})'
        )
    prompt = {
        "role": "user",
        "content": (
            f"Question: {question}\n\nEvidence gathered from the web:\n"
            + "\n".join(digest)
            + "\n\nWrite ONE well-structured paragraph (200-400 words) that "
              "answers the question as a research analyst would. Ground every "
              "claim in the numbered evidence and cite inline as [n]. If the "
              "evidence is insufficient to answer fully, state exactly what is "
              "missing. Never invent facts, numbers or quotes."
        ),
    }
    try:
        text = llm.complete(
            [{"role": "system", "content": "You write accurate, sourced, single-paragraph answers."}, prompt]
        )
    except Exception:  # noqa: BLE001 - LLM optional; fall back to compiled paragraph
        return ""
    return text.strip()


def _paragraph_heuristic(
    question: str, findings: list[EvidenceItem], selected: list[SelectedSite]
) -> str:
    if not findings:
        n = len(selected)
        return (
            f"The search returned {n} relevant page{'s' if n != 1 else ''} but no "
            "clear, quotable evidence answering your question could be extracted "
            "from them. Try rephrasing, or use the research mode for a deeper pass."
        )
    hosts = {f.source_url: urlparse(f.source_url).netloc.replace("www.", "").split(":")[0] for f in findings}
    parts = []
    seen = set()
    for f in findings:
        txt = clean_snippet(f.finding)
        if len(txt) < 30:
            continue
        if _CLICKBAIT.search(txt):
            continue
        key = txt[:44].lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append((txt, hosts.get(f.source_url, "the web"), f.confidence))
        if len(parts) >= 4:
            break
    if not parts:
        return (
            "The pages reviewed did not yield a quotable answer. Try rephrasing "
            "the question, or set OLLAMA_API_KEY in .env for an AI-written answer."
        )
    host_list = ", ".join(dict.fromkeys(h for _, h, _ in parts))
    n = len(parts)
    lead = f"According to {n} source{'s' if n != 1 else ''} ({host_list}), "
    body = "; ".join(f"{txt} (per {host}, confidence {conf:.2f})" for txt, host, conf in parts)
    return lead + body + "."