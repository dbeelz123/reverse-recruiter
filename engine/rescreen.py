"""Re-screen every current job against the current spec (run at the end of every round).

Usage:  python engine/rescreen.py [--data my-data]

Rules change between rounds, so jobs scored in earlier rounds can be out of date. This script is the
mechanical half of the re-screen: for each current job it checks
  - each rule's `title_regex` (dealbreakers, negatives, qualifiers) against the title,
  - each rule's `rescreen_regex` against the full posting and its "About the company" text,
  - the company blocklist against the company name,
  - each hybrid or on-site job's location against the current radius center and radius (OUTSIDE RADIUS, or
    DISTANCE UNKNOWN when the place isn't in 5-criteria/places.json); a job with no workplace recorded is checked
    too when its location names a city,
and prints every hit with a short excerpt. It changes nothing.

The judgment half is Claude's: read each flagged excerpt in context, decide whether the rule really
applies (a mention is not the job's focus), and update that job's entry in its reviews/round-NN.json
with a `rescreened` note. A real dealbreaker hit goes through the removal prompt.
"""
import argparse
import json
import re
from pathlib import Path

from locations import distance, home_state_of, load_places, within_radius
from paths import (Paths, blocked_by, blocklist, case_by_case, plain_bonus, radius_miles, read_job, read_json, review_score_problems,
                   spec_rules)


def excerpt(text, m, width=90):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return "..." + re.sub(r"\s+", " ", text[a:b]) + "..."


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    P = Paths(args.data)
    spec = read_json(P.spec, expect=dict)
    # Only confirmed rules are screened, so every rule's status is checked first (paths.spec_rules): a mistyped
    # status must stop the run, not drop the rule from it.
    rules = [(kind, r) for kind, section in (("DEALBREAKER", "dealbreakers"), ("NEGATIVE", "negatives"),
                                             ("QUALIFIER", "qualifiers"))
             for r in spec_rules(spec, P.spec, section) if r["status"] == "confirmed"]
    blocklist(spec, P.spec)
    blocked = [b for b in spec_rules(spec, P.spec, "company_blocklist") if b["status"] == "confirmed"]
    radius = radius_miles(spec, P.spec)
    # Check every rule's patterns once, up front, so a typo in spec.json names the rule instead of crashing midway.
    bad = []
    for kind, rule in rules:
        for field in ("title_regex", "rescreen_regex"):
            if rule.get(field) is not None and rule[field] != "":
                name = str(rule.get("value", "?"))[:60]
                if not isinstance(rule[field], str):  # a number or a list where the pattern's text belongs
                    bad.append(f"  {kind} {name!r}: {field} must be text, not {rule[field]!r}")
                    continue
                try:
                    re.compile(rule[field])
                except re.error as e:
                    bad.append(f"  {kind} {name!r}: {field} {rule[field]!r} ({e})")
    if bad:
        raise SystemExit(f"Invalid patterns in {P.spec}:\n" + "\n".join(bad))

    # Read reviews straight from reviews/round-NN.json (latest round wins), so jobs reviewed this round
    # are covered even before build_report.py has copied review blocks into the job records.
    reviews = {}
    for rf in sorted(P.reviews.glob("round-*.json")):
        rd = read_json(rf, expect=dict)
        jobs = rd.get("jobs", {})
        if not isinstance(jobs, dict):
            raise SystemExit(f"Malformed review file {rf}: 'jobs' must be an object keyed by job ID.")
        for jid, rv in jobs.items():
            problems = (review_score_problems(rv, plain_bonus(spec)) if isinstance(rv, dict)
                        else ["the entry isn't an object"])
            if problems:
                raise SystemExit(f"Malformed review for job {jid} in {rf}:\n  " + "\n  ".join(problems))
            adj = rv.get("adjustments", [])
            total = (rv.get("fit") or 0) + rv.get("network_bonus", 0) + sum(a["points"] for a in adj)
            reviews[jid] = dict(rv, round=rd.get("round"), total=total)

    # The location rule has no text pattern: hybrid and on-site jobs are checked against the current center and
    # radius, so a changed center or radius reaches jobs reviewed under the old one.
    rule = (spec.get("work_arrangement") or {}).get("machine_rule") or {}
    c = rule.get("hybrid_onsite_center")
    center = (c["lat"], c["lon"]) if c else None
    home_state = home_state_of(c.get("name")) if c else None
    load_places(P)

    print(f"Re-screen against spec v{spec.get('version')}\n")
    checked = 0
    for f in sorted(P.jobs.glob("*.json")):
        j = read_job(f)
        r = reviews.get(j["job_id"]) or j.get("review")
        if not r:
            print(f"NOT REVIEWED: {j['company']} - {j['title']} ({j['job_id']})\n")
            continue
        if r.get("tier") == "X":
            continue
        checked += 1
        # The posting and the "About the company" text: rules about the employer (its industry, its customers) are
        # often met only there.
        text = "\n\n".join(t for t in (j.get("posting_text"), j.get("company_text")) if isinstance(t, str) and t)
        hits = []
        for kind, rule in rules:
            name = rule["value"][:60]
            if rule.get("title_regex") and re.search(rule["title_regex"], j.get("title") or "", re.I):
                hits.append(f"  {kind} (title): {name}")
            if rule.get("rescreen_regex"):
                ms = list(re.finditer(rule["rescreen_regex"], text, re.I))
                if ms:
                    hits.append(f"  {kind} ({len(ms)}x): {name}\n      {excerpt(text, ms[0])}")
        company = (j.get("company") or "").lower()
        hit = blocked_by(company, blocked)
        if hit:
            soft = " (case by case: is this role in the blocked area?)" if case_by_case(hit) else ""
            hits.append(f"  BLOCKLIST{soft}: {hit['value']} ({hit.get('reason', 'no reason recorded')})")
        loc = j.get("location") or ""
        # A record with no workplace (the page showed no chip) can still be hybrid or on-site: its location is
        # checked unless it reads as remote or names no city ("United States").
        unknown = (j.get("workplace") not in ("Remote", "Hybrid", "On-site") and "," in re.sub(r"\(.*?\)", "", loc)
                   and not re.search(r"\bremote\b", loc, re.I))
        if center and (j.get("workplace") in ("Hybrid", "On-site") or unknown):
            inside = within_radius(loc, center, radius, home_state)
            if inside is False:
                d = distance(loc, center)
                what = "workplace not recorded: is it hybrid or on-site?" if unknown else j["workplace"]
                hits.append(f"  OUTSIDE RADIUS: {what} in {loc}"
                            + (f" (~{d} mi; radius {radius} mi)" if d is not None else f" (radius {radius} mi)"))
            elif inside is None and unknown:
                hits.append(f"  WORKPLACE UNKNOWN: workplace not recorded in {loc}: check whether it is hybrid or "
                            f"on-site, and its distance against the {radius}-mile radius")
            elif inside is None:
                hits.append(f"  DISTANCE UNKNOWN: {j['workplace']} in {loc}: check it against the {radius}-mile "
                            f"radius (add the city to places.json)")
        if hits:
            print(f"{j['company']} - {j['title']} (round {r.get('round')}, score {r.get('total')}, {j['job_id']})")
            print("\n".join(hits) + "\n")
    print(f"{checked} current jobs checked (tier X skipped).")
    manual = [r["value"][:80] for _, r in rules if not (r.get("rescreen_regex") or r.get("title_regex"))]
    if manual:
        print(f"{len(manual)} confirmed rules have no regex and are judged in review only:", *manual, sep="\n  - ")


if __name__ == "__main__":
    main()
