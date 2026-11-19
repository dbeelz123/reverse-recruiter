"""Re-screen every current job against the current spec (run at the end of every round).

Usage:  python engine/rescreen.py [--data my-data]

Rules change between rounds, so jobs scored in earlier rounds can be out of date. This script is the
mechanical half of the re-screen: for each current job it checks
  - each dealbreaker's `title_regex` against the title,
  - each rule's `rescreen_regex` (dealbreakers, negatives, qualifiers) against the full posting,
  - the company blocklist against the company name,
and prints every hit with a short excerpt. It changes nothing.

The judgment half is Claude's: read each flagged excerpt in context, decide whether the rule really
applies (a mention is not the job's focus), and update that job's entry in its reviews/round-NN.json
with a `rescreened` note. A real dealbreaker hit goes through the removal prompt.
"""
import argparse
import json
import re
from pathlib import Path

from paths import Paths, read_json


def excerpt(text, m, width=90):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return "..." + re.sub(r"\s+", " ", text[a:b]) + "..."


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    P = Paths(args.data)
    spec = read_json(P.spec)
    rules = ([("DEALBREAKER", r) for r in spec.get("dealbreakers", []) if r.get("status") == "confirmed"]
             + [("NEGATIVE", r) for r in spec.get("negatives", []) if r.get("status") == "confirmed"]
             + [("QUALIFIER", r) for r in spec.get("qualifiers", []) if r.get("status") == "confirmed"])
    blocked = [b["value"].split(" (")[0].lower() for b in spec.get("company_blocklist", [])
               if b.get("status") == "confirmed" and not b["value"].startswith("Companies owned")]
    # Check every rule's patterns once, up front, so a typo in spec.json names the rule instead of crashing midway.
    bad = []
    for kind, rule in rules:
        for field in ("title_regex", "rescreen_regex"):
            if rule.get(field):
                try:
                    re.compile(rule[field])
                except re.error as e:
                    bad.append(f"  {kind} {rule.get('value', '?')[:60]!r}: {field} {rule[field]!r} ({e})")
    if bad:
        raise SystemExit(f"Invalid patterns in {P.spec}:\n" + "\n".join(bad))

    # Read reviews straight from reviews/round-NN.json (latest round wins), so jobs reviewed this round
    # are covered even before build_report.py has copied review blocks into the job records.
    reviews = {}
    for rf in sorted(P.reviews.glob("round-*.json")):
        rd = read_json(rf)
        for jid, rv in rd.get("jobs", {}).items():
            total = (rv.get("fit") or 0) + rv.get("network_bonus", 0) + sum(a["points"] for a in rv.get("adjustments", []))
            reviews[jid] = dict(rv, round=rd.get("round"), total=total)

    print(f"Re-screen against spec v{spec.get('version')}\n")
    checked = 0
    for f in sorted(P.jobs.glob("*.json")):
        j = read_json(f)
        r = reviews.get(j["job_id"]) or j.get("review")
        if not r:
            print(f"NOT REVIEWED: {j['company']} - {j['title']} ({j['job_id']})\n")
            continue
        if r.get("tier") == "X":
            continue
        checked += 1
        text = j.get("posting_text") or ""
        hits = []
        for kind, rule in rules:
            name = rule["value"][:60]
            if kind == "DEALBREAKER" and rule.get("title_regex") and re.search(rule["title_regex"], j.get("title") or "", re.I):
                hits.append(f"  {kind} (title): {name}")
            if rule.get("rescreen_regex"):
                ms = list(re.finditer(rule["rescreen_regex"], text, re.I))
                if ms:
                    hits.append(f"  {kind} ({len(ms)}x): {name}\n      {excerpt(text, ms[0])}")
        company = (j.get("company") or "").lower()
        hits += [f"  BLOCKLIST: {b}" for b in blocked if b and b in company]
        if hits:
            print(f"{j['company']} - {j['title']} (round {r.get('round')}, score {r.get('total')}, {j['job_id']})")
            print("\n".join(hits) + "\n")
    print(f"{checked} current jobs checked (tier X skipped).")
    manual = [r["value"][:80] for _, r in rules if not (r.get("rescreen_regex") or r.get("title_regex"))]
    if manual:
        print(f"{len(manual)} confirmed rules have no regex and are judged in review only:", *manual, sep="\n  - ")


if __name__ == "__main__":
    main()
