"""HTTP fetching and page-text extraction."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_session: requests.Session | None = None
_last_call = 0.0


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    final_url: str
    text: str = ""
    html: str = ""
    error: str = ""


def session(cfg: dict) -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": cfg["monitoring"]["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,es;q=0.8",
        })
    return _session


def fetch(url: str, cfg: dict) -> FetchResult:
    global _last_call
    wait = cfg["monitoring"]["polite_delay_s"] - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    try:
        r = session(cfg).get(url, timeout=cfg["monitoring"]["request_timeout_s"], allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        html = r.text if ("html" in ctype or "xml" in ctype or "text" in ctype) else ""
        ok = r.status_code < 400
        return FetchResult(url, ok, r.status_code, r.url, page_text(html) if html else "",
                           html, "" if ok else f"HTTP {r.status_code}")
    except requests.RequestException as exc:
        return FetchResult(url, False, None, url, error=type(exc).__name__ + ": " + str(exc)[:200])


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()
    lines = []
    for line in soup.get_text("\n").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) > 2:
            lines.append(line)
    return "\n".join(lines)


def content_hash(text: str) -> str:
    # ignore volatile digits like counters/timestamps a little by collapsing whitespace only
    return hashlib.sha256(re.sub(r"\s+", " ", text).encode("utf-8")).hexdigest()


def links(html: str, base: str) -> list[tuple[str, str]]:
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        txt = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        href = urljoin(base, a["href"])
        if txt and href.startswith("http"):
            out.append((txt, href))
    return out
