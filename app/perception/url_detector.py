"""Deterministic URL extraction (spec §10/§18).

Pure regex + normalization — no VLM involved. Handles scheme-less URLs,
trailing punctuation, and common shortener domains for later resolution.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

_URL_RE = re.compile(
    r"(?:(?:https?|ftp)://|www\.)"
    r"[^\s<>\"')\]]+",
    re.IGNORECASE,
)

_SCHEMELESS = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s<>\"')\]]*)?",
    re.IGNORECASE,
)

_TRAILING_PUNCT = ".,;:!?)]}\"'>"


class URLDetector:
    def __init__(self, shorteners: Optional[Iterable[str]] = None) -> None:
        self.shorteners = set(s.lower() for s in (shorteners or []))

    def extract(self, text: str) -> List[str]:
        candidates: List[str] = []
        for m in _URL_RE.finditer(text or ""):
            candidates.append(m.group(0))
        if not candidates:
            for m in _SCHEMELESS.finditer(text or ""):
                # avoid picking up file names like setup.ps1
                if "." in m.group(0) and len(m.group(0).split(".")[-1]) >= 2:
                    candidates.append(m.group(0))
        return [self.normalize(u) for u in candidates]

    def normalize(self, url: str) -> str:
        u = url.strip().strip(_TRAILING_PUNCT)
        if u.startswith("www."):
            u = "https://" + u
        if "://" not in u:
            u = "https://" + u
        p = urlparse(u)
        host = (p.hostname or "").lower()
        if not host:
            return u
        # strip 'www.' host prefix
        if host.startswith("www."):
            host = host[4:]
        port = f":{p.port}" if p.port else ""
        path = p.path.rstrip("/") if p.path not in ("", "/") else ""
        normalized = f"{p.scheme.lower()}://{host}{port}{path}"
        if p.query:
            normalized += "?" + p.query
        return normalized

    def hostname(self, url: str) -> str:
        try:
            return (urlparse(self.normalize(url)).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def is_shortener(self, url: str) -> bool:
        return self.hostname(url) in self.shorteners


def extract_urls(text: str, shorteners: Optional[Iterable[str]] = None) -> List[str]:
    return URLDetector(shorteners).extract(text)
