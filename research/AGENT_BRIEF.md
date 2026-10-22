# Research brief for funding-verification agents

Today is **2026-10-14**. You are verifying funding opportunities for a researcher at the
**Alliance of Bioversity International and CIAT** (a CGIAR center; legal entities: Bioversity
International, registered in Italy, and CIAT, an international organization headquartered in
Cali, Colombia; the Alliance has offices in Latin America, Africa and Asia). Research areas:
Climate Action and Multifunctional Landscapes.

Researcher profile (from CV): Research Specialist at CIAT (Colombian national). PhD Univ. of
Tokyo (plant phenotyping with remote sensing + ML), MPhil Univ. of Manchester (ML/big data for
satellite rice phenology). Skills: Python, R, Google Earth Engine, Sentinel-1/2, Landsat, MODIS,
UAV and hyperspectral imaging, deep learning (TensorFlow), process-based crop modelling
(site-specific crop modelling system for Honduras; Degrees Initiative grant on stratospheric
aerosol injection impacts on maize/rice in South America, 2027-2028), data mining, climate-smart
agriculture. Interests: climate adaptation, digital agriculture/advisory tools, EO, AI/geospatial
AI/foundation models, crop modelling/yield forecasting, climate data infrastructure, landscapes,
food security/smallholders, open-source research software.

## Rules (strict)
1. Use **official funder pages and original call documents** as primary sources (WebSearch to
   find, WebFetch to read). Secondary sources (news, aggregators like fundsforngos) may only be
   used to discover leads; every reported fact must be confirmed on an official page.
2. Only report opportunities that are **open, rolling/continuous, or officially announced as
   upcoming** as of 2026-10-14. Closed calls: only include if the funder officially states a next
   cycle (then status=upcoming or monitoring, and say so). Never label something "open" without an
   official application process being available.
3. **Never invent** amounts, deadlines, eligibility, documents. If not stated, use the literal
   string "Not specified". If you could not load the official page, set status="monitoring" and put
   the gap in `unverified_fields`.
4. Record **verbatim quotes** (short) for deadline and eligibility in `evidence`.
5. Check institutional eligibility carefully: can an international organization / CGIAR center /
   non-national institution apply, as lead or as partner? Is a consortium needed? Country limits?
6. Priority: opportunities that can **pay research staff and sustain multi-year work** (project,
   programme or fellowship funding) matter more than compute credits or short travel grants.
   Always record whether personnel costs are eligible (`covers_staff_costs`, with a quote in
   `evidence.staff_costs_quote`) and the maximum duration in months.
7. Quality over quantity: 3-8 well-verified records per brief is ideal. Also list funder pages that
   are worth monitoring even if nothing is open now (`monitor_sources`).
8. Note: USAID was largely dismantled in 2025 — do not report USAID calls unless an official,
   current page proves one exists.

## Output
Write a single JSON file (UTF-8) at the path given in your task with this shape:

```json
{
  "group": "<group name>",
  "searched_on": "2026-10-14",
  "opportunities": [
    {
      "title": "...",
      "funder": "...",
      "funder_type": "multilateral|national_agency|foundation|tech_company|research_partnership|bilateral|cgiar|regional_fund",
      "program": "...",
      "opportunity_type": "grant|research_award|challenge|fellowship|cloud_credits|consortium_call|prize|accelerator|tender",
      "themes": ["climate_adaptation","climate_mitigation","climate_smart_ag","digital_agriculture","remote_sensing","ai_ml","crop_modeling","climate_data_infrastructure","multifunctional_landscapes","biodiversity","food_security","smallholders","open_source_software","capacity_building"],
      "url": "official call page URL (must load)",
      "source_urls": ["other official URLs used, e.g. guidelines PDF"],
      "status": "open|upcoming|rolling|monitoring",
      "status_basis": "official|speculative",
      "published_date": "YYYY-MM-DD or Not specified",
      "deadline": "YYYY-MM-DDTHH:MM or YYYY-MM-DD or null",
      "deadline_timezone": "e.g. CET, ET, UTC or Not specified",
      "deadline_text": "verbatim from the page",
      "funding_amount_min": null, "funding_amount_max": null,
      "currency": "USD|EUR|GBP|CAD|... or Not specified",
      "funding_text": "verbatim/near-verbatim description",
      "duration": "... or Not specified",
      "duration_months_max": null,
      "covers_staff_costs": "yes|partial|no|Not specified (can the grant pay the applicant's researcher salaries?)",
      "support_type": "project_funding|fellowship_salary|core_or_program_funding|in_kind_resources|prize",
      "eligible_applicants": "...",
      "eligible_countries": "...",
      "international_orgs_eligible": "yes|no|unclear",
      "cgiar_eligible": "yes|no|unclear",
      "cgiar_eligibility_notes": "how CIAT/Alliance could apply: lead / partner / via national partner / not at all",
      "lead_applicant_requirements": "...",
      "geographic_restrictions": "...",
      "consortium_required": "yes|no|optional",
      "consortium_details": "...",
      "cofunding_required": "yes|no|Not specified",
      "cofunding_details": "...",
      "eligible_activities": "...",
      "required_documents": "...",
      "application_procedure": "...",
      "eligibility_assessment": "confirmed_eligible|potentially_eligible|confirmed_ineligible",
      "scientific_alignment": 0,
      "scientific_alignment_rationale": "0-5 rubric: 5 = core topic matches RS/AI/crop modelling/climate-ag directly; 3 = thematically relevant but our methods are secondary; 1 = tangential",
      "strategic_relevance": 0,
      "strategic_relevance_rationale": "0-5: fit with Alliance/CGIAR mission, partnerships, scale, LAC/Africa/Asia focus",
      "technical_feasibility": 0,
      "technical_feasibility_rationale": "0-5: can our team deliver with existing capabilities",
      "recommendation": "why (or why not) to pursue",
      "potential_partners": "...",
      "next_action": "concrete next step",
      "evidence": {"deadline_quote": "...", "eligibility_quote": "...", "status_quote": "..."},
      "unverified_fields": ["fields you could not confirm on official pages"],
      "verification_notes": "what you loaded and when; any caveats"
    }
  ],
  "monitor_sources": [
    {"funder": "...", "name": "...", "url": "official listing/news page to watch", "type": "html|rss|api", "why": "..."}
  ],
  "rejected_leads": [
    {"title": "...", "url": "...", "reason": "closed / ineligible / could not verify / not relevant"}
  ]
}
```

Also include in `opportunities` items that are topically strong but where the Alliance is
**confirmed ineligible** only if they are useful as partner opportunities (e.g., a national
partner leads), and say so explicitly.
