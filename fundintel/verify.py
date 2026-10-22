"""Maintenance of verified records.

For every record in ``data/opportunities``:

1. Check that the official URL still resolves. An unreachable page NEVER closes a call;
   after N consecutive failures the record is flagged ``needs_reverification``.
2. Hash the call page; if it changed, flag for re-verification and look for
   closure wording or new dates (possible deadline extension).
3. Deadline passed -> status ``closed`` and the record moves to ``data/archive``.
4. ``upcoming`` with a past expected-opening date or stale ``last_verified`` -> flag.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from . import fetch as F
from .models import NS, parse_deadline
from .store import add_history, load_dir, log_event, move_record, p, save_record

CLOSED_PATTERNS = [
    r"\b(this )?call (is|has) (now )?closed\b", r"\bapplications? (are|is) (now )?closed\b",
    r"\bno longer accepting\b", r"\bsubmissions? (are|is) closed\b", r"\bcall closed\b",
    r"\bconvocatoria cerrada\b", r"\bdeadline has passed\b",
]
DATE_RX = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(20\d\d)\b|\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),?\s+(20\d\d)\b|\b(20\d\d)-(\d\d)-(\d\d)\b",
    re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}


def extract_dates(text: str) -> list[datetime]:
    out = []
    for m in DATE_RX.finditer(text):
        try:
            if m.group(1):
                out.append(datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))))
            elif m.group(4):
                out.append(datetime(int(m.group(6)), MONTHS[m.group(4).lower()], int(m.group(5))))
            else:
                out.append(datetime(int(m.group(7)), int(m.group(8)), int(m.group(9))))
        except ValueError:
            continue
    return out


def deadline_context_dates(text: str) -> list[datetime]:
    """Dates that appear within ~120 chars after the word deadline/closing/due."""
    out = []
    for m in re.finditer(r"(deadline|closing date|closes|due date|submission|fecha l[ií]mite|cierre)",
                         text, re.I):
        out += extract_dates(text[m.start(): m.start() + 160])
    return out


def _page_state(cfg):
    path = p(cfg, "state") / "pages_state.json"
    return path, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})


def check_record(rec: dict, cfg: dict, pages: dict, now: datetime, online: bool = True) -> list[str]:
    """Mutates rec; returns list of flags raised."""
    flags = []
    st = pages.setdefault(rec["id"], {})

    # 1-2. link + content check
    if online:
        res = F.fetch(rec["url"], cfg)
        st["last_checked"] = now.isoformat(timespec="seconds")
        st["http_status"] = res.status
        if not res.ok:
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"] = res.error
            if st["failures"] >= cfg["monitoring"]["failures_before_flag"]:
                flags.append("url_unreachable")
        else:
            st["failures"] = 0
            st["final_url"] = res.final_url
            h = F.content_hash(res.text)
            if st.get("hash") and st["hash"] != h:
                flags.append("call_page_changed")
                low = res.text.lower()
                if any(re.search(pat, low) for pat in CLOSED_PATTERNS):
                    flags.append("page_mentions_closed")
                cur = parse_deadline(rec.get("deadline"))
                if cur:
                    later = [d for d in deadline_context_dates(res.text) if d.date() > cur.date()]
                    if later:
                        flags.append("possible_deadline_change:" + max(later).strftime("%Y-%m-%d"))
            st["hash"] = h

    # 3. deadline expiry
    dl = parse_deadline(rec.get("deadline"))
    if dl and dl < now and rec["status"] in ("open", "upcoming", "needs_reverification"):
        rec["status"] = "closed"
        add_history(rec, "closed", f"deadline {rec['deadline']} passed")
        flags.append("expired")

    # 4. staleness
    lv = rec.get("last_verified")
    try:
        lv_dt = datetime.strptime(lv, "%Y-%m-%d") if lv and lv != NS else None
    except ValueError:
        lv_dt = None
    if rec["status"] != "closed":
        if lv_dt is None or now - lv_dt > timedelta(days=cfg["monitoring"]["reverify_after_days"]):
            flags.append("stale_verification")

    if rec["status"] != "closed" and ({"url_unreachable", "page_mentions_closed"} & set(flags)):
        if rec["status"] != "needs_reverification":
            add_history(rec, "flagged", f"needs re-verification ({', '.join(flags)}); "
                                        f"previous status {rec['status']}")
            rec["status_before_flag"] = rec["status"]
            rec["status"] = "needs_reverification"
    rec["flags"] = flags
    return flags


def run(cfg: dict, online: bool = True, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    opp_dir, arch_dir = p(cfg, "opportunities"), p(cfg, "archive")
    path, pages = _page_state(cfg)
    summary = {"checked": 0, "flagged": 0, "archived": 0}
    for rec in load_dir(opp_dir):
        before = rec["status"]
        flags = check_record(rec, cfg, pages, now, online)
        summary["checked"] += 1
        rec.pop("_file", None)
        if rec["status"] == "closed":
            move_record(rec, opp_dir, arch_dir)
            summary["archived"] += 1
            log_event(cfg, "archived", {"id": rec["id"], "title": rec["title"], "reason": "deadline passed"})
            print(f"  [archived] {rec['id']}")
            continue
        serious = [f for f in flags if f != "stale_verification"]
        if serious:
            summary["flagged"] += 1
            log_event(cfg, "needs_reverification", {"id": rec["id"], "title": rec["title"],
                                                    "url": rec["url"], "flags": flags})
        if rec["status"] != before:
            log_event(cfg, "status_changed", {"id": rec["id"], "title": rec["title"],
                                              "from": before, "to": rec["status"]})
        save_record(rec, opp_dir)
        print(f"  [{'!' if serious else 'ok'}] {rec['id']} {' '.join(flags)}")
    path.write_text(json.dumps(pages, indent=1), encoding="utf-8")
    log_event(cfg, "verify_run", summary)
    return summary
