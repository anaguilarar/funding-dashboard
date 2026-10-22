"""Transparent, eligibility-gated research-fit scoring.

Five criteria, each 0-5:

* scientific_alignment     - SUBJECTIVE, recorded per opportunity with a rationale
* technical_feasibility    - SUBJECTIVE, recorded per opportunity with a rationale
* strategic_relevance      - SUBJECTIVE, recorded per opportunity with a rationale
* institutional_eligibility - DERIVED from verified eligibility facts
* application_feasibility   - DERIVED from status, deadline proximity and consortium needs

Weighted sum -> 0-100. Gates (applied after weighting):

* confirmed_ineligible           -> capped at 25, tier "ineligible"
* potentially_eligible           -> capped at 69 (cannot be "high" until clarified)
* essential facts unverified     -> capped at 69 (eligibility/deadline/status unverified)
* status monitoring/speculative  -> capped at 60
* weak scientific alignment (<=2) -> capped at 69 (accessible but off-topic is never "high")
* credits / in-kind resources     -> capped at scoring.cap_in_kind (default 69; config uses 60): useful, but they
                                     cannot pay staff, so they never outrank staff-funding calls
"""
from __future__ import annotations

from datetime import datetime

from .models import funding_scope, parse_deadline

ESSENTIAL = {"eligibility", "eligible_applicants", "eligible_countries", "cgiar_eligible",
             "international_orgs_eligible", "deadline", "status"}


def days_left(rec: dict, now: datetime | None = None) -> int | None:
    dl = parse_deadline(rec.get("deadline"))
    if not dl:
        return None
    now = now or datetime.now()
    return (dl - now).days


def institutional_eligibility(rec: dict) -> float:
    ea = rec.get("eligibility_assessment")
    if ea == "confirmed_ineligible":
        return 0.0
    if ea == "confirmed_eligible":
        return 5.0 if rec.get("cgiar_eligible") == "yes" else 4.0
    # potentially eligible
    return 3.0 if rec.get("international_orgs_eligible") == "yes" else 2.0


def application_feasibility(rec: dict, now: datetime | None = None) -> float:
    status = rec.get("status")
    if status == "closed":
        return 0.0
    if status in ("monitoring", "needs_reverification"):
        return 1.0
    if status == "upcoming":
        return 3.5 if rec.get("status_basis") == "official" else 2.0
    if status == "rolling":
        score = 4.0
    else:  # open
        d = days_left(rec, now)
        if d is None:
            score = 3.0
        elif d < 0:
            return 0.0
        elif d < 7:
            score = 1.0
        elif d < 21:
            score = 2.0
        elif d < 45:
            score = 3.5
        else:
            score = 5.0
    if rec.get("consortium_required") == "yes":
        d = days_left(rec, now)
        if d is not None and d < 45:
            score -= 1.0
    if rec.get("cofunding_required") == "yes":
        score -= 0.5
    return max(0.0, score)


def score(rec: dict, cfg: dict, now: datetime | None = None) -> dict:
    w = cfg["scoring"]["weights"]
    comps = {
        "scientific_alignment": float(rec.get("scientific_alignment") or 0),
        "institutional_eligibility": institutional_eligibility(rec),
        "technical_feasibility": float(rec.get("technical_feasibility") or 0),
        "strategic_relevance": float(rec.get("strategic_relevance") or 0),
        "application_feasibility": application_feasibility(rec, now),
    }
    total = sum(comps[k] / 5 * w[k] for k in comps) / sum(w.values()) * 100
    caps = []
    ea = rec.get("eligibility_assessment")
    if ea == "confirmed_ineligible":
        total, caps = min(total, 25), caps + ["confirmed ineligible"]
    elif ea == "potentially_eligible" and total > 69:
        total, caps = 69, caps + ["eligibility needs clarification"]
    unv = {f.lower() for f in rec.get("unverified_fields", [])}
    if unv & ESSENTIAL and total > 69:
        total, caps = 69, caps + ["essential facts unverified: " + ", ".join(sorted(unv & ESSENTIAL))]
    if comps["scientific_alignment"] <= 2 and total > 69:
        total, caps = 69, caps + ["weak scientific alignment"]
    cap_ik = cfg["scoring"].get("cap_in_kind", 69)
    if funding_scope(rec) == "resources_only" and total > cap_ik:
        total, caps = cap_ik, caps + ["credits / in-kind only (cannot pay staff)"]
    if (rec.get("status") in ("monitoring", "needs_reverification")
            or rec.get("status_basis") == "speculative") and total > 60:
        total, caps = 60, caps + ["not confirmed open"]

    tiers = cfg["scoring"]["tiers"]
    if ea == "confirmed_ineligible":
        tier = "ineligible"
    elif total >= tiers["high"]:
        tier = "high"
    elif total >= tiers["medium"]:
        tier = "medium"
    else:
        tier = "low"
    return {"score": round(total), "tier": tier, "components": comps, "caps": caps}
