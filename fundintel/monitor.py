"""Discovery: watch funder pages / feeds / APIs and record *unverified leads*.

Nothing discovered here is ever shown as a verified opportunity. Leads land in
``data/candidates`` and must be verified (``python -m fundintel promote <id>`` after
completing the record from official documentation) before they enter the dashboard.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
import yaml

from . import fetch as F
from .models import slugify
from .store import ROOT, canonical_url, dump_yaml, load_dir, log_event, p


# ---------------------------------------------------------------- relevance
def relevance(text: str, cfg: dict) -> tuple[int, list[str]]:
    t = text.lower()
    hits, score = [], 0
    for kw in cfg["keywords"]["strong"]:
        if kw.lower() in t:
            hits.append(kw)
            score += 3
    for kw in cfg["keywords"]["weak"]:
        pat = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pat, t):
            hits.append(kw)
            score += 1
    return score, hits


def is_call_like(text: str, cfg: dict) -> bool:
    t = text.lower()
    return any(m.lower() in t for m in cfg["keywords"]["call_markers"])


# ---------------------------------------------------------------- state
def _state_path(cfg) -> Path:
    return p(cfg, "state") / "sources_state.json"


def load_state(cfg) -> dict:
    path = _state_path(cfg)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(cfg, state: dict) -> None:
    _state_path(cfg).write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def load_sources(cfg) -> dict:
    with open(ROOT / cfg["paths"]["sources"], encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------- leads
def _known_urls(cfg) -> set[str]:
    urls = set()
    for key in ("opportunities", "archive", "candidates"):
        for r in load_dir(p(cfg, key)):
            urls.add(canonical_url(r.get("url", "")))
            urls.update(canonical_url(u) for u in r.get("source_urls", []))
    rej = p(cfg, "state") / "rejected_leads.txt"
    if rej.exists():
        urls.update(canonical_url(u) for u in rej.read_text(encoding="utf-8").split())
    return urls


def save_lead(cfg, lead: dict, known: set[str]) -> bool:
    cu = canonical_url(lead["url"])
    if cu in known:
        return False
    known.add(cu)
    if "id" not in lead:
        # non-Latin titles (e.g. Chinese) slugify to almost nothing: add a URL hash
        uid = hashlib.sha1(lead["url"].encode("utf-8")).hexdigest()[:8]
        lead["id"] = slugify(f"{lead.get('funder', '')}-{lead['title']}", 60) + "-" + uid
    lead.setdefault("status", "unverified_lead")
    lead.setdefault("review", "pending")
    lead.setdefault("found_on", datetime.now().strftime("%Y-%m-%d"))
    path = p(cfg, "candidates") / f"{lead['id']}.yaml"
    if path.exists():
        return False
    dump_yaml(lead, path)
    log_event(cfg, "new_lead", {"id": lead["id"], "title": lead["title"], "url": lead["url"],
                                "funder": lead.get("funder", ""), "relevance": lead.get("relevance", 0)})
    return True


# ---------------------------------------------------------------- watchers
def watch_html(src: dict, cfg: dict, st: dict, known: set[str]) -> dict:
    res = F.fetch(src["url"], cfg)
    st["last_checked"] = datetime.now().isoformat(timespec="seconds")
    if not res.ok:
        st["failures"] = st.get("failures", 0) + 1
        st["last_error"] = res.error
        if st["failures"] == cfg["monitoring"]["failures_before_flag"]:
            log_event(cfg, "source_unreachable", {"source": src["id"], "url": src["url"],
                                                  "error": res.error})
        return {"ok": False, "new_leads": 0, "changed": False}
    st["failures"] = 0
    st["last_ok"] = st["last_checked"]
    h = F.content_hash(res.text)
    changed = bool(st.get("hash")) and st["hash"] != h
    first_run = not st.get("hash")
    st["hash"] = h

    # link-based discovery: anchors that look like calls and are relevant
    prev_links = set(st.get("links", []))
    cur = F.links(res.html, res.final_url)
    st["links"] = sorted({u for _, u in cur})[:2000]
    new = 0
    if not first_run:
        min_rel = src.get("min_relevance", 3)
        for text, url in cur:
            if url in prev_links:
                continue
            rel, hits = relevance(text, cfg)
            if (is_call_like(text, cfg) or src.get("all_links_are_calls")) and rel >= min_rel:
                lead = {"title": text[:200], "funder": src["funder"], "url": url,
                        "found_via": f"source:{src['id']}", "relevance": rel, "matched_keywords": hits}
                new += save_lead(cfg, lead, known)
    if changed:
        rel, hits = relevance(res.text, cfg)
        log_event(cfg, "source_changed", {"source": src["id"], "funder": src["funder"],
                                          "url": src["url"], "relevance": rel,
                                          "keywords": hits[:10]})
    return {"ok": True, "new_leads": new, "changed": changed}


def watch_rss(src: dict, cfg: dict, st: dict, known: set[str]) -> dict:
    res = F.fetch(src["url"], cfg)
    st["last_checked"] = datetime.now().isoformat(timespec="seconds")
    if not res.ok:
        st["failures"] = st.get("failures", 0) + 1
        return {"ok": False, "new_leads": 0, "changed": False}
    st["failures"] = 0
    try:
        root = ET.fromstring(res.html.encode("utf-8"))
    except ET.ParseError as exc:
        st["last_error"] = f"XML parse error {exc}"
        return {"ok": False, "new_leads": 0, "changed": False}
    seen = set(st.get("items", []))
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = it.findtext("link") or ""
        if not link:
            le = it.find("{http://www.w3.org/2005/Atom}link")
            link = le.get("href") if le is not None else ""
        desc = it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary") or ""
        items.append((title, link.strip(), F.page_text(desc) if "<" in desc else desc))
    new = 0
    first_run = not seen
    for title, link, desc in items:
        if not link or link in seen:
            continue
        rel, hits = relevance(f"{title} {desc}", cfg)
        if not first_run and rel >= src.get("min_relevance", 3):
            new += save_lead(cfg, {"title": title[:200], "funder": src["funder"], "url": link,
                                   "found_via": f"rss:{src['id']}", "relevance": rel,
                                   "matched_keywords": hits, "snippet": desc[:400]}, known)
    st["items"] = sorted(seen | {l for _, l, _ in items})[-1000:]
    return {"ok": True, "new_leads": new, "changed": new > 0}


def api_grants_gov(cfg: dict, queries: list[str], known: set[str]) -> int:
    new = 0
    for q in queries:
        try:
            r = requests.post("https://api.grants.gov/v1/api/search2", json={
                "keyword": q, "oppStatuses": "forecasted|posted", "rows": 50},
                timeout=cfg["monitoring"]["request_timeout_s"])
            hits = r.json().get("data", {}).get("oppHits", [])
        except (requests.RequestException, ValueError) as exc:
            log_event(cfg, "api_error", {"api": "grants.gov", "query": q, "error": str(exc)[:200]})
            continue
        for h in hits:
            rel, kws = relevance(h.get("title", ""), cfg)
            if rel < 5:   # needs e.g. AI + an agriculture/climate term
                continue
            new += save_lead(cfg, {
                "title": h["title"], "funder": h.get("agency", "US Federal"),
                "url": f"https://www.grants.gov/search-results-detail/{h['id']}",
                "found_via": f"api:grants.gov q='{q}'", "relevance": rel, "matched_keywords": kws,
                "api_status": h.get("oppStatus"), "api_open_date": h.get("openDate"),
                "api_close_date": h.get("closeDate"), "opportunity_number": h.get("number"),
                "note": "US federal: most programs restrict eligibility to US entities; check "
                        "foreign-organization eligibility before investing time."}, known)
    return new


_EU_STATUS = {"31094501": "forthcoming", "31094502": "open"}


def api_eu(cfg: dict, queries: list[str], known: set[str]) -> int:
    new = 0
    url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
    query = {"bool": {"must": [{"terms": {"type": ["1", "2", "8"]}},
                               {"terms": {"status": ["31094501", "31094502"]}}]}}
    for q in queries:
        try:
            r = requests.post(url, params={"apiKey": "SEDIA", "text": q, "pageSize": 50, "pageNumber": 1},
                              files={"query": (None, json.dumps(query), "application/json"),
                                     "languages": (None, '["en"]', "application/json")},
                              timeout=cfg["monitoring"]["request_timeout_s"] + 30)
            results = r.json().get("results", [])
        except (requests.RequestException, ValueError) as exc:
            log_event(cfg, "api_error", {"api": "eu-ft", "query": q, "error": str(exc)[:200]})
            continue
        for res in results:
            m = res.get("metadata", {})
            title = (m.get("title") or [res.get("summary") or ""])[0]
            ident = (m.get("identifier") or [""])[0]
            rel, kws = relevance(f"{title} {res.get('content', '')[:3000]}", cfg)
            if rel < 6:
                continue
            topic_url = (f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
                         f"opportunities/topic-details/{ident.lower()}") if ident else res.get("url")
            new += save_lead(cfg, {
                "title": f"{ident} — {title}" if ident else title,
                "funder": "European Commission", "url": topic_url,
                "found_via": f"api:eu-funding-tenders q='{q}'", "relevance": rel,
                "matched_keywords": kws, "opportunity_number": ident,
                "api_status": _EU_STATUS.get((m.get("status") or [""])[0], "unknown"),
                "api_deadlines": m.get("deadlineDate", []),
                "note": "Horizon Europe: international organisations and most LAC countries are "
                        "eligible to participate; funding for non-associated third countries "
                        "depends on the topic - check the topic conditions."}, known)
    return new


# ---------------------------------------------------------------- entry point
def run(cfg: dict) -> dict:
    sources = load_sources(cfg)
    state = load_state(cfg)
    known = _known_urls(cfg)
    summary = {"checked": 0, "failed": 0, "changed": 0, "new_leads": 0}
    for src in sources.get("sources", []):
        if not src.get("enabled", True) or src.get("manual"):
            continue   # manual sources are listed on the dashboard for human checks
        st = state.setdefault(src["id"], {})
        fn = watch_rss if src.get("type") == "rss" else watch_html
        r = fn(src, cfg, st, known)
        summary["checked"] += 1
        summary["failed"] += 0 if r["ok"] else 1
        summary["changed"] += r["changed"]
        summary["new_leads"] += r["new_leads"]
        print(f"  [{'ok' if r['ok'] else 'FAIL'}] {src['id']}"
              f"{' changed' if r['changed'] else ''}{' +' + str(r['new_leads']) if r['new_leads'] else ''}")
    apis = cfg["monitoring"].get("apis", {})
    qs = sources.get("api_queries", {})
    if apis.get("grants_gov"):
        n = api_grants_gov(cfg, qs.get("grants_gov", []), known)
        summary["new_leads"] += n
        print(f"  [api] grants.gov +{n}")
    if apis.get("eu_funding_tenders"):
        n = api_eu(cfg, qs.get("eu_funding_tenders", []), known)
        summary["new_leads"] += n
        print(f"  [api] EU Funding & Tenders +{n}")
    save_state(cfg, state)
    log_event(cfg, "monitor_run", summary)
    return summary
