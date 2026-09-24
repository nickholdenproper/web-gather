"""Optional denylist/allowlist for site visits.

Off by default - empty means "visit anything a human can visit". When you
configure rules they are enforced in both HTTP and browser modes, before any
request, independent of robots or --any-domain.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


class BlockList:
    def __init__(self, blocked: list[str] | None = None, allowed: list[str] | None = None):
        self.blocked = {_norm_domain(b) for b in (blocked or [])}
        self.allowed = {_norm_domain(a) for a in (allowed or [])}

    @classmethod
    def from_file(cls, path: str | Path) -> "BlockList":
        text = Path(path).read_text(encoding="utf-8")
        blocked: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                blocked.append(line)
        return cls(blocked=blocked)

    def blocks(self, url: str) -> bool:
        domain = _domain(url)
        if self.allowed and not _match_any(domain, self.allowed):
            return True
        return _match_any(domain, self.blocked)

    def to_dict(self) -> dict:
        return {"blocked": sorted(self.blocked), "allowed": sorted(self.allowed)}


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def _norm_domain(rule: str) -> str:
    rule = rule.strip().lower().lstrip("*.").rstrip("/")
    if rule.startswith("www."):
        rule = rule[4:]
    return rule


def _match_any(domain: str, rules: set) -> bool:
    for rule in rules:
        if domain == rule or domain.endswith("." + rule):
            return True
    return False