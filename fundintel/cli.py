"""Command-line interface.

    python -m fundintel run            # full pipeline: verify -> monitor -> dashboard -> notify
    python -m fundintel verify         # re-check verified records (links, deadlines, archive)
    python -m fundintel monitor        # watch funder pages/APIs for new leads
    python -m fundintel build          # regenerate site/index.html
    python -m fundintel notify         # build digest and send to configured channels
    python -m fundintel ingest FILE..  # import verified records (JSON/YAML)
    python -m fundintel promote ID     # move a verified candidate into opportunities
    python -m fundintel reject ID      # reject a lead (never suggested again)
    python -m fundintel validate       # integrity check of all records
    python -m fundintel linkcheck      # check every official URL (records + sources)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import dashboard, ingest, monitor, notify, verify
from .models import normalize, validate
from .store import load_config, load_dir, log_event, p


def _validate(cfg) -> int:
    bad = 0
    seen = {}
    for key in ("opportunities", "archive"):
        for rec in load_dir(p(cfg, key)):
            probs = validate(rec)
            if rec["id"] in seen:
                probs.append(f"duplicate id also in {seen[rec['id']]}")
            seen[rec["id"]] = key
            if key == "opportunities" and rec["status"] == "closed":
                probs.append("closed record in active folder")
            if probs:
                bad += 1
                print(f"  [INVALID] {rec['id']}: {'; '.join(probs)}")
    print(f"  {len(seen)} records checked, {bad} with problems")
    return bad


def _linkcheck(cfg) -> int:
    from . import fetch as F
    broken = 0
    urls = []
    for rec in load_dir(p(cfg, "opportunities")):
        urls.append((rec["id"], rec["url"]))
        urls += [(rec["id"] + " (source)", u) for u in rec.get("source_urls", [])]
    for s in monitor.load_sources(cfg).get("sources", []):
        urls.append(("source:" + s["id"], s["url"]))
    for name, url in urls:
        r = F.fetch(url, cfg)
        if not r.ok:
            broken += 1
        print(f"  [{'ok ' if r.ok else 'BAD'}] {r.status} {name}: {url} {r.error}")
    print(f"  {len(urls)} URLs, {broken} failing")
    return broken


def _move_candidate(cfg, cid: str, action: str) -> int:
    path = p(cfg, "candidates") / f"{cid}.yaml"
    if not path.exists():
        print(f"no candidate {cid}")
        return 1
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if action == "reject":
        with open(p(cfg, "state") / "rejected_leads.txt", "a", encoding="utf-8") as fh:
            fh.write(data["url"] + "\n")
        path.unlink()
        log_event(cfg, "lead_rejected", {"id": cid, "url": data["url"]})
        print(f"rejected {cid}")
        return 0
    rec = normalize(data)
    probs = validate(rec)
    if data.get("status") == "unverified_lead" or probs:
        print("Cannot promote: complete the record from official documentation first "
              "(set status, last_verified, eligibility fields, deadline_text, ...).")
        for pr in probs:
            print("  -", pr)
        if data.get("status") == "unverified_lead":
            print("  - status is still 'unverified_lead'")
        return 1
    action, rec = ingest.upsert(cfg, data, source=f"promoted:{cid}")
    print(action, rec["id"])
    if not action.startswith("rejected"):
        path.unlink()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fundintel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "verify", "monitor", "build", "notify", "ingest",
                                        "promote", "reject", "validate", "linkcheck"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--offline", action="store_true", help="verify without network (dates only)")
    ap.add_argument("--dry-run", action="store_true", help="notify: write digest file only")
    ap.add_argument("--config", type=Path)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if a.command == "run":
        print(f"[{stamp}] verify"); print("  ", verify.run(cfg, online=not a.offline))
        if not a.offline:
            print("monitor"); print("  ", monitor.run(cfg))
        print("build"); print("  ", dashboard.build(cfg))
        print("notify"); print("  ", notify.send(cfg, dry_run=a.dry_run))
        return 0
    if a.command == "verify":
        print(verify.run(cfg, online=not a.offline)); return 0
    if a.command == "monitor":
        print(monitor.run(cfg)); return 0
    if a.command == "build":
        print(dashboard.build(cfg)); return 0
    if a.command == "notify":
        print(notify.send(cfg, dry_run=a.dry_run)); return 0
    if a.command == "ingest":
        for f in a.args:
            print(f, ingest.ingest_file(cfg, Path(f)))
        return 0
    if a.command in ("promote", "reject"):
        return max(_move_candidate(cfg, cid, a.command) for cid in a.args) if a.args else 1
    if a.command == "validate":
        return 1 if _validate(cfg) else 0
    if a.command == "linkcheck":
        return 1 if _linkcheck(cfg) else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
