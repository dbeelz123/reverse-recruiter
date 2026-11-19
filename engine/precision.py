"""Triage precision: how good the agent's per-card call ("likely") is, and where it goes wrong.

Usage:
  python engine/precision.py [--round N] [--data my-data]

The agent records a call on every batch card before the user decides (searches.json -> triage_flow 3b):
  likely keep / lean keep / possible: <what's missing> / lean DQ / weak (= likely DQ)
This report compares those calls with what happened next, in three layers:
  1. Decision: did the user decide the way the call pointed? Counted with and without the match gate (DQs that came
     from LinkedIn's match line, below strong, which a card doesn't show: modes.match_gated). The figure with the
     gate is what modes.py uses for the stability signal.
  2. Hedges: the share of cards called "possible".
  3. Outcome of the cards User kept: tier after the full review (A/B/C/D), removed in review, or not yet reviewed.
Then it lists every miss (a firm or lean call decided the other way), match-gated ones apart, with the agent's
"why" and the user's reason: what Claude mines for better calls (guidance in triage_flow 3b; never criteria changes
without asking).
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modes import call_strength, likely_call, match_gated  # noqa: E402
from paths import Paths  # noqa: E402

GOOD = ("A", "B")


def load(p, default=None):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def label(x):
    v = (x.get("likely") or "").lower()
    s, d = call_strength(v), likely_call(v)
    return "possible" if s == "hedge" else f"{'likely' if s == 'firm' else 'lean'} {'keep' if d == 'keep' else 'DQ'}"


def outcome(x, jobs, tombs):
    jid = x.get("job_id")
    if jid in jobs:
        return (jobs[jid].get("review") or {}).get("tier") or "not reviewed"
    if jid in tombs:
        return "removed"
    return "not reviewed"


def cards(P, rnd):
    for f in sorted(P.search_runs.glob("*.json")):
        d = load(f)
        if rnd is not None and d.get("round") != rnd:
            continue
        for x in d.get("listings", []):
            if x.get("likely") and x.get("decision"):
                yield d.get("round"), f.stem, x


def report(P, rnd):
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    tombs = {t["job_id"]: t for t in load(P.removed, [])}
    order = ["likely keep", "lean keep", "possible", "lean DQ", "likely DQ"]
    table = {k: collections.Counter() for k in order}
    misses, gated_misses, rounds = [], [], set()
    for r, run, x in cards(P, rnd):
        rounds.add(r)
        k = label(x)
        t = table[k]
        t["cards"] += 1
        kept = x["decision"] in ("keep", "maybe")
        direction = likely_call(x.get("likely"))
        hit = direction == ("keep" if kept else "dq")
        if direction != "hedge":
            t["agree_all"] += hit
        if match_gated(x):
            t["gated"] += 1
            if direction == "keep":
                gated_misses.append((r, k, x, ""))
            continue
        t["judged"] += 1
        t["kept"] += kept
        if kept:
            o = outcome(x, jobs, tombs)
            t["good" if o in GOOD else ("removed" if o == "removed" else ("C/D" if o in ("C", "D") else "open"))] += 1
        if direction != "hedge":
            t["agree"] += hit
            if not hit:
                misses.append((r, k, x, outcome(x, jobs, tombs) if kept else ""))
    total = collections.Counter()
    for t in table.values():
        total.update(t)
    if not total["cards"]:
        print("No triage cards with a recorded call" + (f" in round {rnd}." if rnd is not None else "."))
        return
    scope = f"round {rnd}" if rnd is not None else f"rounds {', '.join(str(r) for r in sorted(rounds))}"
    print(f"# Triage precision ({scope}): {total['cards']} cards with a call\n")
    pct = lambda a, b: f"{a} of {b}" + (f" ({100 * a / b:.0f}%)" if b else "")
    committed_all = sum(table[k]["cards"] for k in order if k != "possible")
    committed = sum(table[k]["judged"] for k in order if k != "possible")
    print(f"- **Agreement on committed calls:** {pct(total['agree_all'], committed_all)}; without the match gate "
          f"{pct(total['agree'], committed)}.")
    print(f"- **Hedges:** {pct(table['possible']['cards'], total['cards'])} of cards were 'possible'.")
    print(f"- **Match gate:** {pct(total['gated'], total['cards'])} of cards were DQ'd on LinkedIn's match line, "
          f"which a card doesn't show.")
    print(f"- **Keeps that reached A/B:** {pct(total['good'], total['kept'])}\n")
    print("| Call | Cards | Decision agrees | Match-gated DQ | Other cards | User kept | Kept → A/B | → C/D | "
          "→ removed | Not reviewed |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in order:
        t = table[k]
        if t["cards"]:
            agree = "-" if k == "possible" else pct(t["agree_all"], t["cards"])
            print(f"| {k} | {t['cards']} | {agree} | {t['gated']} | {t['judged']} | {t['kept']} | {t['good']} | "
                  f"{t['C/D']} | {t['removed']} | {t['open']} |")
    if gated_misses:
        print("\n## Keep calls stopped by the match gate\n")
        print("What made LinkedIn rate these below strong is often visible in the title or company: worth a look.\n")
        for r, k, x, _ in gated_misses:
            print(f"- round {r}, {k}: {x.get('company')}: {x.get('title')} (agent: {x.get('why')})")
    if misses:
        print("\n## Misses (committed call, opposite decision)\n")
        print("| Round | Call | Job | Agent's why | User's decision and reason | Outcome |")
        print("|---|---|---|---|---|---|")
        for r, k, x, o in misses:
            md = lambda s: str(s or "").replace("|", "/")
            print(f"| {r} | {k} | {md(x.get('company'))}: {md(x.get('title'))} | {md(x.get('why'))} | "
                  f"{x['decision']}: {md(x.get('reason'))} | {o} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None)
    ap.add_argument("--round", type=int, default=None)
    a = ap.parse_args()
    report(Paths(a.data), a.round)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
