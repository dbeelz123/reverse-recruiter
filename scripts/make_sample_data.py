"""Build sample-data/: a fictional candidate's data folder, so every engine script runs end to end.

Usage:  python -B scripts/make_sample_data.py [--out sample-data]

Everything here is invented: the candidate (Jordan Avery), every employer, posting, connection, recruiter and
interview. Company names are made up and any resemblance to real ones is accidental. Job IDs start with 91 and
links point to example.com, so nothing here refers to a real listing.

The script writes the inputs a user (and Claude's judgment steps) would have produced over two rounds, then runs
the engine itself for everything mechanical: reports, metrics, the apply queue, interview records, open checks.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine"


MANIFEST = ".sample-manifest.json"


def digest(path):
    """SHA-256 of a file with line endings normalized, so a Windows checkout (CRLF) matches what was generated."""
    import hashlib
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write_manifest(out):
    """Record every generated file and its hash. Only a folder whose files all still match is ever replaced."""
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != MANIFEST)
    write(out / MANIFEST, {p.relative_to(out).as_posix(): digest(p) for p in files})


def changes(out):
    """Why `out` isn't an untouched folder made by this script ([] if it is). A copy of the README or of the whole
    folder isn't enough: any file added or edited since generation means it holds someone's work."""
    m = out / MANIFEST
    if not m.is_file():
        return [f"no {MANIFEST} (not made by this script)"]
    try:
        known = json.loads(m.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [f"{MANIFEST} is damaged"]
    out_of_place = []
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != MANIFEST):
        rel = f.relative_to(out).as_posix()
        if rel not in known:
            out_of_place.append(f"added: {rel}")
        elif known[rel] != digest(f):
            out_of_place.append(f"changed: {rel}")
    return out_of_place


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, indent=1, ensure_ascii=False)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def run(*args):
    r = subprocess.run([sys.executable, "-B", *map(str, args)], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


# ---- the candidate ------------------------------------------------------------------------------------------------

CAREER_MASTER = """
# Career master record: Jordan Avery (fictional sample)

*The only source of claims for cover letters, tailored resumes, primers and thank-you notes. Titles, dates and
timeline never change; tailoring selects, orders and rewords bullets but never adds facts. Everything in this
sample is invented.*

**Tags** used to match bullets to postings: `logistics` `visibility` `api` `integrations` `platform` `warehouse`
`pricing` `gtm` `partners` `customer-discovery` `prototyping` `portfolio` `leadership` `metrics` `ai` `enablement`

## Summary building blocks
- `logistics` `platform` 11 years in supply-chain software: shipment visibility, carrier integrations and warehouse systems, from analyst to senior product manager.
- `customer-discovery` `prototyping` Starts from the customer's workflow: ride-alongs with dispatchers, warehouse floor visits, prototypes in the first two weeks.
- `ai` Current focus: ETA prediction and exception triage with machine-learning models; uses AI coding assistants daily for prototypes and analysis.

## Quantified results
- `visibility` `metrics` Grew the shipment-visibility product from 40 to 310 enterprise shippers in four years; net revenue retention 118%.
- `api` `integrations` Cut new-carrier onboarding from 9 weeks to 12 days by replacing one-off integrations with a self-serve carrier API and certification suite.
- `pricing` Introduced usage-based pricing for the tracking API; 22% of new revenue in its first year.

## Experience

### Senior Product Manager, Tidewater Logistics Software (Remote) · Mar 2019 – Oct 2026
- `visibility` `platform` Owned the real-time shipment-visibility platform (tracking, ETA prediction, exception alerts) used by 310 enterprise shippers.
- `api` `integrations` `partners` Led the carrier-integration program: a public REST API, webhooks and a certification suite for 1,400 carriers.
- `ai` `metrics` Shipped an ML-based ETA model with the data-science team; on-time prediction accuracy rose from 71% to 89%.
- `pricing` `gtm` Defined packaging and usage-based pricing for the tracking API; trained sales and solutions engineers on the new model.
- `leadership` `enablement` Mentored two associate PMs; ran quarterly roadmap reviews with sales, support and the executive team.

### Product Manager, Parcelwise (Chicago, IL) · Jun 2015 – Mar 2019
- `warehouse` `integrations` Managed warehouse-management integrations (pick, pack, label) for mid-market e-commerce shippers.
- `customer-discovery` `prototyping` Ran 60+ customer interviews and floor visits to redesign the returns workflow; return processing time fell 35%.
- `portfolio` Took over a three-product portfolio after a reorganization and retired the weakest product within a year.

### Business Analyst, Granite Data Systems (Springfield, IL) · Jul 2013 – Jun 2015
- `metrics` Built freight-cost reporting in SQL for 30 regional shippers.

## Education and certifications
- B.S. Industrial Engineering, a state university (2013).
- Certified Scrum Product Owner (2017).

## Not in the history (don't claim)
- No regulated-industry (healthcare, pharma, finance) product experience.
- No people management beyond mentoring.
- No hardware or telematics device experience.
"""

VOICE_GUIDE = """
# Voice guide: Jordan Avery (fictional sample)

Style only; facts come from `career-master.md`.

## How Jordan writes
- Short sentences, active voice, the decision first and then the result.
- Plain words over jargon: "cut onboarding from 9 weeks to 12 days", not "drove efficiencies".
- No hype words (passionate, rockstar, game-changing) and no em dashes.
- Closes with one concrete next step, not a flourish.

## Edits to drafts (strongest voice evidence; add every new one)
| Draft | Jordan's edit | Lesson |
|---|---|---|
| "I am excited to leverage my extensive experience" | "I've spent four years on exactly this problem" | Lead with the fit, skip the adjectives |
"""

PROFILE = {
    "name": "Jordan Avery (fictional sample)",
    "headline": "Senior Product Manager, supply-chain and logistics software",
    "skills": ["shipment visibility", "carrier integrations", "REST APIs and webhooks", "usage-based pricing",
               "warehouse management integrations", "ETA prediction (with data science)", "SQL", "customer discovery"],
    "sources": {"resume": "4-profile/resume/ (not included in the sample)", "calibration": "6-system/calibration/"},
}

# ---- criteria -----------------------------------------------------------------------------------------------------

SPEC = {
    "version": "0.2",
    "updated": "2026-11-14",
    "status_legend": {"proposed": "suggested by the agent, not yet confirmed", "confirmed": "confirmed in calibration",
                      "rejected": "considered and turned down"},
    "target_roles": {
        "titles": ["Senior Product Manager", "Staff Product Manager", "Principal Product Manager"],
        "domain_clusters": {"core": "shipment visibility, carrier and logistics integrations, supply-chain platforms",
                            "adjacent": "warehouse and fleet software, B2B APIs, marketplaces"},
    },
    "work_arrangement": {
        "rule": "Remote anywhere in the US. Hybrid or on-site only within 50 miles of Springfield, IL.",
        "machine_rule": {"remote": "anywhere in the US",
                         "hybrid_onsite_center": {"name": "Springfield, IL", "lat": 39.7817, "lon": -89.6501,
                                                  "linkedin_geo_id": "000000000"},
                         "radius_miles": 50},
    },
    "dealbreakers": [
        {"value": "Hybrid or on-site more than 50 miles from Springfield, IL", "type": "objective",
         "evidence": "stated in setup", "status": "confirmed"},
        {"value": "Defense or weapons programs (employer or customers)", "type": "values",
         "evidence": "calibration round 1 q2", "status": "confirmed",
         "rescreen_regex": r"\b(defense|munitions|weapons|DoD)\b"},
        {"value": "Travel above 30%", "type": "objective", "evidence": "calibration round 1 q3", "status": "confirmed",
         "rescreen_regex": r"\b([4-9]\d|3[1-9])\s?%\s+travel|travel[^.]{0,30}\b([4-9]\d|3[1-9])\s?%"},
        {"value": "People management of other product managers as the core of the role", "type": "preference",
         "evidence": "calibration round 2 q1", "status": "confirmed", "title_regex": r"\b(director|head of|group)\b"},
    ],
    "negatives": [
        {"value": "Data-platform or analytics companies (selling the data stack itself)", "weight": "-8",
         "evidence": "calibration round 1 q4", "status": "confirmed", "rescreen_regex": r"\bdata (platform|warehouse|lakehouse)\b"},
        {"value": "Consumer web or mobile scope", "weight": "-8", "evidence": "calibration round 1 q4",
         "status": "confirmed", "rescreen_regex": r"\b(consumer app|mobile app|shoppers)\b"},
        {"value": "Travel 10-30%: sliding scale, -0.4 per 1%", "weight": "sliding", "status": "confirmed"},
    ],
    "positives": [
        {"value": "1st-degree connection at the company", "weight": "+8", "status": "confirmed"},
        {"value": "Core domain (shipment visibility, carrier integrations)", "weight": "+6", "status": "confirmed"},
    ],
    "company_blocklist": [{"value": "Ironbridge Defense Systems", "reason": "defense contractor", "status": "confirmed"}],
    "connections_policy": "Only 1st-degree connections count; 2nd/3rd-degree and alumni are ignored.",
    "eligibility_baseline": "US citizen, authorized to work in the US, no sponsorship needed.",
    "salary": {"floor_base": 120000, "target_base": "150000-185000", "status": "confirmed"},
    "scoring": {"travel": {"rule": "Each 1% of travel subtracts 0.4 points (10% = -4, 25% = -10)."},
                "tiers": {"A": ">= 80", "B": "65-79", "C": "50-64", "D": "< 50"}},
    "save_meaning": {"rule": "A save is a candidate after a quick title, location and match-line check, not a "
                             "preference. Preferences come from calibration.", "status": "confirmed"},
    "neutral": [{"value": "Program-heavy PM roles", "status": "confirmed"}],
    "open_rules": [{"value": "Marketplace roles where the buyer is a consumer", "status": "case by case"}],
    "process_rules": [{"value": "Several roles at one company: the top 2 lead, the rest wait in reserve",
                       "status": "confirmed"}],
    "qualifiers": [{"value": "Carrier or partner API programs", "status": "confirmed", "effect": "raises fit",
                    "rescreen_regex": r"\bcarrier (API|integration)s?\b"}],
}

CHANGELOG = """
# Spec changelog

Every change to `spec.json`, with date, source and reason. Newest first.

## 2026-11-14 — Round 2 calibration (spec v0.1 → v0.2) [round 2]

| Change | Type | Source |
|---|---|---|
| Managing other PMs as the core of the role → dealbreaker (mentoring is fine) | dealbreaker added | you (Quillstone, round 2 q1) |
| Carrier or partner API programs raise fit | qualifier added | you (Arcadia Fleet, round 2 q2) |

## 2026-11-10 — Round 1 calibration (setup → spec v0.1) [round 1]

| Change | Type | Source |
|---|---|---|
| Remote anywhere; hybrid/on-site within 50 miles of Springfield, IL | dealbreaker added | you (setup) |
| Defense or weapons programs → dealbreaker; Ironbridge Defense Systems blocklisted | dealbreaker added | you (round 1 q2) |
| Travel above 30% → dealbreaker; 10-30% sliding scale | dealbreaker added | you (round 1 q3) |
| Data-platform companies and consumer scope → -8 each | negative added | you (round 1 q4) |
| Core domain +6; 1st-degree connection +8 | scoring rule added | you (round 1 q1) |
"""

PLACES = {"note": "Fictional candidate's city table for the radius check (engine/locations.py).",
          "cities": [{"city": c, "state": s, "lat": la, "lon": lo} for c, s, la, lo in [
              ("springfield", "IL", 39.7817, -89.6501), ("decatur", "IL", 39.8403, -88.9548),
              ("jacksonville", "IL", 39.7339, -90.2290), ("lincoln", "IL", 40.1484, -89.3648),
              ("taylorville", "IL", 39.5489, -89.2945), ("bloomington", "IL", 40.4842, -88.9937),
              ("champaign", "IL", 40.1164, -88.2434), ("peoria", "IL", 40.6936, -89.5890),
              ("chicago", "IL", 41.8781, -87.6298), ("st. louis", "MO", 38.6270, -90.1994)]]}

SEARCHES = {
    "updated": "2026-11-14",
    "defaults": {
        "exclude": ["crypto", "\"security clearance\"", "defense"],
        "posted_within": "week", "experience": ["mid-senior"], "sort": "most recent",
        "pre_run_checklist": ["Reset the filters: Location United States, any date, no workplace or experience filters.",
                              "Write down the result count LinkedIn reports.",
                              "Copy each results page in order into one .txt in 1-inbox/search-results/."],
        "triage_tips": ["A strong match line is a candidate, not a verdict: scan requirements and location first."],
        "triage_flow": ["1. Paste results; ingest_results.py makes cards; triaged.py check skips decided ones.",
                        "3b. Claude records its call on every batch card before the user decides: likely keep / "
                        "lean keep / possible: <missing fact> / lean DQ / weak. Commit to a lean."],
    },
    "searches": [
        {"id": "S1", "name": "Core: shipment visibility and carrier integrations", "cluster": "core",
         "status": "active", "seed_jobs": ["Harborline", "Cobalt Route"],
         "why": "The candidate's core domain; matches both A-tier saves.",
         "titles": ["\"product manager\""], "any_of": ["\"shipment visibility\"", "\"carrier integration\"",
                                                     "\"supply chain\"", "logistics"],
         "where": "remote", "linkedin_action": "Keep; set an alert"},
        {"id": "S2", "name": "Platform: B2B APIs in logistics", "cluster": "platform", "status": "testing",
         "seed_jobs": ["Cobalt Route"], "why": "API and partner programs are a confirmed qualifier.",
         "titles": ["\"product manager\""], "any_of": ["API", "\"developer platform\""],
         "all_of": ["logistics", "freight", "fleet"], "where": "remote", "linkedin_action": "Try once"},
        {"id": "S3", "name": "Local: product roles near Springfield", "cluster": "local", "status": "testing",
         "seed_jobs": ["Brightdock"], "why": "Hybrid roles inside the 50-mile radius.",
         "titles": ["\"product manager\"", "\"product owner\""], "where": "local",
         "linkedin_action": "Try once (the geoId in spec.json is a placeholder in this sample)"},
    ],
    "insights": [{"date": "2026-11-14", "round": 2, "trend": "Fleet and telematics roles surfaced from S1",
                  "evidence": "Arcadia Fleet kept as a strong keep", "proposal": "Add \"fleet\" to S1's any_of",
                  "decision": "open"}],
    "mode": {"mode": "catch-up", "since": "2026-11-10", "builder": False, "goal": 200, "lookback": None,
             "pace": "two sessions a week, about an hour each", "cadence": None, "last_asked": None},
}

# ---- jobs ---------------------------------------------------------------------------------------------------------


def posting(about, duties, required, nice, extra=""):
    lines = [about, "", "What you'll do", *[f"- {d}" for d in duties], "", "What we're looking for",
             *[f"- {r}" for r in required]]
    if nice:
        lines += ["", "Nice to have", *[f"- {n}" for n in nice]]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)


def job(jid, company, title, location, workplace, posted, applicants, text, salary=None, connections=None,
        leads=None, printed="11/09/26"):
    return {
        "job_id": jid, "url": f"https://example.com/jobs/{jid}", "list": "saved",
        "source_files": [f"1-inbox/job-pdfs/{title} _ {company} (sample).pdf"],
        "title": title, "company": company, "location": location, "posted": posted, "applicants": applicants,
        "workplace": workplace, "employment_type": "Full-time", "network_teaser": [], "posting_text": text,
        "company_text": f"{company} (fictional company for the sample data).", "company_meta": None,
        "salary_mentions": [salary] if salary else [], "truncated": False, "leads": leads or [],
        "main_file": f"1-inbox/job-pdfs/{title} _ {company} (sample).pdf", "printed": printed,
        "connections_1st": connections or [], "extracted_at": "2026-11-10T09:00:00",
    }


def lead(title, company, location, salary="", note=None):
    d = {"title": title, "company": company, "location": location, "salary": salary}
    if note:
        d["connections_note"] = note
    return d


ROUND1 = [
    job("9100000001", "Harborline Logistics", "Senior Product Manager, Shipment Visibility",
        "United States (Remote)", "Remote", "Posted 4 days ago", "48 applicants",
        posting("Harborline gives 2,000 shippers one view of every load in motion.",
                ["Own the roadmap for real-time tracking, ETA prediction and exception alerts",
                 "Partner with data science on ETA accuracy", "Work with carriers and shippers to define integrations"],
                ["6+ years of B2B product management", "Experience with shipment visibility or transportation software",
                 "Comfort with APIs, webhooks and event data", "Clear written communication with executives"],
                ["Experience with machine-learning products", "Usage-based pricing experience"],
                "Travel: up to 10%."),
        salary="$155,000 - $185,000",
        connections=[{"name": "Sam Ortiz (fictional)", "headline": "Director of Engineering at Harborline Logistics"}],
        leads=[lead("Product Manager, Carrier Network", "Harborline Logistics", "United States (Remote)", "",
                    "1 connection works here"),
               lead("Senior Product Manager, Tracking API", "Ferrous Freight Tech", "United States (Remote)")]),
    job("9100000002", "Cobalt Route", "Staff Product Manager, Carrier Integrations API",
        "Denver, CO (Remote)", "Remote", "Posted 1 week ago", "Over 100 applicants",
        posting("Cobalt Route connects shippers to 5,000 carriers through one API.",
                ["Own the public carrier API, SDKs and certification program",
                 "Set API versioning and deprecation policy", "Grow carrier self-serve onboarding"],
                ["8+ years of product management, 3+ on API or platform products",
                 "Hands-on understanding of REST APIs and webhooks", "Experience running partner or developer programs"],
                ["Logistics or freight industry background", "Pricing and packaging for API products"]),
        salary="$170,000 - $200,000",
        leads=[lead("Senior Product Manager, Tracking API", "Ferrous Freight Tech", "United States (Remote)"),
               lead("Product Manager, Freight Marketplace", "Lattice Haul", "Chicago, IL (Hybrid)")]),
    job("9100000003", "Brightdock", "Principal Product Manager, Warehouse Automation",
        "Decatur, IL (Hybrid)", "Hybrid", "Posted 2 weeks ago", "31 applicants",
        posting("Brightdock builds software that runs robotic picking cells in mid-size warehouses.",
                ["Define the roadmap for the warehouse execution system", "Work with robotics and floor operations teams",
                 "Lead launches across 40 customer sites"],
                ["7+ years of product management", "Warehouse management or execution system experience",
                 "Experience shipping integrations with WMS and ERP systems"],
                ["Robotics or automation hardware exposure"],
                "Hybrid: 2 days a week in our Decatur office. Travel: up to 15% to customer sites."),
        salary="$150,000 - $175,000"),
    job("9100000004", "Meridian Parcel", "Senior Product Manager, Returns",
        "Chicago, IL (Hybrid)", "Hybrid", "Posted 3 days ago", "Over 100 applicants",
        posting("Meridian Parcel handles returns for 600 retailers.",
                ["Own the returns portal and carrier label flows"],
                ["5+ years of product management", "Returns or reverse-logistics experience"], [],
                "Hybrid: 3 days a week in our Chicago office."),
        salary="$140,000 - $165,000"),
    job("9100000005", "Tessellate Systems", "Product Manager, Logistics Data Platform",
        "United States (Remote)", "Remote", "Posted 5 days ago", "62 applicants",
        posting("Tessellate sells a data platform for supply-chain analytics teams.",
                ["Own ingestion connectors and the semantic layer", "Work with data engineers at customer companies"],
                ["5+ years of product management on data platform or data warehouse products",
                 "Hands-on SQL and dbt experience"],
                ["Supply-chain domain knowledge"])),
    job("9100000006", "Lumen Cart", "Senior Product Manager, Checkout and Delivery Options",
        "United States (Remote)", "Remote", "Posted 1 week ago", "Over 100 applicants",
        posting("Lumen Cart's mobile app helps shoppers pick delivery windows at checkout.",
                ["Own delivery-option selection in the consumer app", "Run A/B tests on conversion"],
                ["5+ years of product management for consumer app or e-commerce products",
                 "Strong experimentation and growth-metrics track record"],
                ["Logistics or last-mile experience"]),
        salary="$160,000 - $190,000"),
    job("9100000007", "Ironbridge Defense Systems", "Product Manager, Logistics Software",
        "United States (Remote)", "Remote", "Posted 6 days ago", "22 applicants",
        posting("Ironbridge builds logistics software for defense programs.",
                ["Own supply tracking for munitions depots"], ["5+ years of product management", "Active security clearance"],
                [])),
    job("9100000008", "Pinecrest Health Supply", "Senior Product Manager, Inventory Planning",
        "United States (Remote)", "Remote", "Posted 4 days ago", "37 applicants",
        posting("Pinecrest supplies 900 clinics with medical consumables.",
                ["Own demand forecasting and replenishment planning", "Work with clinic operations and suppliers"],
                ["6+ years of product management", "Inventory planning or replenishment software experience",
                 "Comfort working with data science on forecasting models"],
                ["Healthcare supply chain experience"],
                "This role requires a background check and drug screening."),
        salary="$145,000 - $170,000"),
]

ROUND2 = [
    job("9100000009", "Arcadia Fleet", "Senior Product Manager, Fleet Platform APIs",
        "United States (Remote)", "Remote", "Posted 2 days ago", "19 applicants",
        posting("Arcadia Fleet's platform connects 80,000 trucks to the shippers that book them.",
                ["Own the fleet platform's partner APIs and webhooks", "Launch a carrier certification program",
                 "Work with telematics partners on data quality"],
                ["6+ years of product management on B2B platform or API products",
                 "Experience with carrier or partner integration programs", "Data-informed decision making"],
                ["Telematics or IoT device experience", "Usage-based pricing"]),
        salary="$165,000 - $195,000", printed="11/13/26"),
    job("9100000010", "Quillstone Software", "Group Product Manager, Supply Chain Planning",
        "United States (Remote)", "Remote", "Posted 1 week ago", "54 applicants",
        posting("Quillstone builds planning software for consumer-goods supply chains.",
                ["Lead a team of four product managers", "Own the planning suite's strategy"],
                ["10+ years of product management, 3+ managing product managers", "Supply-chain planning experience"],
                []),
        salary="$190,000 - $220,000", printed="11/13/26"),
]

EXT_ID = "ext-northwind-freight-sr-pm"
EXT_DESCRIPTION = """
Senior Product Manager, Freight Marketplace (Northwind Freight, through Summit Staffing)

About the role
Northwind Freight is building a marketplace that matches regional shippers with small carriers. You'll own the
marketplace from load posting to payment, working with operations, sales and two engineering teams.

What you'll do
- Own the load-matching and booking experience for shippers and carriers
- Define carrier onboarding and verification
- Set marketplace pricing and take-rate experiments with finance

What we're looking for
- 6+ years of B2B product management
- Logistics, freight or transportation software experience
- Experience with two-sided marketplaces or partner networks
- Comfort with pricing decisions backed by data

Nice to have
- Carrier onboarding or compliance programs
- Experience with payments or factoring

Hybrid: 2 days a week in Springfield, IL.
"""

REVIEWS1 = {"round": 1, "date": "2026-11-10",
            "method": "Each posting read in full against engine/prompts/review-rubric.md (sample: written by hand).",
            "jobs": {
    "9100000001": {"fit": 80, "pay": "$155K-$185K", "summary": "Shipment-visibility platform: the candidate's core "
                   "domain, including ETA prediction with data science.",
                   "positives": ["Core domain: tracking, ETA and exception alerts", "APIs and webhooks match the "
                                 "carrier-integration program", "1st-degree connection (fictional)"],
                   "caveats": ["Travel up to 10%"], "gaps": ["Machine-learning product depth (nice to have; partial)"],
                   "adjustments": [{"reason": "core domain", "points": 6}, {"reason": "travel 10%", "points": -4}],
                   "network_bonus": 8, "dealbreakers": [], "eligibility": [], "tier": "A", "search": "S1"},
    "9100000002": {"fit": 82, "pay": "$170K-$200K", "summary": "Public carrier API and certification program at a "
                   "carrier network; a near-exact match for the carrier-integration program.",
                   "positives": ["Carrier API, SDKs and certification: done before at scale",
                                 "API pricing and packaging (nice to have) is a strength"],
                   "caveats": ["Staff level: ask about scope and how the role is leveled"], "gaps": [],
                   "adjustments": [{"reason": "core domain", "points": 6}], "network_bonus": 0, "dealbreakers": [],
                   "eligibility": [], "tier": "A", "search": "S1"},
    "9100000003": {"fit": 74, "pay": "$150K-$175K", "summary": "Warehouse execution system for robotic picking; "
                   "hybrid in Decatur, inside the radius.",
                   "positives": ["WMS integrations match the Parcelwise years", "Local hybrid, 2 days a week"],
                   "caveats": ["Travel up to 15% to customer sites", "Robotics hardware is new territory"],
                   "gaps": ["Robotics or automation hardware (nice to have; missing)"],
                   "adjustments": [{"reason": "travel 15%", "points": -6}], "network_bonus": 0, "dealbreakers": [],
                   "eligibility": [], "tier": "B", "search": "direct"},
    "9100000004": {"fit": 70, "pay": "$140K-$165K", "summary": "Returns product; hybrid 3 days a week in Chicago.",
                   "positives": ["Returns workflow experience from Parcelwise"], "caveats": [],
                   "gaps": [], "adjustments": [], "network_bonus": 0,
                   "dealbreakers": ["Hybrid in Chicago, about 185 miles from Springfield"], "eligibility": [],
                   "tier": "X", "search": "direct"},
    "9100000005": {"fit": 60, "pay": "not listed", "summary": "Data platform for supply-chain analytics teams.",
                   "positives": ["Supply-chain domain (nice to have)"],
                   "caveats": ["Sells the data stack itself", "Hands-on dbt required"],
                   "gaps": ["dbt (required; missing)", "Data warehouse product experience (required; missing)"],
                   "adjustments": [{"reason": "data-platform company", "points": -8}], "network_bonus": 0,
                   "dealbreakers": [], "eligibility": [], "tier": "C", "search": "S1"},
    "9100000006": {"fit": 62, "pay": "$160K-$190K", "summary": "Delivery options inside a consumer shopping app.",
                   "positives": ["Last-mile logistics (nice to have)"],
                   "caveats": ["Consumer app scope", "Growth-metrics track record required"],
                   "gaps": ["Consumer experimentation at scale (required; partial)"],
                   "adjustments": [{"reason": "consumer scope", "points": -8}], "network_bonus": 0,
                   "dealbreakers": [], "eligibility": [], "tier": "C", "search": "S1"},
    "9100000007": {"fit": None, "pay": "not listed", "summary": "Supply tracking for defense programs.",
                   "positives": [], "caveats": [], "gaps": [], "adjustments": [], "network_bonus": 0,
                   "dealbreakers": ["Defense programs (and a required security clearance)"], "eligibility": [
                       {"requirement": "active security clearance", "quote": "Active security clearance",
                        "applies_to": "person"}], "tier": "X", "search": "S1"},
    "9100000008": {"fit": 70, "pay": "$145K-$170K", "summary": "Demand forecasting and replenishment for a medical "
                   "supply distributor.",
                   "positives": ["Forecasting with data science matches the ETA-model work"],
                   "caveats": ["Healthcare is a new domain"],
                   "gaps": ["Inventory planning software (required; partial)"], "adjustments": [],
                   "network_bonus": 0, "dealbreakers": [], "eligibility": [
                       {"requirement": "background check and drug screening",
                        "quote": "This role requires a background check and drug screening.", "applies_to": "person"}],
                   "tier": "B", "search": "S1"},
}}

REVIEWS2 = {"round": 2, "date": "2026-11-14",
            "method": "New jobs from the S1 triage run, read in full (sample: written by hand).", "jobs": {
    "9100000009": {"fit": 80, "pay": "$165K-$195K", "summary": "Partner APIs and a carrier certification program on "
                   "a fleet platform; a strong keep in triage, confirmed in calibration.",
                   "positives": ["Carrier certification program: done before for 1,400 carriers",
                                 "Usage-based pricing (nice to have) is a strength"],
                   "caveats": ["Telematics devices are new territory"],
                   "gaps": ["Telematics or IoT devices (nice to have; missing)"],
                   "adjustments": [{"reason": "core domain", "points": 6}], "network_bonus": 0, "dealbreakers": [],
                   "eligibility": [], "tier": "A", "search": "S1", "strength": "strong keep"},
    "9100000010": {"fit": 66, "pay": "$190K-$220K", "summary": "Group PM leading four product managers in planning "
                   "software.", "positives": ["Supply-chain planning domain"],
                   "caveats": ["Managing PMs is the core of the role"], "gaps": ["People management (required; missing)"],
                   "adjustments": [], "network_bonus": 0,
                   "dealbreakers": ["Managing other product managers as the core of the role (rule added round 2)"],
                   "eligibility": [], "tier": "X", "search": "S1"},
    EXT_ID: {"fit": 76, "pay": "not stated (ask the recruiter)", "summary": "Freight marketplace for regional "
             "shippers and small carriers; hybrid in Springfield; through a staffing firm.",
             "positives": ["Carrier onboarding and partner networks", "Pricing backed by data", "Local hybrid"],
             "caveats": ["Through a staffing firm: contract or conversion not stated"],
             "gaps": ["Two-sided marketplace (required; partial)", "Payments or factoring (nice to have; missing)"],
             "adjustments": [], "network_bonus": 0, "dealbreakers": [], "eligibility": [], "tier": "B",
             "search": "external: recruiter"},
}}

CALIBRATION1 = {"round": 1, "date": "2026-11-10", "questions": [
    {"id": "q1", "topic": "Core domain", "question": "Should shipment visibility and carrier integrations score above "
     "other logistics roles?", "answer": "Yes, +6.", "answered": "2026-11-10"},
    {"id": "q2", "topic": "Defense", "question": "Ironbridge builds logistics software for defense programs. Rule it out?",
     "answer": "Yes: no defense or weapons work, ever.", "answered": "2026-11-10"},
    {"id": "q3", "topic": "Travel", "question": "Brightdock asks for up to 15% travel. Where's your limit?",
     "answer": "Up to 30% is fine if it's worth it; above that, no.", "answered": "2026-11-10"},
    {"id": "q4", "topic": "Company type", "question": "Tessellate sells a data platform; Lumen Cart is a consumer app. "
     "Penalty or dealbreaker?", "answer": "Penalty for both, not a dealbreaker.", "answered": "2026-11-10"},
]}

CALIBRATION2 = {"round": 2, "date": "2026-11-14", "questions": [
    {"id": "q1", "topic": "People management", "question": "Quillstone's Group PM role manages four PMs. Is that a "
     "dealbreaker?", "answer": "Yes, when managing PMs is the core of the job. Mentoring is fine.",
     "answered": "2026-11-14"},
    {"id": "q2", "topic": "Strong keep: Arcadia Fleet", "question": "Telematics devices are nice to have. Partner APIs "
     "and certification: have / partial / no?", "answer": "Have: same program as Tidewater's carrier certification.",
     "answered": "2026-11-14"},
    {"id": "s1", "type": "stretch review", "topic": "Stretch review: Northwind Freight, Senior PM Freight Marketplace",
     "question": "Stretches: two-sided marketplace (required; partial), payments (nice to have; missing). Build, build "
     "without concessions, or pass?", "answer": "Build; name the marketplace gap, skip payments.",
     "answered": "2026-11-14"},
]}

SKILLS_GAP = {"method": "Requirements from every reviewed job, matched to the profile and weighted by how often and "
              "how strongly top jobs ask (sample).", "items": [
    {"skill": "Carrier / partner API programs", "category": "have", "weight": 4, "dq_demand": 0,
     "jobs": ["Cobalt Route", "Arcadia Fleet", "Harborline Logistics"], "action": "Lead with it."},
    {"skill": "Machine-learning products", "category": "partial", "weight": 2, "dq_demand": 0,
     "jobs": ["Harborline Logistics", "Pinecrest Health Supply"],
     "action": "Describe the ETA model as a product decision, not a data-science project."},
    {"skill": "Usage-based pricing", "category": "have_not_on_resume", "weight": 2, "dq_demand": 0,
     "jobs": ["Harborline Logistics", "Arcadia Fleet"], "action": "Add the 22% new-revenue result to the resume."},
    {"skill": "dbt", "category": "missing", "weight": 1, "dq_demand": 1, "jobs": ["Tessellate Systems"],
     "dq_jobs": ["Kestrel Analytics"], "action": "Low priority: only data-platform roles ask for it."},
    {"skill": "Telematics / IoT devices", "category": "missing", "weight": 1, "dq_demand": 0,
     "jobs": ["Arcadia Fleet"], "action": "A short course would cover the vocabulary."},
], "tracks": [{"track": "Fleet and telematics platforms", "target": "fleet-platform PM roles",
               "skills": ["Telematics / IoT devices", "Carrier / partner API programs"],
               "steps": ["Read two telematics data-standard overviews", "Map the carrier API work to device data flows"]}]}

# Round 2's triage run: what was on the search results, the agent's call, and the decision.
RUN_LISTINGS = [
    ("Senior Product Manager, Fleet Platform APIs", "Arcadia Fleet", "United States (Remote)", "likely keep",
     "fleet platform partner APIs", "keep", "", "well", "9100000009"),
    ("Group Product Manager, Supply Chain Planning", "Quillstone Software", "United States (Remote)", "lean DQ",
     "Group PM title: likely manages PMs", "keep", "manages PMs? check in calibration", "well", "9100000010"),
    ("Senior Product Manager, Freight Payments", "Lattice Haul", "United States (Remote)", "possible: payments depth",
     "freight payments", "dq", "LinkedIn match below strong (not investigated)", "some", None),
    ("Product Manager, Analytics", "Kestrel Analytics", "United States (Remote)", "weak", "analytics company",
     "dq", "requires hands-on dbt", "missing", None),
    ("Senior Product Manager, Yard Management", "Copperline Yards", "Peoria, IL (Hybrid)", "weak",
     "hybrid outside the radius", "dq", "rule: outside 50 miles", "", None),
    ("Product Manager, Route Optimization", "Waymarrow Labs", "United States (Remote)", "lean keep",
     "routing is adjacent to visibility", "dq", "LinkedIn match below strong (not investigated)", "some", None),
    ("Senior PM, Shopper Experience", "Thimbleroot Goods", "United States (Remote)", "weak", "consumer app", "dq",
     "consumer scope", "some", None),
    ("Staff Product Manager, EDI Integrations", "Relay Ledger", "United States (Remote)", "likely keep",
     "carrier EDI integrations", "keep", "saved; review next round", "well", None),
]

# Round 1's first search run: the eight saves plus the cards ruled out in triage (no agent calls yet).
RUN1_DQS = [
    ("Product Manager, Payments Risk", "Fernhill Pay", "fintech, not logistics"),
    ("Senior Product Manager, Ad Platform", "Velvetine Media", "ad tech"),
    ("Product Owner, Claims", "Granary Mutual", "insurance claims"),
    ("Senior Product Manager, Growth", "Pebblequay Kids", "consumer growth"),
    ("Director of Product, Logistics", "Ostrava Carriers", "director level"),
    ("Product Manager, Clinical Trials", "Verdance Bio", "regulated healthcare"),
    ("Senior Product Manager, Port Operations", "Tidal Berth", "on-site, out of radius"),
    ("Product Manager, Smart Home", "Nestfield", "consumer devices"),
    ("Senior Product Manager, Freight Audit", "Ledgerline", "LinkedIn match below strong (not investigated)"),
    ("Product Manager, Cold Chain Sensors", "Frostline IoT", "LinkedIn match below strong (not investigated)"),
    ("Senior Product Manager, Retail Media", "Aislecraft Media", "ad tech"),
    ("Product Manager, Dispatch Mobile App", "Routeloom", "LinkedIn match below strong (not investigated)"),
]


def find_link(title, company):
    from urllib.parse import quote
    return "https://example.com/jobs/search?q=" + quote(f'"{title}" "{company}"')


TRACKER_PASTE = """
Job tracker

Saved · 6

Senior Product Manager, Shipment Visibility
Harborline Logistics · United States (Remote)
Posted 1w ago

Staff Product Manager, Carrier Integrations API
Cobalt Route · Denver, CO (Remote)
Reposted 1w ago

Principal Product Manager, Warehouse Automation
Brightdock · Decatur, IL (Hybrid)
Posted 2w ago

Product Manager, Logistics Data Platform
Tessellate Systems · United States (Remote)
Posted 1w ago

Senior Product Manager, Inventory Planning
Pinecrest Health Supply · United States (Remote)
Posted 1w ago

Senior Product Manager, Fleet Platform APIs
Arcadia Fleet · United States (Remote)
Posted 5d ago
"""

KIT_LOG = f"""
# Application log: Northwind Freight, Senior Product Manager, Freight Marketplace (fictional sample)

| Field | Value |
|---|---|
| Job | Senior PM, Freight Marketplace ([description](job-description.txt)); external job. Project record: `6-system/jobs/{EXT_ID}.json` |
| Score | 76 (B) |
| Route | Summit Staffing recruiter (fictional) → Northwind Freight panel |
| Kit prepared | 2026-11-14 |
| Stretch review | 2026-11-14 (calibration round 2, s1): build; name the marketplace gap, skip payments |
| Status | Interviewing |

## Timeline
| Date | What | Notes |
|---|---|---|
| 2026-11-14 | Kit prepared after the stretch review | |
| 2026-11-15 | Applied through the recruiter | |
| 2026-11-17 | Round 1: recruiter screen | Went well; panel next |
"""

KIT_FIT_MAP = """
# Fit map: Northwind Freight, Senior PM, Freight Marketplace (fictional sample)

Every claim comes from `4-profile/career-master.md`. **Have** = clear evidence; **Partial** = adjacent or smaller;
**Gap** = not in the history.

## Required
| # | Requirement | Rating | Your evidence | Where they can see it | How to say it |
|---|---|---|---|---|---|
| R1 | 6+ years of B2B product management | **Have** | 11 years in supply-chain software, 7 as a PM | Resume | "Seven years as a PM on B2B logistics products." |
| R2 | Logistics, freight or transportation software | **Have** | Shipment visibility for 310 shippers; carrier integrations for 1,400 carriers | Resume | Lead with the carrier network. |
| R3 | Two-sided marketplaces or partner networks | **Partial** | Carrier certification program (a partner network), not a marketplace | Resume (program), not the word "marketplace" | Name the gap; bridge with the carrier network's supply side. |
| R4 | Pricing decisions backed by data | **Have** | Usage-based API pricing: 22% of new revenue in year one | Not on the resume yet | Say it in the room. |

## Nice to have
| # | Requirement | Rating | Your evidence | Where they can see it | How to handle it |
|---|---|---|---|---|---|
| N1 | Carrier onboarding or compliance programs | **Have** | Onboarding cut from 9 weeks to 12 days | Resume | A two-minute story. |
| N2 | Payments or factoring | **Gap** | None | - | Skip unless asked; then say it plainly and point to pricing work. |

## Summary
- Required: 3 Have, 1 Partial. Nice to have: 1 Have, 1 Gap.
"""

KIT_PREP = """
# Interview prep: Northwind Freight, Senior PM, Freight Marketplace (fictional sample)

## Likely interview questions

**From the hiring manager**
| # | Question | Use |
|---|---|---|
| 1 | Tell us about a marketplace or network you grew. | Fit map R3: the carrier network as a supply side |
| 2 | How would you set the take rate for a new lane? | R4: usage-based pricing, data first |
| 3 | How do you onboard and verify small carriers? | N1: 9 weeks to 12 days |
| 4 | What would you do in your first 30 days? | Map shippers, carriers and ops pain points |
| 5 | How do you decide what not to build? | Parcelwise portfolio retirement |

**From operations**
| # | Question | Use |
|---|---|---|
| 6 | How do you work with dispatchers and ops teams? | Ride-alongs and floor visits |
| 7 | Tell us about an integration that went wrong. | Carrier certification suite: why it exists |
| 8 | How would you measure marketplace health? | Fill rate, time to book, repeat carriers |

**Behavioral and fit**
| # | Question | Use |
|---|---|---|
| 9 | Why Northwind, and why a marketplace? | The carrier network was always half a marketplace |
| 10 | You haven't run payments. How would you get up to speed? | N2: name it, then the pricing work |
| 11 | How do you use AI tools in your own work? | Daily prototypes and analysis |
| 12 | What questions do you have for us? | Contract or conversion; who owns pricing |
"""

DEBRIEF1 = {"how": "Recruiter screen: friendly, about the role's scope and the hybrid schedule.",
            "asked": ["Walk me through your background", "Why a marketplace?", "Are you open to contract-to-hire?"],
            "landed": ["The carrier onboarding story (9 weeks to 12 days)"],
            "missed": ["Was vague on salary expectations"],
            "signals": "Panel with the hiring manager and operations lead next week",
            "next": "Panel interview", "lessons": ["Have a salary range ready before the first call"],
            "thank_you_to": ["the recruiter"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(REPO / "sample-data"))
    out = Path(ap.parse_args().out).resolve()
    if out.exists():
        # Only ever replace a folder this script made and nobody has changed since: never a filesystem root, the
        # repo itself, or a folder holding anyone's work (checked file by file against the generation manifest).
        if out == Path(out.anchor) or out in (REPO, Path.home()):
            sys.exit(f"Refusing to replace {out}. Choose a new or empty --out folder.")
        found = changes(out) if any(out.iterdir()) else []
        if found:
            sys.exit(f"Refusing to replace {out}: it isn't an unchanged sample-data folder made by this script ("
                     + "; ".join(found[:5]) + ("; ..." if len(found) > 5 else "") + "). Choose a new or empty "
                     "--out folder.")
        shutil.rmtree(out)
    D = out
    data = ["--data", D]

    write(D / "README.md", """
# Sample data: a fictional candidate

Everything in this folder is invented: Jordan Avery, every employer, posting, connection, recruiter and interview.
Company names are made up and any resemblance to real ones is accidental; job links point to example.com.
It was generated by `scripts/make_sample_data.py`, which writes the inputs a user and Claude's judgment steps would
have produced over two rounds, then runs the engine for everything mechanical.

To try it without changing these files, copy the folder first:

    cp -r sample-data demo-data
    python -B engine/build_report.py --data demo-data --round 2

(`demo-data/` is git-ignored.) Job PDFs and the resume aren't included; the job records stand in for extracted PDFs.
""")
    for sub in ("1-inbox/job-pdfs", "1-inbox/search-results", "1-inbox/role-explorer", "2-reports/archive",
                "6-system/search-runs"):
        (D / sub).mkdir(parents=True, exist_ok=True)
    write(D / "4-profile/career-master.md", CAREER_MASTER)
    write(D / "4-profile/voice-guide.md", VOICE_GUIDE)
    write(D / "6-system/profile.json", PROFILE)
    write(D / "5-criteria/spec.json", SPEC)
    write(D / "5-criteria/changelog.md", CHANGELOG)
    write(D / "5-criteria/places.json", PLACES)
    write(D / "5-criteria/searches.json", SEARCHES)
    write(D / "6-system/removed.json", [{"job_id": "9100000099", "removed": "2026-11-10",
                                         "reason": "travel 50% (dealbreaker: above 30%)",
                                         "company": "Velocity Rideshare Freight", "title": "Product Manager, Field Ops"}])
    write(D / "6-system/skills-gap.json", SKILLS_GAP)
    write(D / "private-terms.example.txt", "# Terms the privacy scan must never find in shareable files (sample)\n"
                                   "Jordan Avery\nTidewater Logistics Software\nSam Ortiz\n")

    # Round 1: eight saved jobs, reviewed and calibrated.
    for j in ROUND1:
        write(D / f"6-system/jobs/{j['job_id']}.json", j)
    write(D / "6-system/reviews/round-01.json", REVIEWS1)
    write(D / "6-system/calibration/round-01.json", CALIBRATION1)
    run1 = [{"id": f"S1-{n:03d}", "title": j["title"], "company": j["company"], "location": j["location"],
             "workplace": j["workplace"], "section": "exact", "status": "candidate", "batch": 1,
             "find": find_link(j["title"], j["company"]), "decision": "keep", "decided": "2026-11-09",
             "linkedin_match": "well", "job_id": j["job_id"]} for n, j in enumerate(ROUND1, 1)]
    run1 += [{"id": f"S1-{n:03d}", "title": t, "company": c, "location": "United States (Remote)",
              "workplace": "Remote", "section": "exact", "status": "candidate", "batch": 1 + n // 12,
              "find": find_link(t, c), "decision": "dq", "decided": "2026-11-09", "reason": r,
              "linkedin_match": "some" if r.startswith("LinkedIn match") else ""}
             for n, (t, c, r) in enumerate(RUN1_DQS, len(ROUND1) + 1)]
    write(D / "6-system/search-runs/s1-run-2026-11-09.json",
          {"round": 1, "mode": "catch-up", "search": "S1", "date": "2026-11-09",
           "source": "1-inbox/search-results/s1-2026-11-09.txt (sample; not included)", "result_count": 64,
           "unrecorded_cards": 24, "listings": run1})
    run(ENGINE / "build_report.py", *data, "--round", 1)
    run(ENGINE / "metrics.py", "--round", 1, *data)

    # Round 2: a triage run, two saves from it, and an external job from a recruiter.
    listings = []
    for n, (title, company, loc, likely, why, dec, reason, match, jid) in enumerate(RUN_LISTINGS, 1):
        x = {"id": f"S1-{n:03d}", "title": title, "company": company, "location": loc,
             "workplace": loc.split("(")[-1].rstrip(")"), "section": "exact", "status": "candidate", "batch": 1,
             "find": find_link(title, company), "likely": likely, "why": why, "decision": dec, "decided": "2026-11-13", "reason": reason,
             "linkedin_match": match}
        if jid:
            x["job_id"] = jid
        if jid == "9100000009":
            x["strength"] = "strong keep"
        listings.append(x)
    write(D / "6-system/search-runs/s1-run-2026-11-13.json",
          {"round": 2, "mode": "catch-up", "search": "S1", "date": "2026-11-13",
           "source": "1-inbox/search-results/s1-2026-11-13.txt (sample; not included)", "result_count": 112,
           "unrecorded_cards": 38, "listings": listings})
    for j in ROUND2:
        write(D / f"6-system/jobs/{j['job_id']}.json", j)
    kit = D / "3-applications/northwind-freight-sr-pm-marketplace"
    write(kit / "job-description.txt", EXT_DESCRIPTION)
    run(ENGINE / "ingest_external.py", kit / "job-description.txt", "--id", EXT_ID, "--company",
        "Northwind Freight (through Summit Staffing)", "--title", "Senior Product Manager, Freight Marketplace",
        "--location", "Springfield, IL", "--workplace", "Hybrid", "--source", "Summit Staffing recruiter (fictional)",
        *data)
    write(D / "6-system/reviews/round-02.json", REVIEWS2)
    write(D / "6-system/calibration/round-02.json", CALIBRATION2)
    write(kit / "log.md", KIT_LOG)
    write(kit / "fit-map.md", KIT_FIT_MAP)
    write(kit / "interview-prep.md", KIT_PREP)
    run(ENGINE / "triaged.py", "seed", *data)

    # Application steps, interviews and open checks, recorded the way Claude records what the user reports.
    for args in (("9100000001", "outreach", "--date", "2026-11-11", "--note", "Messaged Sam Ortiz (fictional)"),
                 ("9100000001", "applied", "--date", "2026-11-12"),
                 (EXT_ID, "applied", "--date", "2026-11-15", "--note", "Through the recruiter"),
                 ("9100000005", "passed", "--date", "2026-11-14", "--note", "dbt is required; not worth the stretch")):
        run(ENGINE / "pipeline.py", "record", *args, *data)
    run(ENGINE / "interviews.py", *data, "schedule", EXT_ID, "--round", 1, "--date", "2026-11-17",
        "--with", "Summit Staffing recruiter", "--format", "phone")
    debrief = D / "debrief.tmp.json"
    write(debrief, DEBRIEF1)
    run(ENGINE / "interviews.py", *data, "debrief", EXT_ID, "--round", 1, "--file", debrief)
    debrief.unlink()
    run(ENGINE / "interviews.py", *data, "schedule", EXT_ID, "--round", 2, "--date", "2026-11-24",
        "--with", "hiring manager and operations lead", "--format", "video")
    write(D / "1-inbox/tracked-jobs/tracked-2026-11-14.txt", TRACKER_PASTE)
    run(ENGINE / "staleness.py", *data, "tracker", D / "1-inbox/tracked-jobs/tracked-2026-11-14.txt")

    # Close round 2: report, metrics, report again (it embeds the funnel), search links, queue.
    run(ENGINE / "build_report.py", *data, "--round", 2)
    run(ENGINE / "metrics.py", "--round", 2, *data)
    for f in (D / "2-reports").glob("2026-11-10-round-01*"):
        f.rename(D / "2-reports/archive" / f.name)
    run(ENGINE / "build_report.py", *data, "--round", 2)
    run(ENGINE / "searches.py", *data)
    run(ENGINE / "pipeline.py", "queue", *data)
    write_manifest(out)
    print(f"Sample data written to {out}")


if __name__ == "__main__":
    main()
