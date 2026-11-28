"""Merge a review round into the job records and write the re-screen report.

Usage:  python engine/build_report.py --round 1 [--data my-data]

Reads   6-system/jobs/*.json, 6-system/reviews/round-NN.json, 5-criteria/spec.json, 5-criteria/searches.json,
        6-system/skills-gap.json, 6-system/calibration/round-NN.json (optional). Locations: engine/paths.py.
Writes  "review" block into each job record, and 2-reports/<date>-round-NN-report.md
"""
import argparse
import collections
import json
import math
import re
from pathlib import Path

from paths import (PLAIN_BONUS, YMD, Paths, company_key, location_rule, plain_bonus, read_job, round_number, blocked_by, blocklist, case_by_case, latest_reviews,
                   read_json, review_score_problems, to_date, write_json)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_results import find_link  # noqa: E402
from locations import distance, home_state_of, load_places, within_radius  # noqa: E402

TIER_NAMES = {"A": "A - strong fit", "B": "B - good fit", "C": "C - possible", "D": "D - weak",
              "X": "Excluded (dealbreaker)", "?": "Incomplete - re-save needed"}
TIER_ORDER = ["A", "B", "C", "D", "X", "?"]
# How a connection's level (engine/connections.py) shows in the ranked table and in the connections list.
LEVEL_MARK = {"recommendation": " (recommendation)", "plus": "", "neutral": " (neutral)",
              "unclassified": " (not yet classified)"}
LEVEL_NOTE = {"recommendation": "; recommendation", "plus": "", "neutral": "; neutral: you wouldn't ask for a referral",
              "unclassified": "; not yet classified"}
TIER_COLORS = {"A": "#0C447C", "B": "#378ADD", "C": "#85B7EB", "D": "#B5D4F4"}  # one hue, darker = better


def tiers_svg(reviewed, path, rnd):
    """Jobs under consideration as one bar split into grade bands (A/B/C/D), each labeled with its count and share.
    Kept deliberately simple (decided 2026-11-17): the per-job ranked chart was too busy."""
    jobs = [j for j in reviewed if j["review"]["tier"] in TIER_COLORS]
    if not jobs:
        return None
    counts = collections.Counter(j["review"]["tier"] for j in jobs)
    n, W, H, x0, bw, y = len(jobs), 680, 150, 16, 648, 52
    names = {"A": "strong fit", "B": "good fit", "C": "possible", "D": "weak"}
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img">',
         f"<title>{n} jobs under consideration after round {rnd}: "
         + ", ".join(f"{counts[t]} {t}" for t in TIER_COLORS) + "</title>",
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         f'<text x="{x0}" y="30" font-size="16" font-weight="600" fill="#0B0B0B">{n} jobs under consideration '
         f'after round {rnd}</text>']
    x = x0
    for t in TIER_COLORS:
        c = counts[t]
        if not c:
            continue
        wd = bw * c / n
        ink = "#FFFFFF" if t in ("A", "B") else "#0C447C"
        s.append(f'<rect x="{x:.1f}" y="{y}" width="{max(wd - 3, 1):.1f}" height="44" rx="3" fill="{TIER_COLORS[t]}"/>')
        if wd >= 34:
            s.append(f'<text x="{x + wd / 2 - 1.5:.1f}" y="{y + 28}" font-size="16" font-weight="600" fill="{ink}" '
                     f'text-anchor="middle">{t} {c}</text>')
        s.append(f'<text x="{x + 2:.1f}" y="{y + 66}" font-size="12" fill="#52514E">{names[t]}</text>'
                 f'<text x="{x + 2:.1f}" y="{y + 82}" font-size="12" fill="#898781">{100 * c / n:.0f}%</text>')
        x += wd
    s.append("</svg>")
    path.write_text("\n".join(s), encoding="utf-8")
    return path


def load(p: Path, default=None):
    return read_json(p, default)


def check_review(path, jid, r, plain=PLAIN_BONUS):
    """Stop with the file, job and field when a review entry is malformed, instead of a KeyError mid-report."""
    problems = []
    if not isinstance(r, dict):
        problems.append("the entry isn't an object")
    else:
        problems += review_score_problems(r, plain)
        if r.get("tier") not in TIER_ORDER:
            problems.append(f"'tier' must be one of {', '.join(TIER_ORDER)}")
        if not isinstance(r.get("summary", ""), str):
            problems.append("'summary' must be text")
    if problems:
        raise SystemExit(f"Malformed review for job {jid} in {path}:\n  " + "\n  ".join(problems))


def whole_score(x):
    """A score as the whole number the report prints, a half point always rounding up (64.5 -> 65, 79.5 -> 80).
    Python's round() goes to the even number instead, which made 64.5 a 64 and 65.5 a 66. The tier is then set from
    this printed number, on purpose: the rubric's bands are whole numbers (A from 80, B from 65, C from 50), and a
    job shown as 80 in band B would contradict the page it is printed on."""
    return math.floor(x + 0.5)


def lead_is_saved(title, company, saved):
    """A lead that is really one of the saved jobs (LinkedIn sometimes re-labels the company): the same title and
    company, or a lead title ending in the saved title with the saved company's first word in the lead as a whole
    word. As a substring, a saved company called "Age of Supply" hid every lead with "Manager" in it."""
    lead = (title + " " + company).lower()
    for j in saved:
        st, sc = (j.get("title") or "").lower(), (j.get("company") or "").lower()
        if title.lower() == st and company.lower() == sc:
            return True
        words = [w for w in re.split(r"\W+", sc) if w]
        first_word = next((w for w in words if w != "the"), "")
        if (st and first_word and title.lower().endswith(st)
                and re.search(rf"(?<![a-z0-9]){re.escape(first_word)}(?![a-z0-9])", lead)):
            return True
    return False


def md_cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--data", default=None)
    ap.add_argument("--round", type=round_number, required=True)
    args = ap.parse_args()
    P = Paths(args.data)
    data = P.data
    rnd = f"round-{args.round:02d}"
    review = load(P.reviews / f"{rnd}.json")
    if not isinstance(review, dict) or not review.get("date"):
        raise SystemExit(f"No usable review file for round {args.round}: expected {P.reviews / f'{rnd}.json'} "
                         f"with a 'date' and a 'jobs' map. Write the round's reviews first.")
    # The date becomes part of the report's file name, so it must be a real day written YYYY-MM-DD: anything else
    # ("2026/11/14", "../x") would name a file in another folder, or stop after the records were rewritten.
    if not (isinstance(review["date"], str) and YMD.fullmatch(review["date"]) and to_date(review["date"])):
        raise SystemExit(f"The 'date' in {P.reviews / f'{rnd}.json'} must be a day written YYYY-MM-DD, not "
                         f"{review['date']!r}. Fix it and rerun; nothing was changed.")
    # Every round's review file is merged (latest round wins per job), so a re-screen edit to an
    # earlier round's entry reaches the job records and this report.
    spec = read_json(P.spec, {}, expect=dict)
    plain = plain_bonus(spec)
    all_reviews = latest_reviews(P, upto=args.round, check=lambda f, jid, r: check_review(f, jid, r, plain))
    import recommendations
    recs = recommendations.load(P)  # connections with a LinkedIn recommendation either way score higher
    import connections
    people = connections.load(P)  # the user's call on each connection: plus or neutral (connections.py)
    levels_on = connections.settings(spec) is not None
    gaps = read_json(P.skills_gap, {"items": []}, expect=dict)
    calibration = read_json(P.calibration / f"{rnd}.json", {"questions": []}, expect=dict)
    insights = [i for i in read_json(P.searches, {}, expect=dict).get("insights", []) if i.get("round") == args.round]
    # Every blocklist entry, proposed ones included, hides leads: proposed criteria count in reviews too
    # (engine/prompts/review-rubric.md, rule 3). rescreen.py flags only confirmed rules, to keep its flags firm.
    blocked = blocklist(spec, P.spec)
    loc_rule = location_rule(spec, P.spec)  # the whole rule is checked here, before any job record is rewritten
    center, radius = loc_rule["center"], loc_rule["radius"]
    home_state = home_state_of(loc_rule["name"]) if center else None
    load_places(P)

    jobs = {}
    # Every record is read and checked before the first one is rewritten: a damaged record further down the list
    # must stop the report before any review copy has changed, not after half of them have.
    records = [(f, read_job(f)) for f in sorted(P.jobs.glob("*.json"))]
    conflicts = []
    for f, rec in records:
        r, from_round = all_reviews.get(rec["job_id"], (None, None))
        if r:
            r = dict(r)
            adj = sum(a["points"] for a in r.get("adjustments", []))
            # The review records the plain connection bonus; the connection's level (recommendation, plus, neutral)
            # sets it here, so a new recommendation or a call on a person re-scores every job without touching the
            # review files.
            r["network_bonus"], found = connections.network_points(spec, r.get("network_bonus", 0), rec, recs, people)
            r.pop("recommendation", None)
            r.pop("network", None)
            if levels_on and found:
                r["network"] = [{"name": n, "level": lv} for n, lv in found]
            rm = recommendations.matches(rec, recs)
            if rm:
                r["recommendation"] = [{"name": n, "direction": d} for n, d in rm]
            r["total"] = None if r["fit"] is None else whole_score(r["fit"] + r.get("network_bonus", 0) + adj)
            if r["tier"] not in ("X", "?") and r["total"] is not None:
                r["tier"] = "A" if r["total"] >= 80 else "B" if r["total"] >= 65 else "C" if r["total"] >= 50 else "D"
            if r.get("dealbreakers") and r["tier"] != "X" and not r.get("held"):
                # The rubric makes any dealbreaker tier X. A review that lists one and still carries a grade is a
                # slip in the review file: it is named, never changed here. (A job held for calibration has a rule
                # suspended on purpose, and sits in its own section.)
                listed = r["dealbreakers"] if isinstance(r["dealbreakers"], list) else [r["dealbreakers"]]
                conflicts.append(f"WARNING: {rec.get('company') or '?'} - {rec.get('title') or '?'} "
                                 f"({rec['job_id']}) lists a dealbreaker but is ranked in tier {r['tier']}: "
                                 f"{' / '.join(str(d) for d in listed)}. If the dealbreaker stands, set its tier to "
                                 f"X in the review file (round {from_round}).")
            r["round"] = from_round
            rec["review"] = r
            write_json(f, rec, indent=2)
        elif "review" in rec:
            # The review files are the source of truth: a job whose entry is gone from them (deleted for a
            # re-review, or a later round's review when an earlier round is rebuilt) isn't ranked from the copy an
            # earlier build left in its record. It goes under "Not reviewed yet".
            del rec["review"]
            write_json(f, rec, indent=2)
        # Fields the report prints for every job, defaulted here (in memory only) so a record or review written
        # without one builds a report instead of stopping halfway, after the records were already rewritten.
        rec.setdefault("url", "")
        if isinstance(rec.get("review"), dict):
            rec["review"].setdefault("summary", "")
        jobs[rec["job_id"]] = rec

    # A review whose job record is gone (removed by hand, or a mistyped ID) is named rather than silently dropped.
    for jid in sorted(set(all_reviews) - set(jobs)):
        print(f"WARNING: review for job {jid} (round {all_reviews[jid][1]}) has no job record in "
              f"{P.rel(P.jobs)}; it's left out of the report. Remove the entry, or check the job ID.")
    for line in conflicts:
        print(line)

    reviewed = [j for j in jobs.values() if "review" in j]
    reviewed.sort(key=lambda j: (TIER_ORDER.index(j["review"]["tier"]), -(j["review"]["total"] or 0)))
    # Held for calibration (added 2026-11-26): a review with "held" (e.g. "leadership", "role type") has a rule the
    # user suspended for that job until a calibration decides it. It keeps its score for reference but stays off the
    # ranked list, the grade bands and the company groups, in a section of its own. A held job that hits another
    # dealbreaker (tier X) is listed as excluded as usual.
    held = [j for j in reviewed if j["review"].get("held") and j["review"]["tier"] != "X"]
    held_ids = {j["job_id"] for j in held}
    reviewed = [j for j in reviewed if j["job_id"] not in held_ids]
    out = []
    w = out.append
    w(f"# Saved jobs re-screen - round {args.round} ({review['date']})\n")
    # A job with no review in any round is listed on its own (never silently left out, never given a score).
    unreviewed = sorted((j for j in jobs.values() if "review" not in j),
                        key=lambda j: (j.get("company") or "", j.get("title") or ""))
    new = sum(1 for j in reviewed + held if j["review"].get("round") == args.round)
    w(f"{len(reviewed)} saved jobs, each read in full ({new} new this round; the rest keep their earlier review)"
      + (f", plus {len(held)} held for calibration (listed after the ranked list)" if held else "")
      + (f", plus {len(unreviewed)} not reviewed yet (listed after the ranked list)" if unreviewed else "")
      + ". Calibration questions at the end may still adjust scores.\n")
    if levels_on:
        pts, _ = connections.settings(spec)
        net_text = (f" + a 1st-degree connection: {pts['recommendation']:+g} when they have given you a LinkedIn "
                    f"recommendation or received one from you, {pts['plus']:+g} when you'd ask them for a referral, "
                    f"{pts['neutral']:+g} when you wouldn't (a recruiter may still notice the connection); the best "
                    f"connection at the company counts")
    else:
        net_text = (" + 8 for a 1st-degree connection" +
                    (f" ({rp:+g} instead when that connection has given you a LinkedIn recommendation or received one "
                     f"from you)" if isinstance(rp := ((spec.get("scoring") or {}).get("network") or {})
                                                .get("recommendation_points"), (int, float)) else ""))
    w("**Score** = fit from the full-text review (0-100) + adjustments from confirmed rules (domain 60/40, "
      "travel sliding scale, ...)" + net_text + ". The breakdown is shown as fit / adjustments / network.\n")

    # Search funnel (engine/metrics.py; recorded at the end of each round)
    if P.metrics.exists():
        import metrics
        w("## Search funnel: progress through the sea of jobs\n")
        w("Each job is counted once per stage (by company + title), so a job that reappears in later searches isn't "
          "counted again. 'Job listings processed' includes cards ruled out automatically and saved postings that never "
          "showed up as a search card (direct saves); 'LinkedIn baseline match' "
          "is your triage call on LinkedIn's match; 'Agent deep-fit review' is every saved PDF the agent read in full; "
          "'Qualified targets' are the jobs on the ranked list. Recorded at the end of each round by "
          "`engine/metrics.py --round N`.\n")
        img = metrics.funnel_svg(P, P.reports / f"{review['date']}-round-{args.round:02d}-funnel.svg")
        if img:
            w(f"![Search funnel after round {args.round}]({img.name})\n")
        w(metrics.table(P) + "\n")
        tt = metrics.timing_table(P)
        if tt:
            w("### Time per round\n")
            w("How long each stage took, from timing events logged during the round and file save times. "
              "'Per 100 job listings' divides the round's total by its job listings processed.\n")
            w(tt + "\n")
        # Triage mode (engine/modes.py; docs/how-it-works.md -> Triage modes): Catch-up progress and the stability signals
        # that decide when to ask about switching to Keep-up.
        import modes
        w("### Triage mode\n")
        prog = modes.progress_md(P)
        if prog:
            w("**Catch-up progress:** " + " ".join(prog) + "\n")
        w("\n".join(modes.signals_md(P)) + "\n")

    # Outcome funnel (engine/pipeline.py): ranked -> kit -> applied -> response -> interview -> offer.
    # Building it also refreshes 2-reports/apply-queue.md, the list of what to apply to next.
    import pipeline
    w("## Applications: from qualified target to offer\n")
    w("Picks up where the search funnel ends. A job counts at every stage it has reached; a rejection after "
      "applying counts as a response. What to do next for each job is in [apply-queue.md](apply-queue.md).\n")
    w(pipeline.funnel_table(pipeline.build(P)) + "\n")

    # Action items
    todo = []
    for j in reviewed + held:
        if j["review"]["tier"] == "?":
            todo.append(f"Re-save **{j['company']} - {j['title']}** with 'See more' expanded (description was collapsed).")
        if (any("in your network" in t for t in j.get("network_teaser", [])) and not j.get("people_file")
                and not j["review"].get("network")):
            todo.append(f"Save a `_people` file for **{j['company']} - {j['title']}**: the page shows "
                        f"'{j['network_teaser'][0]}' but the connection list wasn't captured.")
    unclassified = sorted({x["name"] for j in reviewed + held for x in j["review"].get("network", [])
                           if x["level"] == "unclassified"})
    if unclassified:
        todo.append(f"Connections not yet classified (would you ask them for a referral?): {', '.join(unclassified)}. "
                    f"Until you decide, each scores as the spec's 'unclassified' level.")
    if todo:
        w("## Action items for you\n")
        for t in todo:
            w(f"- {t}")
        w("")

    # Ranked table
    w("## Ranked list\n")
    img = tiers_svg(reviewed, P.reports / f"{review['date']}-round-{args.round:02d}-tiers.svg", args.round)
    if img:
        w(f"![Ranked list by grade after round {args.round}]({img.name})\n")
    w("| # | Score | Tier | Role | Company | Where | Pay (as posted) | 1st-degree |")
    w("|---|---|---|---|---|---|---|---|")
    for i, j in enumerate(reviewed, 1):
        r = j["review"]
        adj = sum(a["points"] for a in r.get("adjustments", []))
        parts = [str(r["fit"])] + ([f"{adj:+g}"] if adj else []) + ([f"+{r['network_bonus']} net"] if r.get("network_bonus") else [])
        score = "-" if r["total"] is None else (f"{r['total']}" + (f" ({' '.join(parts)})" if len(parts) > 1 else ""))
        pay = r.get("pay") or "; ".join(j.get("salary_mentions") or []) or "not listed"
        rec_names = {x["name"] for x in r.get("recommendation", [])}
        if r.get("network"):
            conn = ", ".join(x["name"] + LEVEL_MARK[x["level"]] for x in r["network"])
        else:
            conn = ", ".join(c["name"] + (" (recommendation)" if c["name"] in rec_names else "")
                             for c in j.get("connections_1st", [])) or ""
        if not conn and r.get("network_bonus"):
            conn = "referral (name withheld)"
        if j.get("external"):  # non-LinkedIn job (engine/ingest_external.py): say so, and show its pipeline stage
            pl = j.get("pipeline") or {}
            # Pipeline stage names (engine/pipeline.py) read as states here: "interview" -> "interviewing".
            shown = {"interview": "interviewing", "kit": "kit built", "response": "heard back",
                     "outreach": "outreach sent", "hold": "on hold"}.get(pl.get("status"), pl.get("status"))
            conn = "; ".join(x for x in (conn, "external" + (f" · {shown}" if shown else "")) if x)
        where = f"{j.get('workplace') or ''} - {j.get('location') or ''}"
        if center and j.get("workplace") in ("Hybrid", "On-site"):
            d = distance(j.get("location") or "", center)
            where += f" (~{d} mi)" if d is not None else " (distance unknown)"
        w(f"| {i} | {score} | {r['tier']} | [{md_cell(j['title'])}]({j['url']}) | {md_cell(j['company'])} | "
          f"{md_cell(where)} | {md_cell(pay)} | {md_cell(conn)} |")
    w("")
    if held:
        w("## Held for calibration\n")
        w("These jobs fall under a rule suspended for them until a calibration decides it (the reason is in 'Held "
          "for'). They are reviewed and scored as if that rule were lifted, but stay off the ranked list, the grade "
          "bands and the company groups until then.\n")
        held.sort(key=lambda j: (str(j["review"]["held"]), TIER_ORDER.index(j["review"]["tier"]),
                                 -(j["review"]["total"] or 0)))
        w("| # | Held for | Score if lifted | Tier if lifted | Role | Company | Where | Pay (as posted) |")
        w("|---|---|---|---|---|---|---|---|")
        for i, j in enumerate(held, 1):
            r = j["review"]
            pay = r.get("pay") or "; ".join(j.get("salary_mentions") or []) or "not listed"
            where = f"{j.get('workplace') or ''} - {j.get('location') or ''}"
            w(f"| {i} | {md_cell(str(r['held']))} | {'-' if r['total'] is None else r['total']} | {r['tier']} | "
              f"[{md_cell(j['title'])}]({j['url']}) | {md_cell(j['company'])} | {md_cell(where)} | {md_cell(pay)} |")
        w("")
        for j in held:
            r = j["review"]
            w(f"#### {j['company']} - {j['title']} (held: {r['held']})\n")
            w(f"{r['summary']}\n")
            if r.get("held_findings"):
                w("**Why it's held:** " + " / ".join(r["held_findings"]) + "\n")
            if r.get("positives"):
                w("**Looks good:** " + " / ".join(r["positives"]) + "\n")
            if r.get("caveats"):
                w("**But:** " + " / ".join(r["caveats"]) + "\n")
            if r.get("gaps"):
                w("*Skill gaps:* " + ", ".join(r["gaps"]) + "\n")
            w(f"[Posting]({j['url']})\n")
    if unreviewed:
        w("## Not reviewed yet\n")
        w("These jobs have a record but no review in any round's reviews file, so they have no score or tier. "
          "Review them (engine/prompts/review-rubric.md) and rebuild the report.\n")
        for j in unreviewed:
            title = md_cell(j.get("title") or "(no title)")
            w(f"- [{title}]({j['url']}) - {md_cell(j.get('company') or '')} ({j['job_id']})" if j.get("url")
              else f"- {title} - {md_cell(j.get('company') or '')} ({j['job_id']})")
        w("")

    # Company groups: several roles at one company are compared together before picking the top 1-2.
    groups = collections.defaultdict(list)
    for j in reviewed:
        if j["review"]["tier"] not in ("X", "?"):
            groups[company_key(j.get("company"))].append(j)
    multi = {k: v for k, v in groups.items() if k and len(v) >= 2}  # jobs with no company name aren't a group
    if multi:
        w("## Companies with several roles\n")
        w("Compared every round on current scores: the top 2 lead, the rest are held in reserve (kept and re-scored, "
          "not removed) and move up if they overtake. Ties and the final pick are yours.\n")
        w("| Company | Role | Score | Suggested |")
        w("|---|---|---|---|")
        for k, v in sorted(multi.items(), key=lambda kv: -max(x["review"]["total"] or 0 for x in kv[1])):
            v.sort(key=lambda x: -(x["review"]["total"] or 0))
            for i, j in enumerate(v):
                w(f"| {md_cell(j['company']) if i == 0 else ''} | [{md_cell(j['title'])}]({j['url']}) | "
                  f"{j['review']['total']} | {'lead' if i < 2 else 'reserve'} |")
        w("")

    # Network
    net = [j for j in reviewed + held if j.get("connections_1st") or j["review"].get("network")]
    w("## Your 1st-degree connections at these companies\n")
    for j in net:
        if j["review"].get("network"):
            heads = {c["name"]: c.get("headline") for c in j.get("connections_1st") or []}
            for x in j["review"]["network"]:
                w(f"- **{x['name']}** ({heads.get(x['name']) or 'no headline'}{LEVEL_NOTE[x['level']]}) "
                  f"- {j['company']}, *{j['title']}*")
            continue
        rec_dir = {x["name"]: x["direction"] for x in j["review"].get("recommendation", [])}
        for c in j["connections_1st"]:
            mark = {"received": "; recommended you", "given": "; you recommended them",
                    "both": "; recommendations both ways"}.get(rec_dir.get(c["name"]), "")
            w(f"- **{c['name']}** ({c.get('headline') or 'no headline'}{mark}) - {j['company']}, *{j['title']}*")
    w("")

    # Details
    w("## Job-by-job: looks good, but...\n")
    for tier in TIER_ORDER:
        group = [j for j in reviewed if j["review"]["tier"] == tier]
        if not group:
            continue
        w(f"### {TIER_NAMES[tier]}\n")
        for j in group:
            r = j["review"]
            score = "-" if r["total"] is None else r["total"]
            w(f"#### {j['company']} - {j['title']} ({score})\n")
            w(f"{r['summary']}\n")
            if r.get("eligibility"):
                w("**Eligibility / regulated requirements (beyond your baseline in spec.json):** "
                  + " / ".join(f"{e['requirement']} ({e.get('applies_to', 'person')}): \"{e.get('quote', '')}\""
                               for e in r["eligibility"]) + "\n")
            if r.get("dealbreakers"):
                w("**Dealbreaker:** " + " / ".join(r["dealbreakers"]) + "\n")
            if r.get("adjustments"):
                w("*Adjustments:* " + "; ".join(f"{a['reason']} ({a['points']:+g})" for a in r["adjustments"]) + "\n")
            if r.get("positives"):
                w("**Looks good:** " + " / ".join(r["positives"]) + "\n")
            if r.get("caveats"):
                w("**But:** " + " / ".join(r["caveats"]) + "\n")
            if r.get("gaps"):
                w("*Skill gaps:* " + ", ".join(r["gaps"]) + "\n")
            w(f"[Posting]({j['url']})\n")

    # Leads
    seen = collections.defaultdict(lambda: {"count": 0, "with": set(), "lead": None})
    for j in reviewed:
        for l in j.get("leads", []):
            k = (l["title"], l["company"])
            seen[k]["count"] += 1
            seen[k]["with"].add((j["company"], j["url"]))
            if l.get("connections_note") or not seen[k]["lead"]:
                seen[k]["lead"] = l

    def is_saved(title, company):
        return lead_is_saved(title, company, jobs.values())

    # The printed page has no link to the lead itself, so each lead gets a LinkedIn job search for it: the same
    # directed search the triage cards use (ingest_results.find_link: title and company as exact phrases).

    def shown_with(v, limit=4):
        items = sorted(v["with"])
        cell = ", ".join(f"[{md_cell(c)}]({u})" for c, u in items[:limit])
        return cell + (f" +{len(items) - limit} more" if len(items) > limit else "")

    def location_ok(loc):
        """Remote is fine anywhere; hybrid/on-site (or unstated) only within the radius.
        Unknown cities are kept (better to show than to hide wrongly)."""
        if not center or "(Remote)" in loc:
            return True
        inside = within_radius(loc, center, radius, home_state)
        return inside is not False

    leads, out_of_area = [], 0
    for k, v in seen.items():
        hit = blocked_by(k[1], blocked)
        if is_saved(*k) or (hit and not case_by_case(hit)):  # case-by-case companies stay visible
            continue
        if not location_ok(v["lead"]["location"]):
            out_of_area += 1
            continue
        leads.append((k, v))
    w("## Leads from 'More jobs' (not preference evidence)\n")
    w("LinkedIn's similar-job suggestions printed with your saved jobs. Listed for discovery only; "
      "blocklisted companies removed. 'Connections' means 1st-degree connections work there. "
      "**Find** opens a LinkedIn job search for that role (the printed page doesn't include a direct link); "
      "**Appeared on** links the saved jobs it was printed next to.\n")
    if out_of_area:
        w(f"{out_of_area} leads hidden because they are hybrid or on-site outside the allowed area "
          f"(remote anywhere; hybrid/on-site within {radius} miles of {loc_rule['name']}).\n")
    w("### At companies where you have connections\n")
    w("| Role | Company | Location | Connections | Find | Appeared on |")
    w("|---|---|---|---|---|---|")
    conn_leads = sorted([x for x in leads if x[1]["lead"].get("connections_note")], key=lambda x: -x[1]["count"])
    for (t, c), v in conn_leads:
        l = v["lead"]
        w(f"| {md_cell(t)} | {md_cell(c)} | {md_cell(l['location'])} | {md_cell(l['connections_note'])} | "
          f"[Find]({find_link(t, c)}) | {shown_with(v)} |")
    w("\n### Most frequently suggested\n")
    w("| Role | Company | Location | Pay | Find | Appeared on |")
    w("|---|---|---|---|---|---|")
    for (t, c), v in sorted(leads, key=lambda x: -x[1]["count"])[:15]:
        l = v["lead"]
        w(f"| {md_cell(t)} | {md_cell(c)} | {md_cell(l['location'])} | {md_cell(l.get('salary', ''))} | "
          f"[Find]({find_link(t, c)}) | {shown_with(v)} |")
    w("")

    # Skills gap
    w("## Skills gap (running tally)\n")
    w(f"{gaps.get('method', '')}\n")
    w("| Skill | Status | Weight | DQ demand | Seen in | Suggested action |")
    w("|---|---|---|---|---|---|")
    label = {"have": "Have", "have_not_on_resume": "Have - not on resume", "partial": "Partial",
             "missing": "Missing", "unknown": "Unknown - ask"}
    for it in sorted(gaps["items"], key=lambda x: (x["category"] == "have", -(x["weight"] + x.get("dq_demand", 0)))):
        seen = ", ".join(it["jobs"] + [f"{j} (DQ)" for j in it.get("dq_jobs", [])])
        w(f"| {md_cell(it['skill'])} | {label.get(it['category'], it['category'])} | {it['weight']} | "
          f"{it.get('dq_demand', 0)} | {md_cell(seen)} | {md_cell(it.get('action') or '')} |")
    w("")

    # Resume & LinkedIn update candidates: skills the user has that their documents don't show yet
    cands = [it for it in gaps["items"] if it["category"] == "have_not_on_resume"]
    if cands:
        w("## Resume & LinkedIn update candidates\n")
        w("Skills you have that the resume or LinkedIn doesn't show yet. The optional end-of-round review "
          "turns these into tracked changes and paste-ready LinkedIn text.\n")
        for it in sorted(cands, key=lambda x: -(x["weight"] + x.get("dq_demand", 0))):
            w(f"- **{it['skill']}** (weight {it['weight']}, DQ demand {it.get('dq_demand', 0)}): {it.get('action') or ''}")
        w("")

    # Training tracks: gaps grouped by the role type that asks for them
    if gaps.get("tracks"):
        by_name = {it["skill"]: it for it in gaps["items"]}
        w("## Training tracks\n")
        w("Skill gaps grouped by the kind of role that requires or prefers them. Demand counts saved jobs "
          "(weight) and jobs DQ'd for a missing skill (DQ demand).\n")
        for t in gaps["tracks"]:
            w(f"### {t['track']}\n")
            w(f"*For:* {t['target']}\n")
            for s in t["skills"]:
                it = by_name.get(s, {})
                w(f"- **{s}**: {label.get(it.get('category'), it.get('category', '?'))}; "
                  f"weight {it.get('weight', 0)}, DQ demand {it.get('dq_demand', 0)}")
            w("\n*Steps:*")
            for i, step in enumerate(t["steps"], 1):
                w(f"{i}. {step}")
            if t.get("rules_it_could_retire"):
                w("\n*Closing this track could retire:* " + "; ".join(t["rules_it_could_retire"]))
            w("")

    # Search insights: trends across the round, each with a proposed search change
    if insights:
        w(f"## Search insights - round {args.round}\n")
        w("| Trend | Evidence | Proposal | Decision |")
        w("|---|---|---|---|")
        for i in insights:
            w(f"| {md_cell(i.get('trend', ''))} | {md_cell(i.get('evidence', ''))} | "
              f"{md_cell(i.get('proposal', ''))} | {md_cell(i.get('decision', 'open'))} |")
        w("")

    # Calibration questions
    questions = [q for q in (calibration.get("questions") or []) if isinstance(q, dict)]
    if questions:
        w(f"## Calibration questions - round {args.round}\n")
        for i, q in enumerate(questions, 1):
            w(f"{i}. **{q.get('topic') or 'Question'}:** {q.get('question') or ''}")
        w("")

    path = P.reports / f"{review['date']}-{rnd}-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path}  ({len(reviewed)} jobs, {len(conn_leads)} connection leads)")
    archive_earlier(P, args.round)


def archive_earlier(P, rnd):
    """Each round's report replaces the last: earlier rounds' reports and their images move to 2-reports/archive/.
    Rebuilding the same round simply overwrites its own files."""
    moved = []
    for f in sorted(P.reports.glob("*-round-*")):
        m = re.search(r"-round-(\d+)-(report\.md|funnel\.svg|tiers\.svg)$", f.name)
        if f.is_file() and m and int(m.group(1)) < rnd:
            (P.reports / "archive").mkdir(exist_ok=True)
            f.replace(P.reports / "archive" / f.name)
            moved.append(f.name)
    if moved:
        print("Archived earlier round files: " + ", ".join(moved))


if __name__ == "__main__":
    main()
