# Apply queue (2026-11-18)

Built by `engine/pipeline.py queue` from the ranked jobs, the kit folders and each job's recorded steps. Rebuilt whenever you report a step (messaged, applied, heard back, interview) and at the end of every round.

## Due

Owed now or in the next 3 days (`engine/interviews.py due`): debriefs, thank-you notes and follow-ups.

- **today** · Northwind Freight (through Summit Staffing): Send the round 1 thank-you to the recruiter (draft in the kit folder)
- **in 1 day** · Harborline Logistics: no response since applying: send a short follow-up or ask your connection for a nudge (last step applied 2026-11-12)

## Outcome funnel

| Stage | Jobs | Of the stage before |
|---|---|---|
| Qualified targets | 8 |  |
| Kit built | 2 | 25% |
| Applied | 2 | 100% |
| Employer response | 1 | 50% |
| Interview | 1 | 100% |
| Offer | 0 | 0% |

## In progress

| Job | Score | Stage | Last step | Next |
|---|---|---|---|---|
| [Northwind Freight (through Summit Staffing): Senior Product Manager, Freight Marketplace](../3-applications/northwind-freight-sr-pm-marketplace/job-description.txt) | 76 | interview: round 2 on 2026-11-24 | interview 2026-11-18 (today) | Send the round 1 thank-you to the recruiter (draft in the kit folder) |
| [Harborline Logistics: Senior Product Manager, Shipment Visibility](https://example.com/jobs/9100000001) | 90 | applied | applied 2026-11-12 (6 days ago) | Wait for a response; tell me when you hear back |

## Apply next

A and B jobs with no application yet, best first. Several roles at one company: the top 2 lead, the rest wait in reserve. C and D jobs (2) are not queued; they are in the round report.

**Open?** comes from `engine/staleness.py`: confirm a job is still open before kit work or applying (fresh = seen open in the last 3 days).

| # | Tier | Score | Job | 1st-degree | Kit | Open? | Next step |
|---|---|---|---|---|---|---|---|
| 1 | A | 88 | [Cobalt Route: Staff Product Manager, Carrier Integrations API](https://example.com/jobs/9100000002) |  | - | check | Say **prep Cobalt Route** (stretch review, then kit) |
| 2 | A | 86 | [Arcadia Fleet: Senior Product Manager, Fleet Platform APIs](https://example.com/jobs/9100000009) |  | - | check | Say **prep Arcadia Fleet** (stretch review, then kit) |
| 3 | B | 70 | [Pinecrest Health Supply: Senior Product Manager, Inventory Planning](https://example.com/jobs/9100000008) |  | - | check | Say **prep Pinecrest Health Supply** (stretch review, then kit) |
| 4 | B | 68 | [Brightdock: Principal Product Manager, Warehouse Automation](https://example.com/jobs/9100000003) |  | - | check | Say **prep Brightdock** (stretch review, then kit) |

## Not applying

| Job | Score | Decision | Note |
|---|---|---|---|
| [Tessellate Systems: Product Manager, Logistics Data Platform](https://example.com/jobs/9100000005) | 52 | passed 2026-11-14 | dbt is required; not worth the stretch |
