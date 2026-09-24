"""Smarter link choosing: rank search results by evidence quality.

Deterministic, zero keys. Signals: cross-engine agreement, mean position,
goal-relevance of the title/url/snippet, freshness year, and junk-site
penalties. LLM re-ranking is available later as an optional upgrade.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from .search import SearchResult

JUNK_TLDS = {"buzz", "top", "club", "xyz", "icu", "rest", "click", "online"}
SPAM_WORDS = ("aggregator", "sponsored", "advert", "promo", "best of the best", "top 10")


@dataclass
class SelectedSite:
    url: str
    title: str
    snippet: str
    score: int
    engines: list[str]
    positions: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def _goal_tokens(goal: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", goal.lower()))


def select_sites(
    results: list[SearchResult],
    goal: str,
    min_score: int = 30,
    max_sites: Optional[int] = None,
) -> list[SelectedSite]:
    """Group results by normalized URL, score each, return ranked winners."""
    from .dedupe import normalize_url

    groups: dict[str, dict] = {}
    tokens = _goal_tokens(goal)
    for r in results:
        base_url = r.url
        norm = normalize_url(r.url) or r.url
        g = groups.setdefault(norm, {"url": base_url, "title": r.title, "snippet": r.snippet, "engines": [], "positions": []})
        if r.engine not in g["engines"]:
            g["engines"].append(r.engine)
        g["positions"].append(r.position)
        if len(r.title) > len(g["title"]):
            g["title"] = r.title
        if len(r.snippet) > len(g["snippet"]):
            g["snippet"] = r.snippet

    ranked: list[SelectedSite] = []
    for norm, g in groups.items():
        site = SelectedSite(
            url=g["url"],
            title=g["title"],
            snippet=g["snippet"],
            score=0,
            engines=g["engines"],
            positions=g["positions"],
        )
        site.score = _score(site, tokens, len(groups))
        ranked.append(site)
    ranked.sort(key=lambda s: s.score, reverse=True)
    if max_sites:
        ranked = ranked[:max_sites]
    return [s for s in ranked if s.score >= min_score]


def _score(site: SelectedSite, tokens: set[str], total_sites: int) -> int:
    score = 40  # baseline: it was returned by a real engine

    # cross-engine agreement is the strongest signal
    extra_engines = len(site.engines) - 1
    score += min(extra_engines * 12, 24)

    # mean position bonus (seen near the top of any engine)
    best = min(site.positions)
    if best <= 3:
        score += 12
    elif best <= 6:
        score += 7
    elif best <= 10:
        score += 3

    # goal relevance
    hay = f"{site.title} {site.url} {site.snippet}".lower()
    hits = sum(1 for t in tokens if t in hay)
    score += min(hits * 3, 15)

    # freshness: current-year mentions usually mean recent coverage
    import datetime

    if str(datetime.date.today().year) in hay:
        score += 5

    # junk penalties
    host = urlparse(site.url).netloc.lower().split(":")[0]
    if host.split(".")[-1] in JUNK_TLDS:
        score -= 10
    if any(word in site.url.lower() for word in SPAM_WORDS):
        score -= 10
    if len(site.title) < 12 and not site.title:
        score -= 5

    return max(0, score)