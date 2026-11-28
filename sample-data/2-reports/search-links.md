# LinkedIn search suggestions (2026-11-28)

Built from your top-ranked saved jobs and your confirmed spec. Each link opens a LinkedIn job search with filters already set: remote US (or within 50 miles of Springfield, Illinois for local), posted in the past week, newest first, excluding crypto, security clearance, defense.

## Your LinkedIn searches: what to do with each

| Search | Name | Status | Action on LinkedIn |
|---|---|---|---|
| S1 | Core: shipment visibility and carrier integrations | active | Keep; set an alert |
| S2 | Platform: B2B APIs in logistics | testing | Try once |
| S3 | Local: product roles near Springfield | testing | Try once (the geoId in spec.json is a placeholder in this sample) |

**To make one a job alert:** open the link, check the results look right, then switch on **Set alert** at the top of the results. Alert emails become the input for Phase 2.

**Before every run (check this first):**

1. Reset the filters: Location United States, any date, no workplace or experience filters.
2. Write down the result count LinkedIn reports.
3. Copy each results page in order into one .txt in 1-inbox/search-results/.

**While triaging (tips):**

- A strong match line is a candidate, not a verdict: scan requirements and location first.

**Why sales/marketing aren't excluded:** LinkedIn matches keywords against the whole description, and nearly every PM posting mentions sales and marketing teams. Role type is filtered by the scoring step instead.

**What happens next:** jobs you find through these searches go into `1-inbox/job-pdfs/` like any other. Each search keeps a yield record (jobs found, scored high, saved) so weak searches can be tuned or retired.

## Core (60% weight)

### S1 - Core: shipment visibility and carrier integrations

The candidate's core domain; matches both A-tier saves.  
*Built from:* Harborline, Cobalt Route

*Status:* active · *Window:* Past week

**[Open search on LinkedIn](https://www.linkedin.com/jobs/search/?keywords=%22product+manager%22+AND+%28%22shipment+visibility%22+OR+%22carrier+integration%22+OR+%22supply+chain%22+OR+logistics%29+NOT+%28crypto+OR+%22security+clearance%22+OR+defense%29&f_TPR=r604800&sortBy=DD&f_E=4&location=United+States&geoId=103644278&f_WT=2)**

Keywords (to paste or edit by hand):

```
"product manager" AND ("shipment visibility" OR "carrier integration" OR "supply chain" OR logistics) NOT (crypto OR "security clearance" OR defense)
```

## Platform

### S2 - Platform: B2B APIs in logistics

API and partner programs are a confirmed qualifier.  
*Built from:* Cobalt Route

*Status:* testing · *Window:* Past week

**[Open search on LinkedIn](https://www.linkedin.com/jobs/search/?keywords=%22product+manager%22+AND+%28API+OR+%22developer+platform%22%29+AND+%28logistics+OR+freight+OR+fleet%29+NOT+%28crypto+OR+%22security+clearance%22+OR+defense%29&f_TPR=r604800&sortBy=DD&f_E=4&location=United+States&geoId=103644278&f_WT=2)**

Keywords (to paste or edit by hand):

```
"product manager" AND (API OR "developer platform") AND (logistics OR freight OR fleet) NOT (crypto OR "security clearance" OR defense)
```

## Local

### S3 - Local: product roles near Springfield

Hybrid roles inside the 50-mile radius.  
*Built from:* Brightdock

*Status:* testing · *Window:* Past week

**[Open search on LinkedIn](https://www.linkedin.com/jobs/search/?keywords=%28%22product+manager%22+OR+%22product+owner%22%29+NOT+%28crypto+OR+%22security+clearance%22+OR+defense%29&f_TPR=r604800&sortBy=DD&location=Springfield%2C+Illinois&geoId=000000000&distance=50&f_WT=1%2C3)**

Keywords (to paste or edit by hand):

```
("product manager" OR "product owner") NOT (crypto OR "security clearance" OR defense)
```
