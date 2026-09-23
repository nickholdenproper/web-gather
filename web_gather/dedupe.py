"""Deduplication: URL normalization + content fingerprinting."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid", "mc_cid", "mc_eid"}


def normalize_url(url: str) -> str:
    """Canonical form for dedupe: lowercase host, drop tracking params,
    default ports and fragments."""
    if not urlparse(url).scheme:
        url = "http://" + url
    scheme, netloc, path, params, query, fragment = urlparse(url)
    scheme = (scheme or "http").lower()
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if (scheme == "http" and netloc.endswith(":80")) or (
        scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]
    path = path.rstrip("/") or "/"
    kept = [(k, v) for k, v in parse_qsl(query) if k.lower() not in _TRACKING]
    query = urlencode(sorted(kept))
    return urlunparse((scheme, netloc, path, params, query, ""))


def content_fingerprint(text: str) -> str:
    """Stable hash of normalized plain text (near-duplicates collide)."""
    clean = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha1(clean.encode("utf-8")).hexdigest() if clean else None