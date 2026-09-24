"""Goal -> search queries. Heuristic (deterministic, free) or LLM-assisted."""

from __future__ import annotations

import re
from typing import Optional

from .llm import LLMClient

STOPWORDS = {
    "and", "the", "for", "with", "this", "that", "what", "when", "where",
    "which", "who", "how", "are", "was", "were", "have", "has", "had", "from",
    "about", "into", "over", "after", "before", "their", "they", "them", "its",
    "it", "is", "in", "on", "of", "to", "a", "an", "or", "not", "but", "latest",
}


def plan_queries(goal: str, n: int = 4, llm: Optional[LLMClient] = None) -> list[str]:
    """Expand a goal into n query strings to run across search engines."""
    goal = goal.strip()
    if not goal:
        return []
    if llm is not None:
        queries = _plan_with_llm(llm, goal, n)
        if queries:
            return queries[:n]
    return _plan_heuristic(goal, n)


def _plan_heuristic(goal: str, n: int) -> list[str]:
    keywords = _keywords(goal)
    base = re.sub(r"\s+", " ", goal.lower()).strip()
    queries = [goal]
    if len(queries) < n and keywords:
        queries.append(" ".join(keywords))
    if len(queries) < n and len(keywords) >= 2:
        queries.append(f'"{keywords[0]} {keywords[1]}"')
    if len(queries) < n and len(keywords) >= 3:
        queries.append(f"{keywords[0]} {keywords[1]} {keywords[2]}")
    # Add a "news + year" flavor when possible (freshness-oriented goal).
    import datetime

    year = str(datetime.date.today().year)
    if len(queries) < n and keywords:
        queries.append(f"{' '.join(keywords[:2])} {year}")
    while len(queries) < n and keywords:
        queries.append(f"{base} {keywords[len(queries) % len(keywords)]}")
    return queries[:n]


def _keywords(goal: str) -> list[str]:
    tokens = re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", goal.lower())
    seen = set()
    out = []
    for tok in tokens:
        if tok in STOPWORDS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out[:6]


def _plan_with_llm(llm: LLMClient, goal: str, n: int) -> list[str]:
    prompt = {
        "role": "user",
        "content": (
            f"Given the research goal: \"{goal}\"\n\n"
            f"Write exactly {n} diverse web-search queries (one per line) that "
            "would surface the most useful, fresh pages about this topic. "
            "Queries only, no numbering, no commentary."
        ),
    }
    try:
        text = llm.complete([{"role": "system", "content": "You are a search query planner."}, prompt])
    except Exception:  # noqa: BLE001 - LLM optional; fall back to heuristic
        return []
    lines = [re.sub(r"^\d+[.)]\s*", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and len(ln) < 200]
    return lines[:n]