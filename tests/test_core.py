"""Tests for de-duplication, expiry/archiving, unreachable handling, scoring gates and digests.

Run:  python -m pytest -q
All tests use a temporary copy of the config pointing to a temp data folder (no network).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from fundintel import dashboard, ingest, notify, verify
from fundintel import fetch as F
from fundintel.models import NS, normalize, validate
from fundintel.scoring import score
from fundintel.store import find_duplicate, load_config, load_dir, p

NOW = datetime(2026, 10, 14, 12, 0)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = copy.deepcopy(load_config())
    for k in ("opportunities", "archive", "candidates", "state", "site", "reports"):
        c["paths"][k] = str(tmp_path / k)
    c["paths"]["sources"] = str(tmp_path / "sources.yaml")
    (tmp_path / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
    c["monitoring"]["polite_delay_s"] = 0
    return c


def rec(**kw):
    base = dict(title="AI for Climate Resilient Agriculture Call 2026", funder="Example Foundation",
                url="https://example.org/calls/ai-climate-ag", status="open", status_basis="official",
                deadline="2026-12-15T17:00", deadline_text="15 December 2026, 17:00 CET",
                deadline_timezone="CET", eligibility_assessment="confirmed_eligible",
                cgiar_eligible="yes", international_orgs_eligible="yes",
                scientific_alignment=5, technical_feasibility=5, strategic_relevance=4,
                last_verified="2026-10-14", themes=["ai_ml", "remote_sensing", "bogus_theme"])
    base.update(kw)
    return base


def test_normalize_fills_not_specified_and_filters_themes():
    r = normalize({"title": "X", "funder": "F", "url": "https://x.org"})
    assert r["duration"] == NS and r["required_documents"] == NS
    r2 = normalize(rec())
    assert "bogus_theme" not in r2["themes"]


def test_validate_rejects_open_speculative_and_missing_currency():
    assert any("status_basis" in pr for pr in validate(normalize(rec(status_basis="speculative"))))
    assert any("currency" in pr for pr in validate(normalize(rec(funding_amount_max=100000))))
    assert validate(normalize(rec())) == []


def test_duplicate_detection_url_and_title():
    a = normalize(rec())
    b = normalize(rec(url="https://www.example.org/calls/ai-climate-ag/", title="Other"))
    c = normalize(rec(url="https://mirror.net/x", title="AI for Climate-Resilient Agriculture - Call for Proposals"))
    d = normalize(rec(url="https://mirror.net/y", title="Totally different oceans programme", funder="Other Org"))
    assert find_duplicate(b, [a]) is not None
    assert find_duplicate(c, [a]) is not None
    assert find_duplicate(d, [a]) is None


def test_ingest_dedupes_and_tracks_changes(cfg):
    assert ingest.upsert(cfg, rec())[0] == "added"
    action, r = ingest.upsert(cfg, rec(deadline="2027-01-15T17:00", deadline_text="15 January 2027"))
    assert action == "updated"
    assert len(load_dir(p(cfg, "opportunities"))) == 1
    stored = load_dir(p(cfg, "opportunities"))[0]
    assert stored["deadline"] == "2027-01-15T17:00"
    assert any(h["event"] == "reverified" for h in stored["history"])


def test_long_funder_id_collision_keeps_both_calls(cfg):
    funder = "U.S. Department of Commerce - National Oceanic and Atmospheric Administration (NOAA), " + "x" * 40
    a = rec(funder=funder + " NESDIS", title="NOAA NESDIS Broad Agency Announcement FY2027-2028",
            url="https://www.grants.gov/search-results-detail/364069")
    b = rec(funder=funder + " OAR", title="NOAA Oceanic and Atmospheric Research Broad Agency Announcement FY2027-2029",
            url="https://www.grants.gov/search-results-detail/364130")
    assert ingest.upsert(cfg, a)[0] == "added"
    assert ingest.upsert(cfg, b)[0] == "added"
    assert len(load_dir(p(cfg, "opportunities"))) == 2


def test_funding_scope():
    from fundintel.models import funding_scope
    assert funding_scope(normalize(rec(opportunity_type="cloud_credits"))) == "resources_only"
    assert funding_scope(normalize(rec(covers_staff_costs="yes", duration_months_max=36))) == "staff_multi_year"
    assert funding_scope(normalize(rec(covers_staff_costs="partial", duration_months_max=12))) == "staff"
    assert funding_scope(normalize(rec())) == "unknown"


def test_ingest_rejects_invalid(cfg):
    action, _ = ingest.upsert(cfg, rec(url="not-a-url"))
    assert action.startswith("rejected")


def test_expired_call_is_archived(cfg):
    ingest.upsert(cfg, rec(deadline="2026-10-01", deadline_text="1 October 2026"))
    verify.run(cfg, online=False, now=NOW)
    assert load_dir(p(cfg, "opportunities")) == []
    arch = load_dir(p(cfg, "archive"))
    assert len(arch) == 1 and arch[0]["status"] == "closed"


def test_rolling_never_expires(cfg):
    ingest.upsert(cfg, rec(status="rolling", deadline=None, deadline_text=NS))
    verify.run(cfg, online=False, now=NOW)
    assert len(load_dir(p(cfg, "opportunities"))) == 1


def test_unreachable_flags_but_does_not_close(cfg, monkeypatch):
    ingest.upsert(cfg, rec())
    monkeypatch.setattr(F, "fetch", lambda url, c: F.FetchResult(url, False, None, url, error="ConnectionError"))
    for _ in range(cfg["monitoring"]["failures_before_flag"]):
        verify.run(cfg, online=True, now=NOW)
    r = load_dir(p(cfg, "opportunities"))[0]
    assert r["status"] == "needs_reverification"
    assert load_dir(p(cfg, "archive")) == []


def test_page_change_detects_closed_and_extension(cfg, monkeypatch):
    ingest.upsert(cfg, rec())
    pages = iter(["Call open. Deadline: 15 December 2026.",
                  "Update: the deadline has been extended. Deadline: 20 January 2027."])
    monkeypatch.setattr(F, "fetch", lambda url, c: F.FetchResult(url, True, 200, url, text=next(pages)))
    verify.run(cfg, now=NOW)
    verify.run(cfg, now=NOW)
    r = load_dir(p(cfg, "opportunities"))[0]
    assert "call_page_changed" in r["flags"]
    assert any(f.startswith("possible_deadline_change:2027-01-20") for f in r["flags"])


def test_scoring_gates(cfg):
    good = score(normalize(rec()), cfg, NOW)
    assert good["tier"] == "high"
    pot = score(normalize(rec(eligibility_assessment="potentially_eligible", cgiar_eligible="unclear")), cfg, NOW)
    assert pot["score"] <= 69 and pot["tier"] != "high"
    inel = score(normalize(rec(eligibility_assessment="confirmed_ineligible", cgiar_eligible="no")), cfg, NOW)
    assert inel["tier"] == "ineligible" and inel["score"] <= 25
    unv = score(normalize(rec(unverified_fields=["deadline"])), cfg, NOW)
    assert unv["score"] <= 69
    spec = score(normalize(rec(status="upcoming", status_basis="speculative")), cfg, NOW)
    assert spec["score"] <= 60
    weak = score(normalize(rec(scientific_alignment=2)), cfg, NOW)
    assert weak["tier"] != "high"


def test_digest_and_dashboard(cfg):
    ingest.upsert(cfg, rec(deadline=(NOW + timedelta(days=10)).strftime("%Y-%m-%d"),
                           deadline_text="in ten days"))
    text, keys, _ = notify.build_digest(cfg, NOW)
    assert "Deadlines approaching" in text and "https://example.org/calls/ai-climate-ag" in text
    out = dashboard.build(cfg, NOW)
    html = open(out, encoding="utf-8").read()
    assert "AI for Climate Resilient Agriculture" in html and "/*__DATA__*/" not in html


def test_digest_alerts_only_once(cfg):
    ingest.upsert(cfg, rec())
    r1 = notify.send(cfg, NOW)
    r2 = notify.send(cfg, NOW)
    assert r1["alerts"] > 0 and r2["alerts"] == 0


def test_same_day_digest_appends(cfg):
    ingest.upsert(cfg, rec())
    r1 = notify.send(cfg, NOW)
    ingest.upsert(cfg, rec(title="Second call on crop yield forecasting", url="https://example.org/second"))
    notify.send(cfg, NOW)
    text = open(r1["file"], encoding="utf-8").read()
    assert "AI for Climate Resilient Agriculture" in text and "# Update" in text
    assert "Second call on crop yield forecasting" in text
