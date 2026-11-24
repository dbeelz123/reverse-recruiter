# Job review rubric (judgment step)

Used by Claude in Claude Code (V1) and by a standalone script calling the Claude API (V2).
Input: one job record from `jobs/<id>.json`, plus `spec.json` and `profile.json`.
Output: one entry in `reviews/round-NN.json` (fields below).

## Rules
1. Read the **whole** posting. Skimming is the problem this tool exists to fix.
2. Pull out buried details: work arrangement vs. what the header says, location/residency limits, travel %, clearance, contract vs. full-time, pay (and whether it includes bonus), years required, degree requirements, industry/customers (defense check), working-hours constraints.
3. Apply `spec.json`:
   - any dealbreaker → `tier: "X"` and state it in `dealbreakers`
   - negatives lower `fit`; positives raise it
   - criteria still `proposed` count, but flag uncertainty in `caveats`
4. Compare requirements against `profile.json`; list unmet ones in `gaps` (feeds the skills-gap tally).
5. Connections: only 1st-degree count; add `network_bonus: 8` when present. Ignore 2nd/3rd-degree people and alumni. Record the plain 8 whatever the connection's level: when `spec.json` → `scoring.network` has `neutral_points`, `build_report.py` sets the points from the person's level (`engine/connections.py`): a recommendation either way (`7-recommendations/`), or the user's call in `5-criteria/connections.json`, **plus** (they'd ask this person for a referral) or **neutral** (they wouldn't). If the connection list wasn't captured but the posting's teaser names a 1st-degree person ("Pat • 1st", "Pat and others in your network"), note the name in `caveats`, so calibration can ask about them and tie them to the job (`job_ids`).
   **Calibration must ask** about every 1st-degree connection on a current job who has no recommendation and isn't in `connections.json` yet (`python engine/connections.py` lists them as "not yet classified"; so does the report's action items): "Would you ask <name> (<their role>, <company>) for a referral: plus or neutral?" Record the answer in `connections.json` (`strength`, `decided`, and `job_ids` for teaser-only names), then rebuild the report. Until then the person scores at `scoring.network.unclassified`.
6. A saved job is a candidate, not a preference (`spec.json` → `save_meaning`): it passed only a quick title, location and LinkedIn-match screen, without a read of the description. Score it on the posting alone; don't infer what the user wants from what they saved. Discovered jobs and leads are not evidence at all.
7. For every requirement the user doesn't clearly meet, say in `gaps` whether it is required or preferred. These feed the stretch review in application kits.
8. If the description is collapsed or cut off, don't guess: `tier: "?"`, `fit: null`, ask for a re-save.
9. **Eligibility and regulated-environment requirements** (set 2026-11-17): the candidate's baseline is in `spec.json` → `eligibility_baseline`. List **every** requirement beyond that in `eligibility`, quoting the posting, even when it isn't a dealbreaker: U.S.-person / citizenship-only / ITAR or EAR export control, clearance or public trust (already a dealbreaker), background, credit or fingerprint checks, drug screening, licensing or certification, residency or on-shore-only, data-sovereignty, FedRAMP/CMMC/HIPAA/GxP/SOX-type compliance ownership, and "regulated industry" language that implies these (e.g. "industries where security, governance, and data sovereignty are non-negotiable"). Say for each whether it is a requirement of the person or a property of the product/customers. The candidate decides the impact; apply spec rules only where one already exists (clearance → dealbreaker; drug screening → negative).

## Output fields
- `fit` (0-100 or null), `network_bonus` (0 or 8; the report sets the final points from the connection's level, rule 5), `tier` (A ≥80, B 65-79, C 50-64, D <50, X excluded, ? incomplete)
- `summary`: one or two sentences, plain language
- `positives`, `caveats` ("looks good, but…"), `dealbreakers`, `gaps`
- `eligibility`: list of `{requirement, quote, applies_to: "person" | "product/customers"}` (rule 9); empty list when there is nothing beyond the baseline
- `pay`: as posted, normalized (note if it includes bonus or is location-adjusted)
- `adjustments`: list of `{reason, points}` for every confirmed rule in `spec.json` → `scoring` (domain 60/40 bonus, travel sliding scale, …; skip any rule marked "superseded"). Keep `fit` as the pure review judgment so each rule's effect stays visible; the report computes total = fit + adjustments + network bonus and sets the tier from the total.

## Re-screen (end of every round)
After the spec changes, run `engine/rescreen.py`. For each flag, read the excerpt in context: a passing mention ("observability" in a company blurb, a degree that allows equivalent experience, travel up to 10%) is not a hit. If a rule really applies, update the job's entry in its original `reviews/round-NN.json` (tier X with the dealbreaker, or an adjustment for a scored negative) and add `rescreened: "<date> vs spec vX: <outcome>"`; otherwise note `no change`. Dealbreaker hits go through the removal prompt.
