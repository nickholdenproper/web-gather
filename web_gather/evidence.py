"""Verifiable findings - the "bring it back and use it" shape.

Every finding is an evidence item: what we believe + the exact source + the
exact supporting quote + a confidence. Mirrors the evidence pattern used by
yt-transcriber verification so downstream systems can trust and audit it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_WS = re.compile(r"\s+")


@dataclass
class EvidenceItem:
    finding: str
    source_url: str
    page_title: str = ""
    published_utc: str = ""
    quote: str = ""
    confidence: float = 0.5
    engine: str = ""
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


def extract_findings(
    goal: str,
    text: str,
    title: str = "",
    source_url: str = "",
    llm=None,
    max_findings: int = 4,
) -> list[EvidenceItem]:
    """Goal-aware extraction: keep only the passages that answer the goal.

    Heuristic (default): paragraphs scored against goal keywords -> best
    excerpts, each returned as an evidence item. Optional free LLM upgrade:
    "does this page address the goal, and quote the exact supporting
    sentences" - with confidence.
    """
    text = (text or "").strip()
    if not text:
        return []
    if llm is not None:
        items = _extract_with_llm(llm, goal, text, title, source_url, max_findings)
        if items:
            return items
    return _extract_heuristic(goal, text, title, source_url, max_findings)


def _goal_tokens(goal: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", goal.lower()))


def _extract_heuristic(
    goal: str, text: str, title: str, source_url: str, max_findings: int
) -> list[EvidenceItem]:
    tokens = _goal_tokens(goal)
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 80]
    if not paragraphs and len(text) > 80:
        paragraphs = [text]
    paragraphs = [p for p in paragraphs if not _looks_like_table(p)]

    scored = []
    for para in paragraphs:
        hay = para.lower()
        hits = sum(1 for t in tokens if t in hay)
        length_ok = 120 <= len(para) <= 900
        boost = 2 if length_ok else 0
        if hits:
            hit_score = min(hits, 5)
            scored.append((para, hit_score * 10 + boost))
    scored.sort(key=lambda x: x[1], reverse=True)

    # Fallback: no goal-token match at all -> keep the most substantive
    # passages anyway (substantial prose with a real sentence), low confidence.
    if not scored:
        substantive = [p for p in paragraphs if len(p) >= 200]
        if not substantive:
            substantive = paragraphs[:2]
        scored = [(p, 0) for p in substantive[:2]]

    items: list[EvidenceItem] = []
    for para, score in scored[:max_findings]:
        sentence = _best_sentence(para, tokens)
        cleaned = clean_snippet(sentence)
        if len(cleaned) < 30:
            continue
        confidence = min(0.95, 0.35 + score / 60)
        items.append(
            EvidenceItem(
                finding=cleaned[:160],
                source_url=source_url,
                page_title=title,
                quote=cleaned,
                confidence=round(confidence, 2),
            )
        )
    return items


def clean_snippet(text: str) -> str:
    """Human-readable snippet: strip markdown, tables, URLs, crammed text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # markdown links -> label
    text = re.sub(r"https?://\S+", "", text)
    text = text.replace("|", " ")
    text = _WS.sub(" ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"^\s*\d{1,2},\s*\d{4}\s*[—–-]?\s*", "", text)  # dateline prefix
    text = re.sub(r"^\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s*", "", text)  # "Aug 22, 2026"
    if len(text) <= 60:
        return text
    end = re.search(r"(?<=[a-z0-9)])[.!?][)\"']?\s", text)
    if end:
        return text[: end.end()].strip()
    text = text[:160]
    space = text.rfind(" ")
    if space > 40:
        text = text[:space]
    return text.rstrip(" ,;:-|")


def _looks_like_table(text: str) -> bool:
    lines = text.splitlines()[:12]
    for ln in lines:
        stripped = ln.strip()
        if re.fullmatch(r"\|?-{3,}\|?\s*", stripped):
            return True
        if stripped.count("|") >= 3 and len(stripped) < 220:
            return True
    return False


def _best_sentence(para: str, tokens: set[str]) -> str:
    parts = re.split(r"(?<=[.!?])\s+", para)
    sentences = [s for s in parts if len(s.strip()) >= 20 and not _looks_like_table(s)]
    if not sentences:
        sentences = parts
    best = sentences[0] if sentences else para
    best_hits = -1
    for s in sentences:
        hits = sum(1 for t in tokens if t in s.lower())
        if hits > best_hits:
            best, best_hits = s, hits
    return best[:500]


def _finding_from(para: str, sentence: str, tokens: set[str]) -> str:
    head = sentence[:160].rstrip(". ")
    return head[:160]


def _extract_with_llm(
    llm, goal: str, text: str, title: str, source_url: str, max_findings: int
) -> list[EvidenceItem]:
    digest = text[:6000]
    prompt = {
        "role": "user",
        "content": (
            f"Research goal: {goal}\n\n"
            f"Page title: {title}\nURL: {source_url}\n\n"
            f"Page text:\n{digest}\n\n"
            f'Return at most {max_findings} JSON objects, one per line, shaped like: '
            f'{"{"}"finding": "short claim answering the goal", "quote": '
            f'"exact supporting sentence from the page verbatim", "confidence": 0.5{"}"}. '
            "Nothing else."
        ),
    }
    try:
        text_out = llm.complete(
            [{"role": "system", "content": "You are a careful research extractor. Never invent quotes."}, prompt]
        )
    except Exception:  # noqa: BLE001 - fall back to heuristic
        return []
    items: list[EvidenceItem] = []
    for line in text_out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        quote = _WS.sub(" ", str(obj.get("quote", ""))).strip()
        if not quote:
            continue
        try:
            conf = float(obj.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        items.append(
            EvidenceItem(
                finding=str(obj.get("finding", quote[:150])),
                source_url=source_url,
                page_title=title,
                quote=quote[:500],
                confidence=max(0.0, min(1.0, conf)),
            )
        )
    return items[:max_findings]


def write_findings(out_dir: Path, items: list[EvidenceItem], meta: dict, report_md: Optional[str] = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    findings_path = out_dir / "findings.json"
    payload = {
        "meta": meta,
        "findings": [i.to_dict() for i in items],
    }
    findings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(findings_path)

    if report_md:
        report_path = out_dir / "report.md"
        report_path.write_text(report_md, encoding="utf-8")
        written.append(report_path)

    md_path = out_dir / "findings.md"
    lines = ["# Findings", "", f"Goal: {meta.get('goal', '')}", ""]
    for i, item in enumerate(items, start=1):
        lines.append(f"## {i}. {item.finding}")
        lines.append(f"- URL: {item.source_url}")
        if item.page_title:
            lines.append(f"- Page: {item.page_title}")
        if item.published_utc:
            lines.append(f"- Published: {item.published_utc}")
        lines.append(f"- Confidence: {item.confidence}")
        if item.quote:
            lines.append(f"- Evidence: \"{item.quote}\"")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    written.append(md_path)
    return written