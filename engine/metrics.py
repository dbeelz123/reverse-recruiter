"""Search funnel metrics: how many jobs each round sifted, and how many are still under consideration.

Usage:  python engine/metrics.py --round N [--data my-data]      record round N, then print the tables
        python engine/metrics.py [--data my-data]                print the tables only
        python engine/metrics.py --round N --event <stage> [--note ...] [--at ISO]
                                                                 log a timing event (capture, triage, export, review,
                                                                 savesync); see "Time per stage" below

Run at the end of every round, after the re-screen and before build_report.py (the report shows the table).

Stages (each job counted once, by normalized company + title, across every search run):
  1. Search results processed  unique cards from pasted or filmed search results (6-system/search-runs/*.json,
                               each tagged with "round"); same-day duplicates and invalid runs are skipped.
                               A run's "unrecorded_cards" (seen but never written down as rows) count here too.
  2. Triage decision           cards the user decided in triage (keep / maybe / DQ). Auto-DQs by rule and cards
                               skipped because they were already Saved or decided earlier are not counted.
  3. PDF saved                 new job PDFs extracted this round (6-system/jobs + removed.json tombstones, by job ID);
                               "from triage" vs "direct" (alerts, other saves) is shown when known.
  4. Ranked                    jobs on the ranked list at the end of the round (current jobs not marked X or ?).

Writes 6-system/metrics.json: one entry per round. Each entry keeps the set of job IDs seen so far, so the next
round's "PDF saved" is an exact difference. Rounds 1-6 were backfilled on 2026-11-17 from the run files and the
round summaries in docs/PLAN.md (marked "backfilled"; R2 and R3 ranked counts are approximate).
"""
import argparse
import datetime as dt
import json

from paths import Paths, read_json, write_json
from triaged import key

# Display names for the four stages (decided 2026-11-18; also used on the LinkedIn project images).
LABELS = ("Job listings processed", "LinkedIn baseline match", "Agent deep-fit review", "Qualified targets")
DECIDED_STATUSES =("", "candidate", "check location", "viewed")


def funnel_from_runs(P):
    """Stages 1-2 per round from the search-run files, deduplicated across all runs in round order."""
    runs = []
    for f in sorted(P.search_runs.glob("*.json")):
        d = read_json(f)
        if "round" in d:
            runs.append((d["round"], d.get("date", ""), f.name, d))
    runs.sort(key=lambda r: (r[0], r[1], r[2]))
    seen, decided, per = set(), set(), {}
    for rnd, _, name, d in runs:
        r = per.setdefault(rnd, {"processed": 0, "decided": 0, "keep": 0, "maybe": 0, "dq": 0, "runs": []})
        r["runs"].append(name)
        r["processed"] += d.get("unrecorded_cards", 0)
        for x in d.get("listings", []):
            s = x.get("status") or ""
            if s == "invalid run" or s.startswith("duplicate"):
                continue
            k = key(x.get("company", ""), x.get("title", ""))
            if k not in seen:
                seen.add(k)
                r["processed"] += 1
            dec = x.get("decision")
            if dec in ("keep", "maybe", "dq") and s in DECIDED_STATUSES and k not in decided:
                decided.add(k)
                r["decided"] += 1
                r["maybe" if x.get("note_maybe") else dec] += 1  # maybes later saved still count as maybes
    return per


def current_state(P):
    jobs = [read_json(f) for f in P.jobs.glob("*.json")]
    removed = read_json(P.removed, [])
    removed = removed if isinstance(removed, list) else removed.get("removed", [])
    ids = {j["job_id"] for j in jobs} | {r["job_id"] for r in removed if r.get("job_id")}
    ranked = sum(1 for j in jobs if (j.get("review") or {}).get("tier") not in ("X", "?", None))
    return ids, ranked


def load(P):
    return read_json(P.metrics, {"rounds": []})


def done(m):
    """Recorded rounds only: a round still in progress has timing events but no ranked_end yet."""
    return [r for r in m["rounds"] if r.get("ranked_end") is not None]


def record(P, rnd):
    m = load(P)
    ids, ranked = current_state(P)
    prev = [r for r in m["rounds"] if r["round"] < rnd and r.get("job_ids")]
    prev_ids = set(prev[-1]["job_ids"]) if prev else set()
    new_ids = sorted(ids - prev_ids)
    entry = next((r for r in m["rounds"] if r["round"] == rnd), None)
    if entry is None:
        entry = {"round": rnd}
        m["rounds"].append(entry)
    searches = read_json(P.searches, {})
    entry.update({"date": dt.date.today().isoformat(), "source": "recorded by metrics.py",
                  "mode": (searches.get("mode") or {}).get("mode", "catch-up"),  # triage mode (docs/PLAN.md)
                  "pdfs_new": len(new_ids) if prev_ids else entry.get("pdfs_new", len(new_ids)),
                  "ranked_end": ranked, "job_ids": sorted(ids)})
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
    out = [f"| Round | {LABELS[0]} | {LABELS[1]} (keep / maybe / DQ) | {LABELS[2]} (from triage + direct) "
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
        out.append(f"| {r['round']} | {f['processed'] or '–'} | {dec} | {r.get('pdfs_new', 0)}{split} "
                   f"| {approx}{r['ranked_end']} |")
        rows.append(r)
    if rows:
        last = rows[-1]
        pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "–"
        out.append(f"| **Total** | **{cum['processed']}** | **{cum['decided']}** | **{cum['pdfs']}** "
                   f"| **{last['ranked_end']}** (now) |")
        out.append("")
        out.append(f"Conversion so far: {pct(cum['decided'], cum['processed'])} of job listings processed reached a "
                   f"LinkedIn baseline match (your triage call); the agent's deep-fit review covered "
                   f"{pct(cum['pdfs'], cum['decided'])} as many jobs as that stage (it also takes alert and direct saves); "
                   f"{pct(last['ranked_end'], cum['pdfs'])} of deep-fit reviews are qualified targets now. Out of "
                   f"{cum['processed']} job listings, {last['ranked_end']} are qualified targets "
                   f"({pct(last['ranked_end'], cum['processed'])}).")
    return "\n".join(out)


def totals(P):
    """Cumulative stage counts after the latest recorded round."""
    m, per = load(P), funnel_from_runs(P)
    rs = done(m)
    if not rs:
        return None
    return {"processed": sum(per.get(r["round"], {}).get("processed", 0) for r in rs),
            "decided": sum(per.get(r["round"], {}).get("decided", 0) for r in rs),
            "pdfs": sum(r.get("pdfs_new", 0) for r in rs),
            "ranked": rs[-1]["ranked_end"], "round": rs[-1]["round"]}


def funnel_svg(P, path):
    """Overall funnel as a static SVG (no dependencies). Light background so it reads in any Markdown viewer."""
    t = totals(P)
    if not t:
        return None
    stages = [(LABELS[0], t["processed"], "#B5D4F4"), (LABELS[1], t["decided"], "#378ADD"),
              (LABELS[2], t["pdfs"], "#185FA5"), (LABELS[3], t["ranked"], "#0C447C")]
    W, left, top, bar, gap, maxw = 680, 190, 44, 26, 18, 380
    H = top + len(stages) * (bar + gap) + 10
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
        times.setdefault(e["stage"], []).append(dt.datetime.fromisoformat(e["t"]))
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
