"""Search funnel metrics: how many jobs each round sifted, and how many are still under consideration.

Usage:  python engine/metrics.py --round N [--data my-data]      record round N, then print the tables
        python engine/metrics.py [--data my-data]                print the tables only
        python engine/metrics.py --round N --event <stage> [--note ...] [--at ISO]
                                                                 log a timing event (capture, triage, export, review,
                                                                 savesync); see "Time per stage" below

Run at the end of every round, after the re-screen and before build_report.py (the report shows the table).

Stages (each job counted once, by normalized company + title, across every search run):
  1. Job listings processed    unique cards from pasted or filmed search results (6-system/search-runs/*.json,
                               each tagged with "round"); same-day duplicates and invalid runs are skipped.
                               A run's "unrecorded_cards" (seen but never written down as rows) count here too.
                               Plus every saved posting that never showed up as a card (alert and direct saves,
                               backlog sweeps), in the round it arrived (added 2026-11-25: without them a round
                               of direct saves had deep-fit reviews with no listings behind them).
  2. Triage decision           cards the user decided in triage (keep / maybe / DQ). Auto-DQs by rule and cards
                               skipped because they were already Saved or decided earlier are not counted.
  3. PDF saved                 new job PDFs extracted this round (6-system/jobs + removed.json tombstones, by job ID);
                               "from triage" vs "direct" (alerts, other saves) is shown when known.
  4. Ranked                    jobs on the ranked list at the end of the round (current jobs not marked X or ?).

Phone triage (added 2026-11-26): saves made straight from LinkedIn alerts on a phone, judged on LinkedIn's match
signal alone, with no result cards captured. A run file with "triage_type": "phone" lists them in "saved_job_ids".
How many listings were seen and decided behind them is unknown, so they are counted apart ("phone" in each round's
funnel entry) and left out of the known funnel: totals() (and with it the per-100 numbers and the LinkedIn project
images) leaves them out of every stage, qualified targets included. The round table shows their stages 1-2 as
unknown. A phone save that matches a search card already counted is that card's listing, as for a direct save.

Writes 6-system/metrics.json: one entry per round. Each entry keeps the set of job IDs seen so far, so the next
round's "PDF saved" is an exact difference. Rounds 1-6 were backfilled on 2026-11-17 from the run files and the
round summaries in the user's own project notes (marked "backfilled"; R2 and R3 ranked counts are approximate).
"""
import argparse
import datetime as dt
import json

from paths import Paths, latest_reviews, read_json, write_json, tombstones
from triaged import key

# Display names for the four stages (decided 2026-11-18; also used on the LinkedIn project images).
LABELS = ("Job listings processed", "LinkedIn baseline match", "Agent deep-fit review", "Qualified targets")
DECIDED_STATUSES =("", "candidate", "check location", "viewed")


def saved_postings(P):
    """Every saved posting ever extracted, current or removed: {job ID: company + title key, or None if nameless}."""
    out = {}
    for f in P.jobs.glob("*.json"):
        j = read_json(f)
        if isinstance(j, dict) and isinstance(j.get("job_id"), str):
            out[j["job_id"]] = j
    removed = tombstones(P.removed)
    for t in removed if isinstance(removed, list) else []:
        out.setdefault(t["job_id"], t)
    return {jid: (key(str(j.get("company") or ""), str(j.get("title") or ""))
                  if (j.get("company") or j.get("title")) else None) for jid, j in out.items()}


def phone_saves(P):
    """Job IDs listed by phone-triage run files ("triage_type": "phone", "saved_job_ids"). See the module docstring."""
    out = set()
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_json(f)
        if isinstance(d, dict) and d.get("triage_type") == "phone":
            out |= {i for i in d.get("saved_job_ids") or [] if isinstance(i, str)}
    return out


def snapshot(r):
    """A round's usable job-ID snapshot as a set, or None. Non-text IDs are ignored; a list that held only such IDs
    counts as missing. An empty list is a real snapshot: the round was recorded with no saved jobs yet."""
    raw = r.get("job_ids")
    if not isinstance(raw, list):
        return None
    good = {i for i in raw if isinstance(i, str)}
    return good if (good or not raw) else None


def saves_by_round(P, rounds):
    """Which round each saved posting arrived in, from the job-ID snapshots metrics.json keeps per round.

    Returns ({round: [job IDs]}, early, first): a snapshot round's new IDs are its snapshot minus the previous one.
    The first snapshot also holds every save from the backfilled rounds before it, which kept no IDs; those are
    returned as `early` (attributed to `first`), and funnel_from_runs spreads their count back over the backfilled
    rounds. IDs in no snapshot go to the latest recorded round when it kept no usable snapshot (they arrived by
    then, so they must stay in the totals), otherwise to the round after it (a round still in progress).
    A snapshot's non-text IDs are ignored; a snapshot with nothing usable in it counts as missing."""
    snaps = [(r["round"], snapshot(r)) for r in rounds if snapshot(r) is not None]
    snaps.sort(key=lambda s: s[0])
    ids, out, prev = set(saved_postings(P)), {}, None
    early, first = set(), None
    for rnd, snap in snaps:
        if prev is None:
            first, early = rnd, snap & ids
        else:
            out[rnd] = sorted((snap - prev) & ids)
        prev = snap if prev is None else prev | snap
    last = max([r["round"] for r in rounds if isinstance(r.get("round"), int)] or [0])
    last_done = max([r["round"] for r in rounds if r.get("ranked_end") is not None] or [0])
    rest = ids - (prev or set())
    if rest:
        if first is None:
            # No snapshots at all: treat every save as early, landing in the last recorded round. With no recorded
            # round either, they wait for the round in progress (or round 1), never a round 0.
            first, early = last_done or max(last, 1), rest
        else:
            last_snap = snaps[-1][0]
            target = last_done if last_done > last_snap else max(last_done, last_snap) + 1
            out.setdefault(target, []).extend(sorted(rest))
    return out, sorted(early), first


def share_early(n, rounds, first):
    """How many of the `n` direct saves from before the first snapshot each backfilled round gets: {round: count}.
    Whatever isn't handed out stays with the first snapshot round.

    Each round's recorded direct count is pdfs_new - pdfs_from_triage; a round without that split gets none. When
    enough saves are left after deduplication, every backfilled round gets its recorded count. When fewer are left
    (some direct saves later showed up as search cards, and without job IDs there is no telling whose), the rounds,
    the first snapshot round included, share them in proportion to their recorded counts, largest remainders first
    and earlier rounds first on a tie."""
    known = {}
    for b in rounds:
        if b["round"] > first:
            continue
        try:
            known[b["round"]] = max(0, int(b["pdfs_new"]) - int(b["pdfs_from_triage"]))
        except (KeyError, TypeError, ValueError):
            continue
    total = sum(known.values())
    if n >= total or not total:
        share = dict(known)
    else:
        share = {r: n * k // total for r, k in known.items()}
        by_remainder = sorted(known, key=lambda r: (-(n * known[r] % total), r))
        for r in by_remainder[:n - sum(share.values())]:
            share[r] += 1
    return {r: c for r, c in share.items() if r != first and c}


def funnel_from_runs(P):
    """Stages 1-2 per round, deduplicated across all search runs and saves in round order.

    Job listings processed = unique search-result cards (plus a run's unrecorded_cards) + saved postings that never
    showed up as a card ("direct": alert and direct saves, backlog sweeps). A save whose company + title matches a
    card already counted adds nothing; a second posting with the same company + title counts (a card stands for one
    posting). A card row that carries a saved posting's job ID (written by triaged.py match-saved) is that posting
    even when the titles differ (a card title cut short, a PDF title with extra words), so the pair counts once.
    Each round's entry also carries "cards" and "direct". Phone-triage saves (see the module docstring) are counted
    in "phone" (their IDs in "phone_ids") instead of "direct" and "processed": the listings behind them are unknown."""
    runs = []
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_json(f)
        if "round" in d:
            runs.append((d["round"], d.get("date", ""), f.name, d))
    runs.sort(key=lambda r: (r[0], r[1], r[2]))
    rounds = [r for r in load(P).get("rounds", []) if isinstance(r, dict) and isinstance(r.get("round"), int)]
    keys = saved_postings(P)
    saves, early, first = saves_by_round(P, rounds)
    seen, claimed, decided, per = set(), set(), set(), {}
    counted = set()  # job IDs of saved postings already counted, as a card or as a direct save
    phone = phone_saves(P)
    entry = lambda rnd: per.setdefault(rnd, {"processed": 0, "cards": 0, "direct": 0, "decided": 0, "keep": 0,
                                             "maybe": 0, "dq": 0, "runs": [], "phone": 0, "phone_ids": []})

    def add_saves(rnd, jids):
        n = 0
        for jid in jids:
            if jid in counted:  # a card row linked to this job ID already counted it
                continue
            counted.add(jid)
            k = keys.get(jid)
            if k is not None and k in seen and k not in claimed:
                claimed.add(k)  # the card already counted this posting
                continue
            if k is not None:
                seen.add(k)
                claimed.add(k)
            if jid in phone:  # phone triage: counted apart, never as a listing processed
                entry(rnd)["phone"] += 1
                entry(rnd)["phone_ids"].append(jid)
                continue
            n += 1
        entry(rnd)["direct"] += n
        entry(rnd)["processed"] += n
        return n

    by_round = {}
    for run in runs:
        by_round.setdefault(run[0], []).append(run)
    for rnd in sorted(set(by_round) | set(saves) | ({first} if first is not None else set())):
        for _, _, name, d in by_round.get(rnd, []):
            r = entry(rnd)
            r["runs"].append(name)
            r["processed"] += d.get("unrecorded_cards", 0)
            r["cards"] += d.get("unrecorded_cards", 0)
            for x in d.get("listings", []):
                s = x.get("status") or ""
                if s == "invalid run" or s.startswith("duplicate"):
                    continue
                # Deliberate (code reviews, 2026-11-25): a card is one listing per company + title, so the same
                # posting met again in a later search, or under another city's card, counts once. Search cards rarely
                # carry a job ID, and LinkedIn shows one role in several cities as separate cards; counting those
                # separately would inflate "listings processed". Linked job IDs refine it below.
                k = key(x.get("company", ""), x.get("title", ""))
                jid = x.get("job_id")
                jid = jid if isinstance(jid, str) and jid in keys else None  # linked to a saved posting
                if jid is not None and jid in counted:
                    seen.add(k)  # the same posting under another title: already counted
                    claimed.add(k)
                else:
                    new = k not in seen
                    if new:
                        seen.add(k)
                        r["processed"] += 1
                        r["cards"] += 1
                    # This card stands for the linked posting unless its title already stands for another saved
                    # posting (then the save counts itself, as a second posting with the same title).
                    if jid is not None and (new or k not in claimed):
                        counted.add(jid)
                        claimed.add(k)
                        if keys[jid] is not None:
                            seen.add(keys[jid])
                            claimed.add(keys[jid])
                dec = x.get("decision")
                if dec in ("keep", "maybe", "dq") and s in DECIDED_STATUSES and k not in decided:
                    decided.add(k)
                    r["decided"] += 1
                    r["maybe" if x.get("note_maybe") else dec] += 1  # maybes later saved still count as maybes
        if rnd == first:
            # Saves from before the first snapshot: deduplicate against every card up to here, then share them
            # between the backfilled rounds and this one by their recorded direct counts (see share_early).
            n = add_saves(rnd, early)
            for b, give in share_early(n, rounds, rnd).items():
                for k_ in ("direct", "processed"):
                    entry(b)[k_] += give
                    entry(rnd)[k_] -= give
        add_saves(rnd, saves.get(rnd, []))
    return per


def ranked_ids(P):
    """Job IDs of current jobs on the ranked list (tier not X, ? or missing); see current_state for where tiers come from."""
    jobs = [read_json(f) for f in P.jobs.glob("*.json")]
    reviews = latest_reviews(P)
    tier = lambda j: (reviews[j["job_id"]][0] if j["job_id"] in reviews else j.get("review") or {}).get("tier")
    held = lambda j: (reviews[j["job_id"]][0] if j["job_id"] in reviews else j.get("review") or {}).get("held")
    # A job held for calibration (build_report.py) isn't on the ranked list until the calibration decides it.
    return {j["job_id"] for j in jobs if tier(j) not in ("X", "?", None) and not held(j)}


def current_state(P):
    jobs = [read_json(f) for f in P.jobs.glob("*.json")]
    removed = tombstones(P.removed)
    removed = removed if isinstance(removed, list) else removed.get("removed", [])
    # Removed jobs stay in the set on purpose: "PDFs saved" counts unique postings ever reviewed, so a job that is
    # removed and later saved again (same job ID) isn't counted twice in the cumulative funnel.
    ids = {j["job_id"] for j in jobs} | {r["job_id"] for r in removed if r.get("job_id")}
    # Tiers come from the review files, not the job records: metrics runs before build_report.py in a round, and
    # only the report copies a round's new or changed reviews into the records. A job with no review entry falls
    # back to its record's copy (data written before the review files existed).
    return ids, len(ranked_ids(P))


def load(P):
    return read_json(P.metrics, {"rounds": []})


def done(m):
    """Recorded rounds only: a round still in progress has timing events but no ranked_end yet."""
    return [r for r in m["rounds"] if r.get("ranked_end") is not None]


def record(P, rnd):
    m = load(P)
    ids, ranked = current_state(P)
    entry = next((r for r in m["rounds"] if r["round"] == rnd), None)
    earlier_ids = set().union(*[snapshot(r) or set() for r in m["rounds"] if r["round"] < rnd])
    late = any(r["round"] > rnd and (snapshot(r) is not None or r.get("ranked_end") is not None) for r in m["rounds"])
    if late:
        # A later round is already recorded (with or without a usable snapshot). Every job ID known today that
        # this round's snapshot lacks arrived after it, so writing today's IDs, counts and date here would move
        # later rounds' saves into this round.
        if entry is not None and entry.get("ranked_end") is not None:
            print(f"Round {rnd} is already recorded and a later round builds on it: left as it is.")
            return m
        print(f"Round {rnd} is recorded after a later round: jobs saved since the round before it stay with the "
              f"rounds that recorded them, so this round adds no saved jobs.")
        ids = set(earlier_ids)
    # Every ID an earlier round kept, not just the latest earlier snapshot: an ID that dropped out of one snapshot
    # (or rounds listed out of order in a hand-edited file) must not come back as a new save, as in the funnel.
    prev_ids = earlier_ids
    new_ids = sorted(ids - prev_ids)
    if entry is None:
        entry = {"round": rnd}
        m["rounds"].append(entry)
    searches = read_json(P.searches, {})
    if prev_ids or late:  # exact: the difference from the rounds that kept their job IDs (none when late)
        pdfs_new = len(new_ids)
    elif entry.get("pdfs_new") is not None:  # backfilled by hand for this round: keep it
        pdfs_new = entry["pdfs_new"]
    else:
        earlier = [r for r in m["rounds"] if r["round"] < rnd]
        if earlier:  # earlier rounds were backfilled without job IDs: estimate rather than count every job as new
            pdfs_new = max(0, len(ids) - sum(r.get("pdfs_new") or 0 for r in earlier))
            entry["pdfs_new_estimated"] = True
            print(f"Round {rnd}: earlier rounds have no job IDs, so PDFs saved this round is estimated "
                  f"({len(ids)} jobs seen in all - {len(ids) - pdfs_new} counted in earlier rounds = {pdfs_new}).")
        else:  # the first round: every job is new
            pdfs_new = len(new_ids)
    entry.update({"date": dt.date.today().isoformat(), "source": "recorded by metrics.py",
                  "mode": (searches.get("mode") or {}).get("mode", "catch-up"),  # triage mode (docs/how-it-works.md -> Triage modes)
                  "pdfs_new": pdfs_new, "ranked_end": ranked, "job_ids": sorted(ids)})
    # File-time events (capture, export): replace earlier file-time events so re-recording doesn't double them.
    ev = [e for e in entry.get("events", []) if not (e.get("note") or "").startswith("file time:")]
    entry["events"] = sorted(ev + (file_events(P, rnd, new_ids) if prev_ids else []), key=lambda e: e["t"])
    m["rounds"].sort(key=lambda r: r["round"])
    write_json(P.metrics, m, indent=1)
    return m


def table(P):
    """Markdown funnel table: per round and cumulative."""
    m, per = load(P), funnel_from_runs(P)
    rows = []
    cum = {"processed": 0, "decided": 0, "pdfs": 0}
    out = [f"| Round | {LABELS[0]} (search cards + direct saves) | {LABELS[1]} (keep / maybe / DQ) "
           f"| {LABELS[2]} (from triage + direct) "
           f"| {LABELS[3]} at round end |", "|---|---|---|---|---|"]
    for r in done(m):
        f = per.get(r["round"], {"processed": 0, "decided": 0, "keep": 0, "maybe": 0, "dq": 0})
        cum["processed"] += f["processed"]
        cum["decided"] += f["decided"]
        cum["pdfs"] += r.get("pdfs_new", 0)
        split = (f" ({r['pdfs_from_triage']} + {r['pdfs_new'] - r['pdfs_from_triage']})"
                 if r.get("pdfs_from_triage") is not None else "")
        approx = "≈" if r.get("ranked_approx") else ""
        dec = f"{f['decided']} ({f['keep']} / {f['maybe']} / {f['dq']})" if f["decided"] else "–"
        proc = (f"{f['processed']} ({f.get('cards', 0)} + {f['direct']})" if f.get("direct")
                else str(f["processed"] or "–"))
        if f.get("phone"):  # phone triage: the listings seen and decided behind these saves are unknown
            proc = f"{proc} + unknown (phone triage)" if f["processed"] else "unknown (phone triage)"
            dec = f"{dec} + unknown (phone triage)" if f["decided"] else "unknown (phone triage)"
            split = f"{split} (incl. {f['phone']} phone triage)"
        out.append(f"| {r['round']} | {proc} | {dec} | {r.get('pdfs_new', 0)}{split} "
                   f"| {approx}{r['ranked_end']} |")
        rows.append(r)
    if rows:
        t = totals(P)
        pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "–"
        if t["phone_pdfs"]:
            out.append(f"| **Total, known funnel** (leaves out phone triage) | **{t['processed']}** | **{t['decided']}** "
                       f"| **{t['pdfs']}** | **{t['ranked']}** (now) |")
            out.append(f"| Phone triage (listings unknown) | unknown | unknown | {t['phone_pdfs']} "
                       f"| {t['phone_ranked']} (now) |")
        else:
            out.append(f"| **Total** | **{t['processed']}** | **{t['decided']}** | **{t['pdfs']}** "
                       f"| **{t['ranked']}** (now) |")
        out.append("")
        out.append(f"Conversion so far: {pct(t['decided'], t['processed'])} of job listings processed reached a "
                   f"LinkedIn baseline match (your triage call); the agent's deep-fit review covered "
                   f"{pct(t['pdfs'], t['decided'])} as many jobs as that stage (it also takes alert and direct saves); "
                   f"{pct(t['ranked'], t['pdfs'])} of deep-fit reviews are qualified targets now. Out of "
                   f"{t['processed']} job listings, {t['ranked']} are qualified targets "
                   f"({pct(t['ranked'], t['processed'])}).")
        if t["phone_pdfs"]:
            out.append("")
            out.append(f"Phone triage: {t['phone_pdfs']} saves made on a phone from LinkedIn alerts, judged on LinkedIn's "
                       f"match signal alone; how many listings were seen behind them is unknown. They are left out of "
                       f"the known funnel and the per-100 numbers; {t['phone_ranked']} of them are qualified targets now.")
    return "\n".join(out)


def totals(P):
    """Cumulative stage counts after the latest recorded round."""
    m, per = load(P), funnel_from_runs(P)
    rs = done(m)
    if not rs:
        return None
    # The known funnel: phone-triage saves (unknown listings behind them) are left out of every stage, qualified
    # targets included, and reported apart. Qualified targets are the last recorded round's, less the phone saves
    # on the ranked list today.
    phone = set().union(*[set(per.get(r["round"], {}).get("phone_ids", [])) for r in rs])
    phone_ranked = len(phone & ranked_ids(P)) if phone else 0
    return {"processed": sum(per.get(r["round"], {}).get("processed", 0) for r in rs),
            "decided": sum(per.get(r["round"], {}).get("decided", 0) for r in rs),
            "pdfs": sum(r.get("pdfs_new", 0) for r in rs) - len(phone),
            "ranked": rs[-1]["ranked_end"] - phone_ranked, "round": rs[-1]["round"],
            "phone_pdfs": len(phone), "phone_ranked": phone_ranked, "phone_ids": sorted(phone)}


def funnel_svg(P, path):
    """Overall funnel as a static SVG (no dependencies). Light background so it reads in any Markdown viewer."""
    t = totals(P)
    if not t:
        return None
    stages = [(LABELS[0], t["processed"], "#B5D4F4"), (LABELS[1], t["decided"], "#378ADD"),
              (LABELS[2], t["pdfs"], "#185FA5"), (LABELS[3], t["ranked"], "#0C447C")]
    W, left, top, bar, gap, maxw = 680, 190, 44, 26, 18, 380
    H = top + len(stages) * (bar + gap) + (32 if t["phone_pdfs"] else 10)
    top_n = max(v for _, v, _ in stages) or 1
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img">',
         f'<title>Search funnel after round {t["round"]}</title>',
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         f'<text x="16" y="26" font-size="15" font-weight="600" fill="#0B0B0B">Search funnel after round {t["round"]} '
         f'(cumulative)</text>']
    for i, (label, v, color) in enumerate(stages):
        y = top + i * (bar + gap)
        w = max(2, round(v / top_n * maxw))
        s += [f'<text x="{left - 10}" y="{y + bar / 2 + 5}" font-size="13" fill="#52514E" text-anchor="end">{label}</text>',
              f'<rect x="{left}" y="{y}" width="{w}" height="{bar}" rx="4" fill="{color}"/>',
              f'<text x="{left + w + 8}" y="{y + bar / 2 + 5}" font-size="13" fill="#0B0B0B">'
              f'<tspan font-weight="600">{v}</tspan></text>']  # no % on bars: the bar length shows the share
    if t["phone_pdfs"]:
        s.append(f'<text x="16" y="{H - 14}" font-size="12" fill="#52514E">Leaves out {t["phone_pdfs"]} phone-triage '
                 f'saves ({t["phone_ranked"]} qualified targets now): the listings behind them are unknown.</text>')
    s.append("</svg>")
    path.write_text("\n".join(s), encoding="utf-8")
    return path


# ---- Time per stage (added 2026-11-18) ------------------------------------------------------------------------
# Each round keeps a list of timestamped events. Active time per stage = the sum of gaps between consecutive events
# of that stage, ignoring gaps longer than BREAK_MIN (a break, not work). Events come from:
#   - Claude, at each stage boundary and each triage batch: metrics.py --round N --event <stage> [--note ...]
#   - file times, added when the round is recorded: pasted search-result files (capture) and the new PDFs (export)
#   (build_report.py does not log events: reports are often rebuilt long after the round.)
# A round's "timing_minutes" (set by hand, e.g. the round 7 backfill) overrides the computed value per stage.
STAGES = {"capture": "Capture search results", "triage": "Triage (your calls)", "export": "Save + PDF export",
          "review": "Agent review, calibration, re-screen, report", "savesync": "Save-sync check"}
BREAK_MIN = 30


def add_event(P, rnd, stage, note=None, at=None):
    if stage not in STAGES:
        raise SystemExit(f"Unknown stage {stage}: use one of {', '.join(STAGES)}")
    m = load(P)
    entry = next((r for r in m["rounds"] if r["round"] == rnd), None)
    if entry is None:
        entry = {"round": rnd, "ranked_end": None}
        m["rounds"].append(entry)
        m["rounds"].sort(key=lambda r: r["round"])
    t = at or dt.datetime.now().isoformat(timespec="seconds")
    entry.setdefault("events", []).append({"t": t, "stage": stage, **({"note": note} if note else {})})
    write_json(P.metrics, m, indent=1)


def file_events(P, rnd, new_ids):
    """Capture and export events from file save times (pasted search results; PDFs of this round's new jobs)."""
    ev = []
    for f in P.search_runs.glob("*.json"):
        d = read_json(f)
        if d.get("round") != rnd or not d.get("source"):
            continue
        src = P.data / d["source"].split(" (")[0]
        if src.exists():
            ev.append({"t": dt.datetime.fromtimestamp(src.stat().st_mtime).isoformat(timespec="seconds"),
                       "stage": "capture", "note": f"file time: {src.name}"})
    for jid in new_ids:
        jf = P.jobs / f"{jid}.json"
        if not jf.exists():
            continue
        for rel in read_json(jf).get("source_files", []):
            pdf = P.data / rel
            if pdf.exists() and pdf.suffix.lower() == ".pdf" and P.job_pdfs in pdf.parents:
                ev.append({"t": dt.datetime.fromtimestamp(pdf.stat().st_mtime).isoformat(timespec="seconds"),
                           "stage": "export", "note": f"file time: {pdf.name}"})
    return ev


def stage_minutes(entry):
    """Active minutes per stage for one round (manual timing_minutes win)."""
    times = {}
    for e in entry.get("events", []):
        try:  # a hand-edited or half-written event is skipped, never a crash
            times.setdefault(e["stage"], []).append(dt.datetime.fromisoformat(e["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    out = {}
    for s, ts in times.items():
        ts.sort()
        out[s] = round(sum(g for g in ((b - a).total_seconds() / 60 for a, b in zip(ts, ts[1:])) if g <= BREAK_MIN))
    out.update(entry.get("timing_minutes", {}))
    return {s: out[s] for s in STAGES if s in out}


def hm(minutes):
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def timing_table(P):
    """Markdown: active time per stage for each round that has timing, and minutes per 100 job listings."""
    m, per = load(P), funnel_from_runs(P)
    rows = [(r, stage_minutes(r)) for r in m["rounds"]]
    rows = [(r, s) for r, s in rows if s]
    if not rows:
        return None
    out = ["| Round | " + " | ".join(STAGES.values()) + " | Total | Per 100 job listings |",
           "|---|" + "---|" * (len(STAGES) + 2)]
    for r, s in rows:
        total = sum(s.values())
        n = per.get(r["round"], {}).get("processed", 0)
        rate = hm(round(total * 100 / n)) if n else "–"
        cells = [hm(s[k]) if k in s else "–" for k in STAGES]
        out.append(f"| {r['round']} | " + " | ".join(cells) + f" | **{hm(total)}** | {rate} |")
    notes = [f"Round {r['round']}: {r['timing_note']}" for r, _ in rows if r.get("timing_note")]
    out.append("")
    out.append("Active time only: gaps over 30 minutes count as breaks. " + " ".join(notes))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int)
    ap.add_argument("--event", choices=list(STAGES), help="log a timing event for --round (stage boundary or batch)")
    ap.add_argument("--note", default=None)
    ap.add_argument("--at", default=None, help="ISO time for the event (default: now)")
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    P = Paths(args.data)
    if args.event:
        if not args.round:
            raise SystemExit("--event needs --round")
        add_event(P, args.round, args.event, args.note, args.at)
        print(f"logged {args.event} for round {args.round}")
        return
    if args.round:
        record(P, args.round)
    print(table(P))
    tt = timing_table(P)
    if tt:
        print("\n" + tt)


if __name__ == "__main__":
    main()
