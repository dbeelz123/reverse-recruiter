"""Application pipeline: record each job's progress, and build the apply queue and the outcome funnel.

Usage:
  python engine/pipeline.py record <job> <stage> [--date YYYY-MM-DD] [--note "..."] [--next "..."]
  python engine/pipeline.py queue                        # writes 2-reports/apply-queue.md and prints a summary

<job> is a job ID (1234567890, ext-...), a kit folder name, or a word that matches one company (e.g. "acme").
Stages, in order: kit -> applied -> response -> interview -> offer. Also: outreach (a connection was messaged),
hold (an application started and paused; give the reason in --note and what's left in --next),
passed (the user decided not to apply), rejected, withdrawn, closed (the posting closed before they applied).

Where it lives: a "pipeline" block on the job record (6-system/jobs/<id>.json):
  {"status": <latest stage>, "updated": <date>, "stage": <optional detail, e.g. "round 4 on 2026-11-23">,
   "next": <optional next step that overrides the derived one>, "events": [{"date", "stage", "note"}]}
extract.py and build_report.py keep the block; remove_job.py copies it into the tombstone so the funnel keeps it.
Kits are found from 3-applications/*/log.md (archive/ ignored): its job link gives the job, its table gives
"Kit prepared" and "Stretch review". log.md stays the human record; Claude updates both when the user reports a step.
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import Paths, iso_date, read_json, write_json, tombstones, to_date  # noqa: E402

STAGES = ["kit", "applied", "response", "interview", "offer"]
TERMINAL = ["passed", "rejected", "withdrawn", "closed"]
OTHER = ["outreach", "hold"]  # events that don't change the status (hold = started, paused; pair it with --next)
FUNNEL = [("ranked", "Qualified targets"), ("kit", "Kit built"), ("applied", "Applied"),
          ("response", "Employer response"), ("interview", "Interview"), ("offer", "Offer")]
QUEUE_TIERS = ("A", "B")


def load(p, default=None):
    return read_json(Path(p), default)


def md(s):
    return str(s).replace("|", "/").replace("\n", " ")


def kits(P):
    """job_id -> {folder, prepared, stretch} from each kit's log.md table."""
    out = {}
    for log in sorted(P.applications.glob("*/log.md")):
        if log.parent.name == "archive":
            continue
        text = log.read_text(encoding="utf-8")
        m = re.search(r"linkedin\.com/jobs/view/(\d+)", text) or re.search(r"jobs/(ext-[\w-]+)\.json", text)
        if not m:
            continue
        row = lambda name: (re.search(rf"^\| {name} \| *([^|]*?) *\|", text, re.M) or [None, ""])[1].strip(" —-")
        out[m.group(1)] = {"folder": log.parent.name, "prepared": row("Kit prepared"),
                           "stretch": row("Stretch review")}
    return out


def reached(pl, has_kit):
    """Highest funnel stage a job has reached. A rejection after applying counts as a response."""
    stages = {e["stage"] for e in (pl or {}).get("events", [])}
    status = {"interviewing": "interview"}.get((pl or {}).get("status"), (pl or {}).get("status"))  # older records
    if status in STAGES:
        stages.add(status)
    if "rejected" in stages and stages & {"applied", "response", "interview", "offer"}:
        stages.add("response")
    if has_kit:
        stages.add("kit")
    idx = [STAGES.index(s) for s in stages if s in STAGES]
    if idx and max(idx) >= STAGES.index("applied"):
        idx.append(STAGES.index("applied"))
    return max(idx) if idx else -1


def in_progress_count(P):
    """Applications sent and still open (applied or further, not rejected/withdrawn), as published on LinkedIn.
    An offer counts as in progress on purpose: it's still open until accepted or declined, and either outcome is
    recorded as a new status (declining is 'passed'), which takes it out of this count."""
    jobs = [load(f) for f in P.jobs.glob("*.json")]
    return sum(1 for j in jobs if reached(j.get("pipeline"), False) >= STAGES.index("applied")
               and (j.get("pipeline") or {}).get("status") not in TERMINAL)


def last_event(pl):
    """The latest dated step (same date: the one recorded later wins). Steps with no readable date ('unknown')
    never beat a dated one; with no readable dates at all, the last step that has a date value, else None."""
    events = [e for e in (pl or {}).get("events", []) if e.get("date")]
    dated = [(to_date(e["date"]), i, e) for i, e in enumerate(events) if to_date(e["date"])]
    return max(dated)[2] if dated else (events[-1] if events else None)


def company_key(j):
    return re.split(r"\W+", (j.get("company") or "").lower())[0]


def resolve(P, jobs, kitmap, key):
    if key in jobs:
        return key
    for jid, k in kitmap.items():
        if k["folder"] == key and jid in jobs:
            return jid
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # "acmecorp" matches "Acme Corp Partners"
    hits = [jid for jid, j in jobs.items() if norm(key) and norm(key) in norm(j.get("company"))]
    if len(hits) == 1:
        return hits[0]
    if hits:
        sys.exit(f"'{key}' matches several jobs; use the job ID:\n" + "\n".join(
            f"  {h}  {jobs[h]['company']} - {jobs[h]['title']}" for h in hits))
    sys.exit(f"No job matches '{key}'.")


def record(P, a):
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    jid = resolve(P, jobs, kits(P), a.job)
    if a.stage not in STAGES + TERMINAL + OTHER:
        sys.exit(f"Unknown stage '{a.stage}'. Use one of: {', '.join(STAGES + OTHER + TERMINAL)}")
    rec = jobs[jid]
    pl = rec.setdefault("pipeline", {})
    pl.setdefault("events", [])
    ev = {"date": a.date, "stage": a.stage}
    if a.note:
        ev["note"] = a.note
    pl["events"].append(ev)
    if a.stage not in OTHER:
        pl["status"] = a.stage
        pl.pop("next", None)  # a new stage makes the old next step stale (e.g. a hold's "finish the application")
    if a.next:
        pl["next"] = a.next
    pl["updated"] = dt.date.today().isoformat()
    write_json((P.jobs / f"{jid}.json"), rec, indent=2)
    print(f"{rec['company']} - {rec['title']}: {a.stage} ({a.date or 'date unknown'})")


def has_primer(P, kit):
    """A kit has an interview primer when fit-map.md exists and interview-prep.md has likely questions."""
    if not kit:
        return False
    folder = P.applications / kit["folder"]
    prep = folder / "interview-prep.md"
    return (folder / "fit-map.md").exists() and prep.exists() and bool(
        re.search(r"^## [^\n]*likely interview questions", prep.read_text(encoding="utf-8"), re.I | re.M))


def in_progress_next(P, j, kit):
    import interviews  # imported here: interviews.py imports this module
    pl = j.get("pipeline") or {}
    owed = interviews.due_items(j, dt.date.today())
    if owed:
        return owed[0][1]
    if pl.get("next"):
        return pl["next"]
    if pl.get("status") == "interview" and not has_primer(P, kit):
        return f"Say **primer {(j.get('company') or '').split(' (')[0]}** before the interview"
    return "Wait for a response; tell me when you hear back"


def next_step(j, kit, reserve, open_code="check"):
    pl = j.get("pipeline") or {}
    if pl.get("next"):
        return pl["next"]
    if open_code == "closed":
        return "Closed: removal prompt"
    company = (j.get("company") or "").split(" (")[0]
    names = [c["name"] for c in j.get("connections_1st", [])]
    messaged = any(e["stage"] == "outreach" for e in pl.get("events", []))
    ask = f"Message {' or '.join(names)} first" if names and not messaged else ""
    if reserve:
        return "Reserve: another role at this company leads; apply there first"
    if not kit:
        steps = [ask, f"say **prep {company}** (stretch review, then kit)"]
    elif not kit["stretch"]:
        steps = [ask, f"say **stretch review {company}** (kit built before the stretch review)"]
    else:
        steps = [ask + " (draft in log.md)" if ask else "", "review the kit in Word, apply" if open_code == "fresh"
                 else "review the kit in Word, confirm the posting is open, apply"]
    text = "; then ".join(s for s in steps if s)
    return text[0].upper() + text[1:]


def build(P):
    jobs = {f.stem: load(f) for f in sorted(P.jobs.glob("*.json"))}
    tombs = tombstones(P.removed)
    kitmap = kits(P)
    today = dt.date.today()
    ranked = [j for j in jobs.values() if (j.get("review") or {}).get("tier") in ("A", "B", "C", "D")]

    # Company groups: the top 2 roles lead, the rest wait in reserve (same rule as the round report).
    groups = collections.defaultdict(list)
    for j in ranked:
        groups[company_key(j)].append(j)
    reserve = set()
    for g in groups.values():
        g.sort(key=lambda j: -(j["review"].get("total") or 0))
        reserve |= {j["job_id"] for j in g[2:]}

    in_progress, queue, closed = [], [], []
    for j in ranked:
        pl = j.get("pipeline") or {}
        status = pl.get("status")
        r = reached(pl, j["job_id"] in kitmap)
        if status in TERMINAL:
            closed.append(j)
        elif r >= STAGES.index("applied") or status == "interviewing":
            in_progress.append(j)
        elif j["review"]["tier"] in QUEUE_TIERS:
            queue.append(j)
    key = lambda j: ("AB".find(j["review"]["tier"]), j["job_id"] in reserve, -(j["review"].get("total") or 0))
    queue.sort(key=key)

    # Outcome funnel: current ranked jobs plus removed jobs that had got as far as an application.
    counts = collections.Counter()
    pool = [(j.get("pipeline"), j["job_id"] in kitmap) for j in ranked]
    # The funnel is cumulative: a job counts in every stage up to the furthest it reached, so an application counts
    # as "Kit built" whether or not a kit folder exists (has_kit only matters for jobs not yet applied).
    pool += [(t["pipeline"], False) for t in tombs if reached(t.get("pipeline"), False) >= STAGES.index("applied")]
    for pl, has_kit in pool:
        counts["ranked"] += 1
        for i in range(reached(pl, has_kit) + 1):
            counts[STAGES[i]] += 1

    out = []
    w = out.append
    w(f"# Apply queue ({today.isoformat()})\n")
    w("Built by `engine/pipeline.py queue` from the ranked jobs, the kit folders and each job's recorded steps. "
      "Rebuilt whenever you report a step (messaged, applied, heard back, interview) and at the end of every round.\n")
    import interviews  # imported here: interviews.py imports this module
    due_rows = interviews.due_table(P, today, soon=3)
    w("## Due\n")
    if due_rows:
        w("Owed now or in the next 3 days (`engine/interviews.py due`): debriefs, thank-you notes and follow-ups.\n")
        for d, j, text in due_rows:
            late = (today - d).days
            tag = "today" if late == 0 else (f"{late} day{'' if late == 1 else 's'} overdue" if late > 0
                                             else f"in {-late} day{'' if late == -1 else 's'}")
            w(f"- **{tag}** · {md(j['company'])}: {md(text)}")
    else:
        w("Nothing owed in the next 3 days.")
    w("")
    w("## Outcome funnel\n")
    w(funnel_table(counts) + "\n")

    w("## In progress\n")
    if in_progress:
        w("| Job | Score | Stage | Last step | Next |")
        w("|---|---|---|---|---|")
        for j in sorted(in_progress, key=lambda j: -reached(j.get("pipeline"), True)):
            pl = j["pipeline"]
            le = last_event(pl)
            when = to_date(le["date"]) if le else None
            days = (today - when).days if when else None
            ago = ("date unreadable" if days is None else "today" if days == 0
                   else f"{days} day{'' if days == 1 else 's'} ago")
            last = f"{le['stage']} {le['date']} ({ago})" if le else "-"
            stage = pl.get("status", "") + (f": {pl['stage']}" if pl.get("stage") else "")
            w(f"| [{md(j['company'])}: {md(j['title'])}]({j['url']}) | {j['review'].get('total')} | {md(stage)} | "
              f"{md(last)} | {md(in_progress_next(P, j, kitmap.get(j['job_id'])))} |")
    else:
        w("Nothing applied yet.")
    w("")

    w("## Apply next\n")
    w(f"A and B jobs with no application yet, best first. Several roles at one company: the top 2 lead, the rest "
      f"wait in reserve. C and D jobs ({sum(1 for j in ranked if j['review']['tier'] in ('C', 'D'))}) are not "
      f"queued; they are in the round report.\n")
    import staleness  # imported here: staleness.py imports this module
    w("**Open?** comes from `engine/staleness.py`: confirm a job is still open before kit work or applying "
      f"(fresh = seen open in the last {staleness.FRESH_DAYS} days).\n")
    w("| # | Tier | Score | Job | 1st-degree | Kit | Open? | Next step |")
    w("|---|---|---|---|---|---|---|---|")
    for i, j in enumerate(queue, 1):
        code, _ = staleness.verdict(j, today)
        oc = j.get("open_check") or {}
        open_cell = {"fresh": f"yes ({oc.get('date', '')[5:]})", "old": f"seen {oc.get('date', '')[5:]}; listed "
                     f"{staleness.describe_age(j, today)}", "closed": "**closed**"}.get(code, "check")
        kit = kitmap.get(j["job_id"])
        kit_cell = "-" if not kit else f"`{kit['folder']}` ({kit['prepared'] or 'date ?'}" + (
            ", stretch reviewed)" if kit["stretch"] else ", no stretch review)")
        conn = ", ".join(c["name"] for c in j.get("connections_1st", []))
        w(f"| {i} | {j['review']['tier']} | {j['review'].get('total')} | [{md(j['company'])}: {md(j['title'])}]"
          f"({j['url']}) | {md(conn)} | {md(kit_cell)} | {md(open_cell)} | "
          f"{md(next_step(j, kit, j['job_id'] in reserve, code))} |")
    w("")

    if closed:
        w("## Not applying\n")
        w("| Job | Score | Decision | Note |")
        w("|---|---|---|---|")
        for j in closed:
            pl = j["pipeline"]
            le = last_event(pl) or {}
            w(f"| [{md(j['company'])}: {md(j['title'])}]({j['url']}) | {j['review'].get('total')} | "
              f"{pl['status']} {le.get('date', '')} | {md(le.get('note', ''))} |")
        w("")

    path = P.reports / "apply-queue.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path}: {len(in_progress)} in progress, {len(queue)} queued, {len(closed)} not applying")
    print("Funnel: " + " -> ".join(f"{label} {counts[k]}" for k, label in FUNNEL))
    return counts


def funnel_table(counts):
    rows = ["| Stage | Jobs | Of the stage before |", "|---|---|---|"]
    prev = None
    for k, label in FUNNEL:
        n = counts[k]
        rate = "" if prev is None else (f"{100 * n / prev:.0f}%" if prev else "-")
        rows.append(f"| {label} | {n} | {rate} |")
        prev = n
    return "\n".join(rows)


def main():
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: otherwise the subcommand's default (None) overwrites a --data given before the subcommand.
    common.add_argument("--data", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", parents=[common])
    r.add_argument("job")
    r.add_argument("stage")
    r.add_argument("--date", type=iso_date, default=dt.date.today().isoformat(), help="YYYY-MM-DD; 'unknown' for no date")
    r.add_argument("--note")
    r.add_argument("--next", help="next step to show instead of the derived one (a new stage clears the old one)")
    sub.add_parser("queue", parents=[common])
    a = ap.parse_args()
    P = Paths(getattr(a, "data", None))
    if a.cmd == "record":
        if a.date == "unknown":
            a.date = None
        record(P, a)
    else:
        build(P)


if __name__ == "__main__":
    main()
