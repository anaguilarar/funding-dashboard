"""Opportunity data model: field definitions, normalisation and validation.

Each opportunity is stored as one YAML file. Missing facts are stored as the literal
string ``"Not specified"`` so that the dashboard never shows invented values.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

NS = "Not specified"

STATUSES = ("open", "rolling", "upcoming", "monitoring", "closed", "needs_reverification")
STATUS_BASIS = ("official", "speculative")
ELIGIBILITY = ("confirmed_eligible", "potentially_eligible", "confirmed_ineligible")
YES_NO_UNCLEAR = ("yes", "no", "unclear")
CONSORTIUM = ("yes", "no", "optional", NS)
FUNDER_TYPES = ("multilateral", "national_agency", "foundation", "tech_company",
                "research_partnership", "bilateral", "cgiar", "regional_fund")
SUPPORT_TYPES = ("project_funding", "fellowship_salary", "core_or_program_funding",
                 "in_kind_resources", "prize", NS)
STAFF_COSTS = ("yes", "partial", "no", NS)
OPP_TYPES = ("grant", "research_award", "challenge", "fellowship", "cloud_credits",
             "consortium_call", "prize", "accelerator", "tender")
THEMES = {
    "climate_adaptation": "Climate adaptation",
    "climate_mitigation": "Climate mitigation",
    "climate_smart_ag": "Climate-smart agriculture",
    "digital_agriculture": "Digital agriculture",
    "remote_sensing": "Remote sensing & EO",
    "ai_ml": "AI / machine learning",
    "crop_modeling": "Crop modelling",
    "climate_data_infrastructure": "Climate data infrastructure",
    "multifunctional_landscapes": "Multifunctional landscapes",
    "biodiversity": "Biodiversity",
    "food_security": "Food security",
    "smallholders": "Smallholder farmers",
    "open_source_software": "Open-source research software",
    "capacity_building": "Capacity building",
}

# Field -> default. Order defines YAML/key order and dashboard field order.
FIELDS: dict[str, object] = {
    "id": "",
    "title": "",
    "funder": "",
    "funder_type": NS,
    "program": NS,
    "opportunity_type": NS,
    "themes": [],
    "url": "",
    "source_urls": [],
    "status": "monitoring",
    "status_basis": "official",
    "published_date": NS,
    "deadline": None,
    "deadline_timezone": NS,
    "deadline_text": NS,
    "funding_amount_min": None,
    "funding_amount_max": None,
    "currency": NS,
    "funding_text": NS,
    "duration": NS,
    "duration_months_max": None,
    "covers_staff_costs": NS,     # can the grant pay researchers' salaries/personnel?
    "support_type": NS,
    "eligible_applicants": NS,
    "eligible_countries": NS,
    "international_orgs_eligible": "unclear",
    "cgiar_eligible": "unclear",
    "cgiar_eligibility_notes": NS,
    "lead_applicant_requirements": NS,
    "geographic_restrictions": NS,
    "consortium_required": NS,
    "consortium_details": NS,
    "cofunding_required": NS,
    "cofunding_details": NS,
    "eligible_activities": NS,
    "required_documents": NS,
    "application_procedure": NS,
    "eligibility_assessment": "potentially_eligible",
    "scientific_alignment": 0,
    "scientific_alignment_rationale": NS,
    "strategic_relevance": 0,
    "strategic_relevance_rationale": NS,
    "technical_feasibility": 0,
    "technical_feasibility_rationale": NS,
    "recommendation": NS,
    "potential_partners": NS,
    "next_action": NS,
    "evidence": {},
    "unverified_fields": [],
    "verification_notes": NS,
    "last_verified": NS,
    "verification_source": NS,
    "first_seen": NS,
    "history": [],
}

# Fields whose change triggers an "eligibility or funding conditions changed" alert.
WATCHED_FIELDS = ("deadline", "status", "funding_amount_min", "funding_amount_max",
                  "currency", "eligible_applicants", "eligible_countries",
                  "international_orgs_eligible", "cgiar_eligible", "consortium_required",
                  "cofunding_required", "eligibility_assessment")


def slugify(text: str, maxlen: int = 70) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:maxlen].rstrip("-")


def parse_deadline(value) -> datetime | None:
    """Parse ISO date/datetime strings (or date objects). Returns naive datetime or None."""
    if value in (None, "", NS, "null"):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59)
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T23:59"   # date-only deadlines: assume end of day
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _num(v):
    if v in (None, "", NS):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").replace("_", ""))
    except ValueError:
        return None


def _score(v) -> int:
    try:
        return max(0, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def normalize(rec: dict) -> dict:
    """Return a record with every field present, values coerced to the schema."""
    out = {}
    for key, default in FIELDS.items():
        val = rec.get(key, default)
        if val in (None, "") and isinstance(default, str) and default == NS:
            val = NS
        out[key] = val if val is not None or default is None else default
    # keep unknown extra keys (forward compatibility)
    for k, v in rec.items():
        if k not in out:
            out[k] = v

    if not out["id"]:
        out["id"] = slugify(f"{out['funder']}-{out['title']}")
    out["themes"] = [t for t in (out["themes"] or []) if t in THEMES]
    out["source_urls"] = list(dict.fromkeys(out["source_urls"] or []))
    out["unverified_fields"] = list(out["unverified_fields"] or [])
    out["evidence"] = dict(out["evidence"] or {})
    out["history"] = list(out["history"] or [])
    out["funding_amount_min"] = _num(out["funding_amount_min"])
    out["funding_amount_max"] = _num(out["funding_amount_max"])
    for k in ("scientific_alignment", "strategic_relevance", "technical_feasibility"):
        out[k] = _score(out[k])
    if out["status"] not in STATUSES:
        out["status"] = "monitoring"
    if out["status_basis"] not in STATUS_BASIS:
        out["status_basis"] = "speculative"
    if out["eligibility_assessment"] not in ELIGIBILITY:
        out["eligibility_assessment"] = "potentially_eligible"
    for k in ("international_orgs_eligible", "cgiar_eligible"):
        if str(out[k]).lower() not in YES_NO_UNCLEAR:
            out[k] = "unclear"
        out[k] = str(out[k]).lower()
    if out["consortium_required"] not in CONSORTIUM:
        out["consortium_required"] = NS
    dl = parse_deadline(out["deadline"])
    if out["covers_staff_costs"] not in STAFF_COSTS:
        out["covers_staff_costs"] = NS
    if out["support_type"] not in SUPPORT_TYPES:
        out["support_type"] = NS
    if out["opportunity_type"] == "cloud_credits":   # credits never pay salaries
        out["support_type"] = "in_kind_resources"
        out["covers_staff_costs"] = "no"
    dm = _num(out["duration_months_max"])
    out["duration_months_max"] = int(dm) if dm else None
    out["deadline"] = dl.strftime("%Y-%m-%dT%H:%M") if dl else None
    for k in ("published_date", "last_verified", "first_seen"):
        if isinstance(out[k], (date, datetime)):
            out[k] = out[k].strftime("%Y-%m-%d")
    return out


def funding_scope(rec: dict) -> str:
    """Classify how much a call can sustain a team:
    staff_multi_year | staff | no_staff (cash, but not salaries) | resources_only (credits/in-kind) | unknown."""
    if rec.get("support_type") == "in_kind_resources":
        return "resources_only"
    if rec.get("covers_staff_costs") == "no":
        return "no_staff"
    if rec.get("covers_staff_costs") in ("yes", "partial"):
        dm = rec.get("duration_months_max")
        return "staff_multi_year" if dm and dm >= 24 else "staff"
    return "unknown"


def validate(rec: dict) -> list[str]:
    """Return a list of integrity problems (empty list = valid)."""
    problems = []
    for req in ("id", "title", "funder", "url"):
        if not rec.get(req):
            problems.append(f"missing required field '{req}'")
    url = rec.get("url") or ""
    if url and not re.match(r"^https?://", url):
        problems.append(f"url is not http(s): {url}")
    if rec.get("status") == "open" and rec.get("status_basis") != "official":
        problems.append("status 'open' requires status_basis 'official'")
    if rec.get("status") in ("open", "rolling") and rec.get("last_verified") in (NS, None, ""):
        problems.append("open/rolling records must have last_verified")
    if rec.get("deadline") and rec.get("deadline_text") in (NS, None, ""):
        problems.append("deadline present but deadline_text (verbatim) missing")
    if (rec.get("funding_amount_min") and rec.get("funding_amount_max")
            and rec["funding_amount_min"] > rec["funding_amount_max"]):
        problems.append("funding_amount_min > funding_amount_max")
    if (rec.get("funding_amount_min") or rec.get("funding_amount_max")) and rec.get("currency") in (NS, None, ""):
        problems.append("funding amount present without currency")
    if rec.get("eligibility_assessment") == "confirmed_eligible" and rec.get("cgiar_eligible") == "no":
        problems.append("confirmed_eligible contradicts cgiar_eligible = no")
    return problems
