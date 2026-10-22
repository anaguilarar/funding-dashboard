# Research Funding Intelligence Dashboard

A small, open-source monitoring system for the **Alliance of Bioversity International and CIAT**
(Climate Action & Multifunctional Landscapes). It keeps a curated set of **verified** funding
opportunities, monitors official funder pages and funding APIs for changes and new calls,
re-checks records, archives expired calls, scores research fit and institutional eligibility,
generates a searchable dashboard, and sends alert digests.

Open the dashboard: **`site/index.html`**. It is a single self-contained file that works offline
and can be shared by email, Teams or SharePoint.

---

## 1. Architecture

```
            ┌──────────────────────────── scheduled run (Windows Task Scheduler) ───────────────────────────┐
            │                                                                                               │
 data/opportunities/*.yaml ──► verify ──► (link check, page-change hash, deadline expiry, staleness)         │
 (verified records)              │        expired ──► data/archive/   unreachable ──► needs_reverification   │
                                 ▼                                                                          │
 data/sources.yaml ─────────► monitor ──► funder pages (HTML diff + new links), RSS, Grants.gov API,         │
 (watched pages + API queries)   │        EU Funding & Tenders API ──► data/candidates/*.yaml (UNVERIFIED)  │
                                 ▼                                                                          │
                              build ────► site/index.html + site/data.json (dashboard)                      │
                                 ▼                                                                          │
                              notify ───► reports/digest-YYYY-MM-DD.md  (+ optional email / Teams / Slack)  │
            └───────────────────────────────────────────────────────────────────────────────────────────────┘
 state: data/state/ (page hashes, failure counters, sent-alert keys, changelog.jsonl)
```

**Stack** (all free and open source): Python 3.10+ with `requests`, `PyYAML`, `beautifulsoup4`
and `lxml`, plus a static HTML/JS dashboard with no server and no build step. Scheduling uses
Windows Task Scheduler. Data is stored as human-readable YAML files, one per opportunity, so the
history can be put under git and a colleague can review or edit a record in any text editor.

**Paid services or keys:** none are required. Grants.gov and the EU Funding & Tenders search API
are public and need no key. Email alerts need an SMTP account. On CGIAR Microsoft 365, SMTP AUTH
may have to be enabled by IT. Teams or Slack alerts need a webhook URL, which you create yourself
in Teams or Slack at no cost.

### Design principle: discovery ≠ verification

Automation **discovers** leads and **maintains** verified records. It never publishes an
unverified call as an opportunity:

| Layer | Who/what | Shown where |
|---|---|---|
| Leads | The monitor, from page changes, new links and API hits | "Leads to verify" tab, labelled unverified |
| Verified records | A person, or a Claude research session, checks the official documents and then ingests or promotes the record | "Active opportunities" |
| Maintenance | `verify` runs automatically: link checks, page-change and closure detection, possible deadline extensions, expiry → archive | Flags on records, Activity log, digest |

---

## 2. Installation

```powershell

python -m pip install -r requirements.txt
python -m pytest -q                 # 12 tests, offline
python -m fundintel run             # verify -> monitor -> build -> notify
start site\index.html
```

### Schedule the automatic run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1      # register/update
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Unregister
```

The schedule comes from `config.yaml → monitoring.schedule` (default: daily 07:00). If the PC
is off at that time, the task runs at the next opportunity. Logs are written to
`logs\run-YYYY-MM.log`. The monitoring only runs while this PC is on. For a shared,
always-on setup, run the same commands on a server or VM.

### Notifications

Edit `config.yaml → notifications.channels` (for example `["file", "email"]`) and set the
environment variables for the channels you use. Use user-level variables so that the
scheduled task can read them:

```powershell
[Environment]::SetEnvironmentVariable("FUNDINTEL_SMTP_HOST", "smtp.office365.com", "User")
[Environment]::SetEnvironmentVariable("FUNDINTEL_SMTP_PORT", "587", "User")
[Environment]::SetEnvironmentVariable("FUNDINTEL_SMTP_USER", "you@cgiar.org", "User")
[Environment]::SetEnvironmentVariable("FUNDINTEL_SMTP_PASSWORD", "<app password>", "User")
[Environment]::SetEnvironmentVariable("FUNDINTEL_TEAMS_WEBHOOK", "<Teams Workflows webhook URL>", "User")
```

Each alert is sent **once**. Deadline reminders fire at 45, 21, 14, 7 and 3 days, which you can
change in `config.yaml`. The digest is written to `reports/` on every run, whatever channels
are set.

---

## 3. Data model (one YAML per opportunity)

Key fields are: `title`, `funder`, `funder_type`, `program`, `opportunity_type`, `themes`, `url`
(the official call page), `source_urls`, `status` (open | rolling | upcoming | monitoring |
needs_reverification | closed), `status_basis` (official | speculative), `published_date`,
`deadline` (ISO), `deadline_timezone`, `deadline_text` (verbatim), funding fields, `duration`,
`duration_months_max`, `covers_staff_costs` (yes | partial | no), `support_type`,
eligibility fields (`eligible_applicants`, `eligible_countries`, `international_orgs_eligible`,
`cgiar_eligible`, `cgiar_eligibility_notes`, `lead_applicant_requirements`,
`geographic_restrictions`), `consortium_required/_details`, `cofunding_required/_details`,
`eligible_activities`, `required_documents`, `application_procedure`, `eligibility_assessment`,
the three subjective scores with rationales, `recommendation`, `potential_partners`,
`next_action`, `evidence` (verbatim quotes), `unverified_fields`, `verification_notes`,
`last_verified`, `verification_source`, `first_seen`, `history`.

The dashboard derives a **funding scope** from these: *Funds staff · multi-year* (salaries
allowed and at least 24 months), *Funds staff*, *Credits / in-kind* (cloud credits never pay
salaries), or unknown. Use the "Funding scope" filter or the KPI tile to focus on calls that
can sustain a team.

Any value that the funder does not publish is stored as **`Not specified`**. The schema is
defined in `fundintel/models.py`. `python -m fundintel validate` enforces integrity rules,
for example: "open" requires an official basis, a deadline requires its verbatim text, and an
amount requires a currency.

---

## 4. Scoring

There are five criteria, each scored 0–5. Weights are set in `config.yaml`:

| Criterion | Weight | Type |
|---|---|---|
| Scientific alignment | 30% | Subjective (rationale stored) |
| Institutional eligibility | 25% | Derived from verified eligibility facts |
| Technical feasibility | 15% | Subjective |
| Strategic relevance | 15% | Subjective |
| Application feasibility | 15% | Derived from status, days to deadline, consortium and co-funding needs |

**Gates:**
- Confirmed ineligible: score is at most 25.
- Eligibility unclear: at most 69, so the record cannot be "high".
- Essential facts unverified: at most 69.
- Monitoring or speculative: at most 60.
- Weak scientific alignment (2/5 or less): at most 69.

Tiers are high (70 or more) and medium (50 or more). The *Method & scoring* tab of the
dashboard shows the full rules.

---

## 5. Operating procedures

### Weekly routine (about 20 minutes)
1. Open the dashboard. Check **Deadlines ≤ 45 days** and **Needs re-verification**.
2. In **Leads to verify**, open the promising leads and read the official call documents. Then
   either reject the lead:
   ```powershell
   python -m fundintel reject <lead-id>          # never suggested again
   ```
   or complete the YAML in `data/candidates/<lead-id>.yaml` with every schema field, setting
   `status`, `last_verified`, eligibility fields and `deadline_text`. Then promote it:
   ```powershell
   python -m fundintel promote <lead-id>
   ```
3. For flagged records (call page changed, unreachable, possible deadline change), re-read the
   official page. Update the YAML, including `last_verified`, or re-ingest it with
   `python -m fundintel ingest file.yaml`. Any change to the deadline, status, eligibility or
   funding fields is logged and triggers an alert.
4. **Before preparing any application, re-verify the call on the official page.** A working
   website does not prove that a call is still open.

### Research refresh with Claude (monthly or quarterly)
New calls are often published on pages the monitor does not watch. The research brief at
`research/AGENT_BRIEF.md` defines the verification rules and the JSON output format. Ask Claude
Code to "run a funding research refresh using research/AGENT_BRIEF.md". Then:
```powershell
python -m fundintel ingest research\raw\<group>.json   # de-duplicates; updates existing records
python scripts\build_sources.py                         # adds newly suggested pages to watch
python -m fundintel build
```

### Maintenance
- `python -m fundintel linkcheck` checks every official URL and watched source.
- Watched sources are listed in `data/sources.yaml`. Set `enabled: false` to disable a noisy
  source. Raise `min_relevance` on a source to filter it more tightly.
- Keyword lists and API queries are set in `config.yaml → keywords` and in `data/sources.yaml →
  api_queries`.
- Archive: deadline-passed records move to `data/archive/` and stay visible in the *Archive* tab.
  When a new cycle opens, ingesting the new call moves the record back to the active list and
  keeps its history.
- Back up or version the `data/` folder, for example with `git init` and regular commits.

---

## 6. Known limitations (honest status)

- **Automated:** link and status checks, page-change detection, expiry and archiving, API lead
  discovery (Grants.gov and EU F&T), dashboard rebuilds and digest files. These are tested
  offline by `tests/` and were run against the live sources during setup.
- **Not automated:** verifying new leads into records still needs a person, or a Claude-assisted
  research session, to read the official documents. This is intentional.
- Some funders block automated requests (for example ACIAR returns 403 and Nestlé Foundation
  returns 403) or render with JavaScript (the EU portal topic pages). For these the monitor
  either relies on the API or flags the source. Check them manually; see the *Monitored
  sources* tab.
- Page-change detection on pages with frequently changing content (such as news tickers) can
  produce noise. Disable those sources or raise their `min_relevance`.
- Approximate USD conversion (`config.yaml → scoring.fx_to_usd`) is used only for sorting and
  filtering. It is never displayed as a fact.
