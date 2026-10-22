"""Import verified records (JSON/YAML) into the store with de-duplication and change tracking.

Used for: research batches (research/raw/*.json), manual re-verification updates, and
promotion of candidate leads after they have been verified against official documents.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import yaml

from .models import normalize, slugify, validate
from .store import (add_history, diff_watched, find_duplicate, load_dir, log_event, p,
                    save_record)


def _load_any(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if isinstance(data, dict) and "opportunities" in data:
        return data["opportunities"], data.get("searched_on")
    if isinstance(data, dict):
        return [data], None
    return data, None


def upsert(cfg: dict, raw: dict, verified_on: str | None = None, source: str = "") -> tuple[str, dict]:
    """Insert or update one record. Returns (action, record). action in added|updated|rejected."""
    rec = normalize(raw)
    today = datetime.now().strftime("%Y-%m-%d")
    if rec["last_verified"] in (None, "", "Not specified"):
        rec["last_verified"] = verified_on or today
    if source and rec["verification_source"] == "Not specified":
        rec["verification_source"] = source
    problems = validate(rec)
    if problems:
        log_event(cfg, "rejected_record", {"title": rec.get("title"), "problems": problems})
        return "rejected:" + "; ".join(problems), rec

    opp_dir = p(cfg, "opportunities")
    existing = load_dir(opp_dir) + load_dir(p(cfg, "archive"))
    dup = find_duplicate(rec, existing)
    if dup:
        changes = diff_watched(dup, rec)
        rec["id"] = dup["id"]
        rec["first_seen"] = dup.get("first_seen") or today
        rec["history"] = dup.get("history", [])
        # merge source URLs from both sources (same call published on several sites)
        rec["source_urls"] = list(dict.fromkeys(dup.get("source_urls", []) + rec["source_urls"]))
        add_history(rec, "reverified", "; ".join(f"{k}: {a} -> {b}" for k, (a, b) in changes.items())
                    or "no material change")
        if changes:
            log_event(cfg, "record_changed", {"id": rec["id"], "title": rec["title"],
                                              "changes": {k: [str(a), str(b)] for k, (a, b) in changes.items()}})
        old_file = Path(dup["_file"])
        if rec["status"] != "closed" and old_file.parent.resolve() != opp_dir.resolve():
            old_file.unlink(missing_ok=True)   # re-opened next cycle: move back from archive
        save_record(rec, opp_dir if rec["status"] != "closed" else p(cfg, "archive"))
        return "updated", rec
    if any(o.get("id") == rec["id"] for o in existing):
        # auto-generated id collided with a different call (long funder names fill the slug)
        rec["id"] = slugify(rec["id"], 61) + "-" + hashlib.sha1(rec["title"].encode()).hexdigest()[:8]
    rec["first_seen"] = today
    add_history(rec, "added", source)
    save_record(rec, opp_dir if rec["status"] != "closed" else p(cfg, "archive"))
    log_event(cfg, "record_added", {"id": rec["id"], "title": rec["title"], "status": rec["status"]})
    return "added", rec


def ingest_file(cfg: dict, path: Path) -> dict:
    items, searched = _load_any(path)
    summary = {"added": 0, "updated": 0, "rejected": 0}
    for raw in items:
        action, rec = upsert(cfg, raw, verified_on=searched, source=f"import:{path.name}")
        key = action.split(":")[0]
        summary[key] += 1
        print(f"  [{action}] {rec.get('id')}")
    return summary
