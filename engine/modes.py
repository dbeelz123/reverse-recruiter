"""Triage modes (Catch-up / Keep-up): the stability signals that say when to ask about switching.

Usage:
  python engine/modes.py signals [--data my-data]   per-round signals table + the verdict (run at every round's end,
                                                    after metrics.py --round N and before build_report.py)
  python engine/modes.py tag [--data my-data]       stamp the current mode on search-run files and metrics rounds
                                                    that don't have one yet (triaged.py add and metrics.py --round N
                                                    also stamp it, so this is for backfills)

The mode itself lives in 5-criteria/searches.json -> "mode" (mode, builder, goal, lookback, pace, cadence,
last_asked). Process and thresholds: docs/how-it-works.md -> Triage modes (approved 2026-11-18).

Signals, per round:
  rules per 100   new criteria rules / search cards processed. A criteria rule is a changelog row whose Type changes a
                  dealbreaker, negative, blocklist, qualifier, exception or scoring rule (process and search changes
                  don't count). Each changelog heading carries "[round N]".
  agreement       the agent's "likely" call on each triage card vs. the user's decision. "likely keep" / "lean keep"
                  -> keep, "weak" / "likely DQ" / "lean DQ" -> DQ, "possible" = a hedge. Agreement is measured on
                  firm and lean calls; the hedge share is shown beside it (Keep-up's bulk confirm needs few hedges).
                  DQs that came from LinkedIn's match line count too: in Keep-up the user overrules a wrong pre-sort
                  either way. engine/precision.py also shows agreement without them (match_gated).
  already decided share of a round's cards that were already decided (DQ'd before, Viewed, Saved, kept before).
  keep rate       keeps (and maybes) per 100 cards.
  Both are shares of the cards recorded as rows in the run files. A run's unrecorded_cards (a backfilled count with
  no rows) add to "Search cards processed" only: nothing is known about them, so they are in neither share.

Catch-up -> Keep-up: ask when VOLUME (>= VOLUME_LISTINGS processed within VOLUME_DAYS, or the goal reached) and at
least 2 of 4 STABILITY signals hold. In builder mode the verdict is reported, never asked.

Volume, the goal and rules per 100 count search-result cards only (the funnel's "cards"), not the saved postings
that never showed up as a card, which the funnel's "Job listings processed" also counts: the modes are about
triage, and a backlog sweep of direct saves is not triage volume.
Keep-up -> a Catch-up burst: suggest one after a gap of more than GAP_DAYS since the last round.
"""
import argparse
import collections
import datetime as dt
import json
import math
import re
import shutil
from pathlib import Path

import metrics
from paths import Paths, read_json, read_run, write_json, to_date

VOLUME_LISTINGS, VOLUME_DAYS = 300, 14
RULES_PER_100_MAX, RULES_ROUNDS = 1.0, 2       # fewer than 1 new rule per 100 listings, two rounds running
AGREE_MIN, HEDGE_MAX = 0.90, 0.25              # firm calls match >= 90%, and no more than 25% of cards hedged
ALREADY_MIN = 0.70                             # 70% or more of a run's cards already decided
STEADY_ROUNDS, STEADY_RATIO = 3, 1.5           # keep rate: last 3 rounds within a 1.5x band
GAP_DAYS = 21


def in_window(date, today):
    """True when date (YYYY-MM-DD) falls in the last VOLUME_DAYS days up to today. A future date is a typo, not recent
    work, so it never counts."""
    d = to_date(date)
    return bool(d) and 0 <= (today - d).days <= VOLUME_DAYS


CRIT = re.compile(r"dealbreaker|negative|blocklist|qualifier|scoring|rule added|exception|open rule|evidence|"
                  r"neutral|exemption|confirmed", re.I)
ALREADY = ("already dq", "viewed", "saved", "kept before", "dq after save")


def mode(P):
    d = read_json(P.searches)
    return d.get("mode") or {"mode": "catch-up", "builder": True}


def likely_call(v):
    """Direction of the agent's call: keep, dq, hedge (possible), or None. Leans count as their direction."""
    v = (v or "").lower().strip()
    if not v:
        return None
    if v.startswith(("likely keep", "lean keep")):
        return "keep"
    if v.startswith(("weak", "likely dq", "lean dq")):
        return "dq"
    return "hedge"


def call_strength(v):
    """firm (likely keep / weak / likely DQ), lean (lean keep / lean DQ) or hedge (possible)."""
    v = (v or "").lower().strip()
    if not v:
        return None
    if v.startswith("lean"):
        return "lean"
    return "hedge" if likely_call(v) == "hedge" else "firm"


# linkedin_match values below the save line, on either scale (docs/how-it-works.md -> The platform's match line): a
# free account shows well / some / missing, a Premium account top / high / medium / low.
MATCH_BELOW_SAVE = ("some", "missing", "some/missing", "below strong", "medium", "low")


def match_gated(x):
    """True when the user's DQ came from LinkedIn's match line (below strong), which the agent can't see on the card.
    engine/precision.py reports agreement with and without these (2026-11-18)."""
    if x.get("decision") != "dq":
        return False
    m = str(x.get("linkedin_match") or "").lower()
    return str(x.get("reason") or "").lower().startswith("linkedin match below strong") or \
        m in MATCH_BELOW_SAVE


def rules_per_round(P):
    crit = collections.Counter()
    rnd = None
    if not P.changelog.exists():  # written at the first calibration: a new data folder has none, so no rules yet
        return crit
    for line in P.changelog.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("## "):
            m = re.search(r"\[round (\d+)\]", line)
            rnd = int(m.group(1)) if m else None
        elif rnd and line.startswith("|") and not line.startswith(("|---", "| Change")):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            t = cells[1] if len(cells) > 1 else ""
            if CRIT.search(t) and "process" not in t.lower():
                crit[rnd] += 1
    return crit


def card_stats(P):
    per = collections.defaultdict(collections.Counter)
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_run(f)
        if "round" not in d:
            continue
        c = per[int(d["round"])]
        for x in d.get("listings", []):
            st = str(x.get("status") or "").lower()
            if st.startswith("invalid") or st.startswith("duplicate"):
                continue
            c["cards"] += 1
            if st.startswith(ALREADY):
                c["already"] += 1
            dec = x.get("decision")
            if dec in ("keep", "maybe"):
                c["keep"] += 1
            call = likely_call(x.get("likely"))
            if call and dec:
                c["predicted"] += 1
                if call == "hedge":
                    c["hedge"] += 1
                else:
                    c["firm"] += 1
                    c["agree"] += call == ("keep" if dec in ("keep", "maybe") else "dq")
    return per


def rows(P):
    m = metrics.load(P)
    funnel, rules, cards = metrics.funnel_from_runs(P), rules_per_round(P), card_stats(P)
    out = []
    for r in metrics.done(m):
        n, c = r["round"], cards.get(r["round"], collections.Counter())
        f = funnel.get(n, {})
        processed = f.get("cards", f.get("processed", 0))  # search cards only: direct saves aren't triage volume
        out.append({
            "round": n, "date": r.get("date"), "mode": r.get("mode"), "processed": processed, "rules": rules[n],
            "phone": f.get("phone", 0),  # phone-triage saves: no cards, so no triage volume or rates
            "rec": f.get("rec", 0),  # the recommendation-save share of "phone"
            "rules_per_100": 100 * rules[n] / processed if processed else None,
            "cards": c["cards"], "already": c["already"] / c["cards"] if c["cards"] else None,
            "keep_rate": 100 * c["keep"] / c["cards"] if c["cards"] else None,
            "firm": c["firm"], "agree": c["agree"], "predicted": c["predicted"], "hedge": c["hedge"]})
    return out


def verdict(P, rs):
    """Which signals hold now, from the latest rounds that have search runs."""
    with_runs = [r for r in rs if r["cards"]]
    today = dt.date.today()
    recent = sum(r["processed"] for r in rs
                 if in_window(r["date"], today))
    goal = mode(P).get("goal")
    total = sum(r["processed"] for r in rs)
    volume = recent >= VOLUME_LISTINGS or bool(goal and total >= goal)

    last_rules = [r["rules_per_100"] for r in with_runs[-RULES_ROUNDS:]]
    s_rules = len(last_rules) == RULES_ROUNDS and all(x is not None and x < RULES_PER_100_MAX for x in last_rules)
    pred = [r for r in with_runs if r["predicted"]][-1:]  # latest round that recorded the agent's calls
    s_agree = bool(pred) and pred[0]["firm"] > 0 and pred[0]["agree"] / pred[0]["firm"] >= AGREE_MIN \
        and pred[0]["hedge"] / pred[0]["predicted"] <= HEDGE_MAX
    s_already = bool(with_runs) and (with_runs[-1]["already"] or 0) >= ALREADY_MIN
    rates = [r["keep_rate"] for r in with_runs[-STEADY_ROUNDS:]]
    s_steady = len(rates) == STEADY_ROUNDS and min(rates) > 0 and max(rates) / min(rates) <= STEADY_RATIO
    stab = {"rules per 100 under 1 (two rounds)": s_rules, "agreement 90%+ with few hedges": s_agree,
            "70%+ already decided": s_already, "steady keep rate": s_steady}
    return {"volume": volume, "recent": recent, "total": total, "goal": goal, "stability": stab,
            "met": sum(stab.values())}


def fmt(x, spec):
    return "–" if x is None else format(x, spec)


def signals_md(P):
    """The signals table, the volume and stability checks and the verdict, as Markdown lines."""
    md, rs = mode(P), rows(P)
    out = [f"Mode: **{md.get('mode')}**{' (builder: report only, never ask)' if md.get('builder') else ''}"
           + (f" · cadence {md['cadence']}" if md.get("mode") == "keep-up" and md.get("cadence") else ""), "",
           "| Round | Mode | Search cards processed | New criteria rules | Rules per 100 | Already decided | "
           "Keeps per 100 recorded cards | Agent calls (firm agree / hedged) |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rs:
        calls = (f"{r['agree']}/{r['firm']} ({100 * r['agree'] / r['firm']:.0f}%) / {r['hedge']} of {r['predicted']}"
                 if r["predicted"] and r["firm"] else f"0 firm / {r['hedge']} of {r['predicted']}" if r["predicted"]
                 else "–")
        lab = metrics.untracked_label(r["phone"], r.get("rec", 0))
        shown = (r["processed"] or "–") if not r["phone"] else \
            (f"{r['processed']} + unknown ({lab})" if r["processed"] else f"unknown ({lab})")
        out.append(f"| {r['round']} | {r['mode'] or '–'} | {shown} | {r['rules']} | "
                   f"{fmt(r['rules_per_100'], '.1f')} | {fmt(r['already'] and 100 * r['already'], '.0f')}"
                   f"{'%' if r['already'] is not None else ''} | {fmt(r['keep_rate'], '.0f')} | {calls} |")
    v = verdict(P, rs)
    goal = f", goal {v['goal']}" if v["goal"] else ""
    out += ["", f"Volume: {'met' if v['volume'] else 'not met'} ({v['recent']} search cards in the last {VOLUME_DAYS} "
                f"days; {v['total']} in all{goal}).",
            f"Stability: {v['met']} of 4 (need 2): " +
            "; ".join(f"{k} {'yes' if ok else 'no'}" for k, ok in v["stability"].items()) + "."]
    m = md.get("mode")
    last = rs[-1]["date"] if rs else None
    if m == "keep-up" and to_date(last) and (dt.date.today() - to_date(last)).days > GAP_DAYS:
        out.append(f"SUGGEST A CATCH-UP BURST: the last round was {last}, more than {GAP_DAYS} days ago.")
    elif m == "catch-up" and v["volume"] and v["met"] >= 2:
        later = md.get("ask_again") and md["ask_again"] > dt.date.today().isoformat()
        out.append("Ready to switch by the numbers, but builder mode is on: report it, don't ask."
                   if md.get("builder") else
                   f"Ready to switch by the numbers; the user asked to be asked again after {md['ask_again']}."
                   if later else
                   "ASK USER: stay in Catch-up, switch to Keep-up (suggest a cadence), or ask again in N weeks? "
                   "(record the answer: modes.py set --asked [--ask-again-days N | --mode keep-up --cadence ...])")
    else:
        out.append("No switch prompt: " + ("builder mode is on." if md.get("builder")
                                           else "the signals aren't there yet."))
    return out


def signals(P):
    print("\n".join(signals_md(P)))


# ---- Catch-up: setup interview answers and progress (built 2026-11-18) ------------------------------------------
LOOKBACK = re.compile(r"^(week|month|any|\d+d)$")


def save_mode(P, md):
    d = read_json(P.searches)
    d["mode"] = md
    write_json(P.searches, d, indent=1)


def setup(P, a):
    """Record the Catch-up setup interview's answers (Claude asks the questions; docs/how-it-works.md -> Triage modes)."""
    md = mode(P)
    if a.goal is not None:
        md["goal"] = a.goal if a.goal > 0 else None
    if a.lookback is not None:
        if a.lookback not in ("", "default") and not LOOKBACK.match(a.lookback):
            raise SystemExit("--lookback: week, month, any, <N>d (e.g. 60d), or default (each search's own window)")
        md["lookback"] = None if a.lookback in ("", "default") else a.lookback
    if a.pace is not None:
        md["pace"] = a.pace or None
    if a.fuzzy is not None:
        md["fuzzy"] = [x.strip() for x in a.fuzzy.split(";") if x.strip()]
    md["setup_done"] = dt.date.today().isoformat()
    save_mode(P, md)
    print(json.dumps(md, indent=1, ensure_ascii=False))


def backlog(P):
    """Listings LinkedIn reported but not yet captured, from each active search's latest run (result_count - cards)."""
    latest = {}
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_run(f)
        sid = (str(d.get("search") or "").split() or [""])[0]  # a run with no search (phone triage) has none
        if d.get("status") == "invalid" or not sid:
            continue
        if sid not in latest or (d.get("date", ""), f.name) >= (latest[sid].get("date", ""), latest[sid]["_f"]):
            latest[sid] = dict(d, _f=f.name)
    active = {s["id"] for s in read_json(P.searches)["searches"]
              if s.get("status") != "retired"}
    known, unknown = 0, []
    for sid in sorted(active):
        d = latest.get(sid)
        if d and isinstance(d.get("result_count"), int):
            rows_ = [x for x in d.get("listings", []) if not str(x.get("status", "")).startswith(("invalid", "duplicate"))]
            known += max(0, d["result_count"] - len(rows_) - d.get("unrecorded_cards", 0))
        else:
            unknown.append(sid)
    return known, unknown


def progress_md(P):
    """Catch-up progress for the round report: goal, processed, backlog left, pace and projected finish."""
    md, rs = mode(P), rows(P)
    if md.get("mode") != "catch-up":
        return []
    total = sum(r["processed"] for r in rs)
    today = dt.date.today()
    window = [r for r in rs if in_window(r["date"], today)]
    recent = sum(r["processed"] for r in window)
    span = max(1, (today - min(to_date(r["date"]) for r in window)).days + 1) if window else None
    per_day = recent / span if span else 0
    goal = md.get("goal")
    out = []
    if goal:
        left = max(0, goal - total)
        line = f"Goal: {goal} listings. Search cards processed: {total} ({100 * total / goal:.0f}%). Left: {left}."
        if left and per_day:
            finish = today + dt.timedelta(days=round(left / per_day))
            line += f" At the last {VOLUME_DAYS} days' pace ({per_day:.0f} a day), about {finish.isoformat()}."
        elif not left:
            line += " Goal reached: the switch check counts this as volume met."
        out.append(line)
    else:
        out.append(f"No goal set (the Catch-up setup interview sets one). Search cards processed so far: {total}; "
                   f"last {VOLUME_DAYS} days: {recent}.")
    known, unknown = backlog(P)
    out.append(f"Backlog not yet captured: {known} listings LinkedIn reported beyond what the latest runs captured"
               + (f"; no result count recorded for {', '.join(unknown)}" if unknown else "") + ".")
    look = md.get("lookback")
    out.append(f"Lookback: {look or 'each search’s own window'}. Pace plan: {md.get('pace') or 'not set'}."
               + (f" Calibration focus: {'; '.join(md['fuzzy'])}." if md.get("fuzzy") else ""))
    return out


# ---- Switching and Keep-up (built 2026-11-18; the user tests Keep-up later) ----------------------------------------
CADENCE_DAYS = {"daily": 1, "twice-weekly": 3.5, "weekly": 7}
FULL_ROUND_DAYS = 7  # Keep-up: the full round runs weekly (decided 2026-11-18); digests in between


def cadence_days(cadence):
    """Interval in days for a cadence: daily, twice-weekly, weekly or every-<N>-days."""
    if cadence in CADENCE_DAYS:
        return CADENCE_DAYS[cadence]
    m = re.match(r"^every-(\d+)-days$", cadence or "")
    if m:
        return int(m.group(1))
    raise SystemExit("cadence: daily, twice-weekly, weekly or every-<N>-days")


def window_days(cadence):
    """Keep-up search window: the cadence interval rounded up, plus one day of overlap so nothing falls through."""
    return math.ceil(cadence_days(cadence)) + 1


def set_mode(P, a):
    md = mode(P)
    if a.mode:
        if a.mode != md.get("mode"):
            md.setdefault("history", []).append({"mode": md.get("mode"), "until": dt.date.today().isoformat()})
            md["since"] = dt.date.today().isoformat()
        md["mode"] = a.mode
    if a.cadence:
        cadence_days(a.cadence)
        md["cadence"] = a.cadence
    if md.get("mode") == "keep-up" and not md.get("cadence"):
        raise SystemExit("Keep-up needs a cadence: --cadence daily | twice-weekly | weekly | every-<N>-days")
    if a.builder is not None:
        md["builder"] = a.builder == "on"
    if a.asked:
        md["last_asked"] = dt.date.today().isoformat()
        if a.ask_again_days:
            md["ask_again"] = (dt.date.today() + dt.timedelta(days=a.ask_again_days)).isoformat()
    save_mode(P, md)
    print(json.dumps(md, indent=1, ensure_ascii=False))
    print("Rebuild the search links for the new windows: python engine/searches.py")


def last_full_round(P):
    rs = metrics.done(metrics.load(P))
    return to_date(rs[-1].get("date")) if rs else None


def due_text(P):
    md = mode(P)
    if md.get("mode") != "keep-up":
        return "Catch-up: every round is a full round (review, calibration, re-screen, metrics, report)."
    last = last_full_round(P)
    days = (dt.date.today() - last).days if last else None
    if days is None or days >= FULL_ROUND_DAYS:
        return (f"FULL ROUND DUE: the last full round was {last or 'never'}"
                f"{f' ({days} days ago)' if days is not None else ''}. Run the whole round this time.")
    return (f"Digest only: the last full round was {last} ({days} days ago); the next is due "
            f"{(last + dt.timedelta(days=FULL_ROUND_DAYS)).isoformat()}. After triage: modes.py digest <run.json>.")


def due(P):
    print(due_text(P))


def digest(P, a):
    """Keep-up check-in digest: what's new in this run, what was kept, what's waiting, what to act on.

    Writes 2-reports/digest-<date>.md; earlier digests move to 2-reports/archive/ (folder hygiene)."""
    run_path = Path(a.run)
    d = read_json(run_path)
    rows_ = [x for x in d.get("listings", []) if not str(x.get("status", "")).startswith(("invalid", "duplicate"))]
    skipped = [x for x in rows_ if str(x.get("status", "")).lower().startswith(ALREADY)]
    auto = [x for x in rows_ if str(x.get("status", "")).lower() == "auto dq"]
    shown = [x for x in rows_ if x not in skipped and x not in auto]
    keeps = [x for x in shown if x.get("decision") in ("keep", "maybe")]
    waiting = [x for x in shown if not x.get("decision")]
    overruled = [x for x in shown if x.get("decision") and likely_call(x.get("likely")) not in (None, "hedge")
                 and likely_call(x.get("likely")) != ("keep" if x["decision"] in ("keep", "maybe") else "dq")]
    new_cases = [x for x in shown if likely_call(x.get("likely")) == "hedge"]

    def line(x):
        link = x.get("url") or x.get("find")
        job = f"{x.get('company', '')}: {x.get('title', '')}"
        return (f"- [{job}]({link})" if link else f"- {job}") + (f" · {x['location']}" if x.get("location") else "") \
            + (f" · {x['reason']}" if x.get("reason") else "")

    today = dt.date.today().isoformat()
    out = [f"# Keep-up digest ({today})\n",
           f"Search run: {d.get('search', '?')} ({d.get('date', '?')}). {len(rows_)} cards: {len(skipped)} already "
           f"decided, {len(auto)} ruled out by rules, {len(shown)} shown to you.\n",
           f"**{due_text(P)}**\n",
           f"## Kept ({len(keeps)})\n", *(map(line, keeps) if keeps else ["Nothing kept this time."]), "",
           f"## Waiting for your call ({len(waiting)})\n", *(map(line, waiting) if waiting else ["None."]), "",
           f"## New kinds of cases for calibration ({len(new_cases) + len(overruled)})\n",
           "Cards the agent hedged on, and cards where you overruled its call. Only these get calibration questions.\n",
           *(map(line, new_cases + overruled) if new_cases or overruled else ["None: the rules covered everything."]),
           "", "## To act on\n",
           "- Saves: export the PDFs of the kept jobs (Job Tracker → Saved) before the next full round.",
           "- Applications: see [apply-queue.md](apply-queue.md) for what to apply to next.", ""]
    path = P.reports / f"digest-{today}.md"
    for old in P.reports.glob("digest-*.md"):
        if old != path:
            (P.reports / "archive").mkdir(exist_ok=True)
            shutil.move(str(old), str(P.reports / "archive" / old.name))
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {P.rel(path)}: {len(keeps)} kept, {len(waiting)} waiting, {len(new_cases) + len(overruled)} for calibration")


def with_mode(d, m):
    """Copy of a run record with "mode" placed right after "round" (keeps the files readable)."""
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == "round":
            out["mode"] = m
    out.setdefault("mode", m)
    return out


def tag(P):
    m = mode(P).get("mode", "catch-up")
    n = 0
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_run(f)
        if "mode" not in d:
            write_json(f, with_mode(d, m), indent=1)
            n += 1
    mm = metrics.load(P)
    k = 0
    for r in mm["rounds"]:
        if "mode" not in r:
            r["mode"] = m
            k += 1
    write_json(P.metrics, mm, indent=1)
    print(f"Tagged {n} search-run files and {k} metrics rounds as {m}.")


def main():
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: otherwise the subcommand's default (None) overwrites a --data given before the subcommand.
    common.add_argument("--data", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("signals", "tag", "due", "progress"):
        sub.add_parser(c, parents=[common])
    s = sub.add_parser("setup", parents=[common], help="record the Catch-up setup interview's answers")
    s.add_argument("--goal", type=int, help="listings to process to clear the backlog (0 = no goal)")
    s.add_argument("--lookback", help="week, month, any, <N>d, or default (each search's own window)")
    s.add_argument("--pace", help='free text, e.g. "3 sessions a week, about 90 minutes each"')
    s.add_argument("--fuzzy", help="what still feels fuzzy, separated by semicolons (calibration aims there first)")
    s = sub.add_parser("set", parents=[common], help="switch mode, set cadence or builder, record a switch prompt")
    s.add_argument("--mode", choices=("catch-up", "keep-up"))
    s.add_argument("--cadence", help="daily, twice-weekly, weekly or every-<N>-days (Keep-up)")
    s.add_argument("--builder", choices=("on", "off"))
    s.add_argument("--asked", action="store_true", help="record that the user was asked about switching today")
    s.add_argument("--ask-again-days", type=int, dest="ask_again_days")
    s = sub.add_parser("digest", parents=[common], help="Keep-up check-in digest from a triaged run file")
    s.add_argument("run")
    a = ap.parse_args()
    P = Paths(getattr(a, "data", None))
    if a.cmd == "progress":
        print("\n".join(progress_md(P)) or "Not in Catch-up: no progress section.")
    elif a.cmd in ("setup", "set", "digest"):
        {"setup": setup, "set": set_mode, "digest": digest}[a.cmd](P, a)
    else:
        {"signals": signals, "tag": tag, "due": due}[a.cmd](P)


if __name__ == "__main__":
    main()
