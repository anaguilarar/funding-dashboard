"""Notifications: build a digest of what changed and deliver it to configured channels.

Channels:
* file  - always available; writes reports/digest-YYYY-MM-DD.md
* email - SMTP (credentials via environment variables; e.g. Office 365 smtp.office365.com:587
          requires an account allowed to use SMTP AUTH - ask CGIAR IT)
* teams - Microsoft Teams incoming webhook / Workflows URL (env var)
* slack - Slack incoming webhook (env var)

Each alert is sent once: state is kept in data/state/notify_state.json.
"""
from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

import requests

from .models import NS, THEMES
from .scoring import days_left, score
from .store import load_dir, p, read_events


def _state(cfg):
    path = p(cfg, "state") / "notify_state.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("sent", [])
    return path, data


def _fmt_deadline(rec) -> str:
    if not rec.get("deadline"):
        return rec.get("deadline_text") if rec.get("deadline_text") not in (None, NS) else "Not specified"
    tz = rec.get("deadline_timezone")
    d = days_left(rec)
    return f"{rec['deadline'].replace('T', ' ')} {'' if tz in (None, NS) else tz} ({d} days left)".strip()


def _elig_summary(rec) -> str:
    lab = {"confirmed_eligible": "Eligible (confirmed)", "potentially_eligible": "Potentially eligible — clarify",
           "confirmed_ineligible": "Not eligible as applicant"}[rec["eligibility_assessment"]]
    note = rec.get("cgiar_eligibility_notes")
    return f"{lab}. {note if note not in (None, NS) else ''}".strip()


def item_block(rec: dict, cfg: dict, reason: str) -> str:
    s = score(rec, cfg)
    themes = ", ".join(THEMES.get(t, t) for t in rec.get("themes", []))
    return (f"### {rec['title']}\n"
            f"*{reason}*\n\n"
            f"- **Funder:** {rec['funder']} — {rec.get('program', NS)}\n"
            f"- **Official link:** {rec['url']}\n"
            f"- **Status:** {rec['status']} ({rec.get('status_basis')}) · **Deadline:** {_fmt_deadline(rec)}\n"
            f"- **Funding:** {rec.get('funding_text', NS)}\n"
            f"- **Eligibility:** {_elig_summary(rec)}\n"
            f"- **Consortium required:** {rec.get('consortium_required', NS)}\n"
            f"- **Fit:** {s['score']}/100 ({s['tier']}) — {rec.get('scientific_alignment_rationale', NS)}\n"
            f"- **Themes:** {themes or NS}\n"
            f"- **Next action:** {rec.get('next_action', NS)}\n"
            f"- **Last verified:** {rec.get('last_verified', NS)}\n")


def build_digest(cfg: dict, now: datetime | None = None) -> tuple[str, list[str], dict]:
    now = now or datetime.now()
    trig = cfg["notifications"]["triggers"]
    path, st = _state(cfg)
    sent = set(st["sent"])
    since = datetime.fromisoformat(st["last_run"]) if st.get("last_run") else None
    recs = {r["id"]: r for r in load_dir(p(cfg, "opportunities"))}
    sections: dict[str, list[str]] = {k: [] for k in (
        "Deadlines approaching", "New high-priority opportunities", "Changes to eligibility / funding / status",
        "Newly announced upcoming programmes", "Consortium or institutional coordination needed",
        "Needs re-verification", "New unverified leads (verify before acting)", "Watched funder pages changed")}
    new_keys = []

    def once(key: str) -> bool:
        if key in sent:
            return False
        sent.add(key)
        new_keys.append(key)
        return True

    for rid, rec in recs.items():
        s = score(rec, cfg, now)
        d = days_left(rec, now)
        if trig["deadline_approaching"] and d is not None and d >= 0 and rec["status"] in ("open", "upcoming"):
            for th in sorted(trig["deadline_reminder_days"]):
                if d <= th:
                    if once(f"deadline:{rid}:{rec['deadline']}:{th}"):
                        sections["Deadlines approaching"].append(item_block(rec, cfg, f"{d} days to deadline"))
                    break
        if trig["new_high_priority"] and s["tier"] == "high" and once(f"high:{rid}"):
            sections["New high-priority opportunities"].append(item_block(rec, cfg, f"Priority score {s['score']}"))
        if (trig["new_upcoming_program"] and rec["status"] == "upcoming"
                and once(f"upcoming:{rid}")):
            basis = "official announcement" if rec["status_basis"] == "official" else "SPECULATIVE — not confirmed"
            sections["Newly announced upcoming programmes"].append(item_block(rec, cfg, f"Upcoming ({basis})"))
        if (trig["consortium_needed"] and rec.get("consortium_required") == "yes"
                and rec["status"] in ("open", "upcoming") and s["tier"] in ("high", "medium")
                and once(f"consortium:{rid}")):
            sections["Consortium or institutional coordination needed"].append(
                item_block(rec, cfg, f"Consortium: {rec.get('consortium_details', NS)}"))

    for e in read_events(cfg, since):
        k = e["kind"]
        if k == "record_changed" and trig["eligibility_or_funding_change"] and e["id"] in recs:
            if once(f"chg:{e['id']}:{e['ts']}"):
                ch = "; ".join(f"{f}: {a} → {b}" for f, (a, b) in e["changes"].items())
                sections["Changes to eligibility / funding / status"].append(
                    item_block(recs[e["id"]], cfg, f"Changed: {ch}"))
        elif k == "needs_reverification" and trig["needs_reverification"]:
            if once(f"reverify:{e['id']}:{','.join(sorted(e['flags']))}"):
                sections["Needs re-verification"].append(
                    f"- **{e['title']}** — flags: {', '.join(e['flags'])} — {e['url']}\n")
        elif (k == "new_lead" and e.get("relevance", 0) >= 6
              and (p(cfg, "candidates") / f"{e['id']}.yaml").exists()):   # still pending
            if once(f"lead:{e['id']}"):
                sections["New unverified leads (verify before acting)"].append(
                    f"- {e['title']} ({e.get('funder', '')}, relevance {e['relevance']}) — {e['url']}\n")
        elif k == "source_changed" and trig["source_changed"] and e.get("relevance", 0) >= 6:
            if once(f"src:{e['source']}:{e['ts']}"):
                sections["Watched funder pages changed"].append(
                    f"- {e['funder']}: {e['url']} (keywords: {', '.join(e.get('keywords', []))})\n")

    body = [f"# Funding intelligence digest — {now:%Y-%m-%d}\n"]
    for title, items in sections.items():
        if items:
            body.append(f"\n## {title} ({len(items)})\n")
            body.extend(items)
    if len(body) == 1:
        body.append("\nNo new alerts since the last run.\n")
    st["sent"] = sorted(sent)[-5000:]
    st["last_run"] = now.isoformat(timespec="seconds")
    st["_path"] = str(path)
    return "\n".join(body), new_keys, st


def send(cfg: dict, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now()
    text, new_keys, st = build_digest(cfg, now)
    path = st.pop("_path")
    results = {"alerts": len(new_keys)}
    if not cfg["notifications"]["enabled"]:
        return results
    channels = cfg["notifications"]["channels"]
    out = p(cfg, "reports") / f"digest-{now:%Y-%m-%d}.md"
    if "file" in channels:
        if not out.exists():
            out.write_text(text, encoding="utf-8")
        elif new_keys:   # later run the same day: append, never overwrite earlier alerts
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(f"\n\n---\n\n# Update {now:%H:%M}\n" + text.split("\n", 1)[1])
        results["file"] = str(out)
    if new_keys and not dry_run:
        subject = f"[Funding Intel] {len(new_keys)} new alert(s) — {now:%Y-%m-%d}"
        if "email" in channels:
            results["email"] = _email(cfg, subject, text)
        if "teams" in channels:
            results["teams"] = _webhook(os.getenv(cfg["notifications"]["teams_webhook_env"]),
                                        {"text": text[:25000]})
        if "slack" in channels:
            results["slack"] = _webhook(os.getenv(cfg["notifications"]["slack_webhook_env"]),
                                        {"text": text[:35000]})
    if not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)
    return results


def _email(cfg, subject, text) -> str:
    e = cfg["notifications"]["email"]
    host, user = os.getenv(e["smtp_host_env"]), os.getenv(e["smtp_user_env"])
    if not host:
        return f"skipped: {e['smtp_host_env']} not set"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv(e["from_env"]) or user
    msg["To"] = ", ".join(e["to"])
    msg.set_content(text)
    try:
        with smtplib.SMTP(host, int(os.getenv(e["smtp_port_env"]) or 587), timeout=30) as s:
            s.starttls()
            if user:
                s.login(user, os.getenv(e["smtp_password_env"]) or "")
            s.send_message(msg)
        return "sent"
    except (smtplib.SMTPException, OSError) as exc:
        return f"error: {exc}"


def _webhook(url, payload) -> str:
    if not url:
        return "skipped: webhook env var not set"
    try:
        r = requests.post(url, json=payload, timeout=30)
        return "sent" if r.status_code < 300 else f"error: HTTP {r.status_code}"
    except requests.RequestException as exc:
        return f"error: {exc}"
