"""Build the static dashboard (site/index.html + site/data.json)."""
from __future__ import annotations

import json
from datetime import datetime

import yaml

from .models import NS, THEMES, funding_scope
from .monitor import load_sources, load_state
from .scoring import days_left, score
from .store import ROOT, load_dir, p, read_events


def _usd(rec, cfg):
    fx = cfg["scoring"].get("fx_to_usd", {})
    rate = fx.get(rec.get("currency"))
    amt = rec.get("funding_amount_max") or rec.get("funding_amount_min")
    return round(amt * rate) if (amt and rate) else None


def _public(rec: dict, cfg: dict, now: datetime) -> dict:
    r = {k: v for k, v in rec.items() if not k.startswith("_")}
    s = score(rec, cfg, now)
    r["score"], r["tier"], r["score_components"], r["score_caps"] = (
        s["score"], s["tier"], s["components"], s["caps"])
    r["days_left"] = days_left(rec, now)
    r["amount_usd_approx"] = _usd(rec, cfg)
    r["funding_scope"] = funding_scope(rec)
    return r


def build(cfg: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    active = [_public(r, cfg, now) for r in load_dir(p(cfg, "opportunities"))]
    archive = [_public(r, cfg, now) for r in load_dir(p(cfg, "archive"))]
    # candidates are not opportunities; load them raw to keep their own fields
    leads = []
    for f in sorted(p(cfg, "candidates").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if d.get("review", "pending") == "pending":
            leads.append(d)
    leads.sort(key=lambda d: -(d.get("relevance") or 0))

    sources = load_sources(cfg).get("sources", [])
    state = load_state(cfg)
    src_rows = []
    for s in sources:
        st = state.get(s["id"], {})
        src_rows.append({"id": s["id"], "funder": s["funder"], "name": s.get("name", ""),
                         "url": s["url"], "type": s.get("type", "html"),
                         "category": s.get("category", ""), "enabled": s.get("enabled", True),
                         "manual": s.get("manual", False), "note": s.get("note", ""),
                         "last_checked": st.get("last_checked"), "last_ok": st.get("last_ok"),
                         "failures": st.get("failures", 0), "last_error": st.get("last_error", "")})
    events = read_events(cfg)[-200:]
    data = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "profile": cfg["profile"],
        "weights": cfg["scoring"]["weights"],
        "tiers": cfg["scoring"]["tiers"],
        "deadlines": cfg["deadlines"],
        "themes": THEMES,
        "active": active,
        "archive": archive,
        "leads": leads[:400],
        "sources": src_rows,
        "events": events[::-1],
        "ns": NS,
    }
    site = p(cfg, "site")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    (site / "data.json").write_text(payload, encoding="utf-8")
    tpl = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", payload.replace("</", "<\\/"))
    out = site / "index.html"
    out.write_text(html, encoding="utf-8")
    return str(out)
