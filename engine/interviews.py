"""Interview loop and follow-up timers: what happened in each interview, what's owed afterwards, what to learn.

Usage:
  python engine/interviews.py schedule <job> --round R --date YYYY-MM-DD [--with "..."] [--format "..."]
  python engine/interviews.py debrief <job> --round R --file debrief.json      # after the interview
  python engine/interviews.py sent <job> --round R [--date YYYY-MM-DD]          # thank-you note(s) sent
  python engine/interviews.py due [--soon N]                                    # everything owed now (or within N days)
  python engine/interviews.py lessons                                           # lessons and questions across interviews

<job> is a job ID, a kit folder name, or a word that matches one company (same as pipeline.py).

Where it lives: an "interviews" list on the job record (6-system/jobs/<id>.json), one entry per round:
  {"round", "date" (None if unknown), "with", "format", "status": scheduled|done|cancelled,
   "debrief": {"how", "asked": [...], "landed": [...], "missed": [...], "signals", "next", "lessons": [...],
               "thank_you_to": [...]},
   "thank_you": {"to": [...], "due", "sent"}}
The debrief file is a JSON object with any of the debrief keys; Claude writes it in the session scratchpad from
the candidate's answers (engine/prompts/interview-loop.md) and this script merges it. The kit's log.md stays the human record.

Follow-up timers (calendar days, counted from the last thing that happened on the job):
  thank-you note   due the day after an interview, until marked sent
  after applying   FOLLOW_APPLIED days with no response -> a polite follow-up (or a nudge to the connection)
  after outreach   FOLLOW_OUTREACH days with no reply from the connection -> one follow-up message
  after interview  FOLLOW_INTERVIEW days with no news -> check in with the recruiter or hiring manager
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import Paths, iso_date, read_json, write_json, tombstones  # noqa: E402

FOLLOW_APPLIED = 7
FOLLOW_OUTREACH = 5
FOLLOW_INTERVIEW = 5
TERMINAL = ("passed", "rejected", "withdrawn", "closed")
DEBRIEF_KEYS = ("how", "asked", "landed", "missed", "signals", "next", "lessons", "thank_you_to")


def load(p, default=None):
    return read_json(Path(p), default)


def save(P, job):
    write_json((P.jobs / f"{job['job_id']}.json"), job, indent=2)


def day(s):
    try:
        return dt.date.fromisoformat(s) if s else None
    except (TypeError, ValueError):  # "unknown" or a hand-edited value: treat as no date
        return None


def find_round(job, rnd, create=False):
    for iv in job.setdefault("interviews", []):
        if str(iv.get("round")) == str(rnd):
            return iv
    if not create:
        sys.exit(f"No round {rnd} recorded for {job['company']}; schedule it first.")
    iv = {"round": str(rnd), "date": None, "status": "scheduled"}
    job["interviews"].append(iv)
    return iv


def short(job):
    return f"{(job.get('company') or '').split(' (')[0]}: {job.get('title')}"


# ---- what's owed --------------------------------------------------------------------------------------------------

def due_items(job, today, soon=0):
    """[(due_date, text)] owed on this job by today + soon days. Empty for closed-out jobs."""
    pl = job.get("pipeline") or {}
    if pl.get("status") in TERMINAL or pl.get("status") == "offer":
        return []
    horizon = today + dt.timedelta(days=soon)
    out = []
    ivs = job.get("interviews") or []
    for iv in ivs:
        d = day(iv.get("date"))
        if iv.get("status") == "scheduled" and d:
            if d < today:
                out.append((d, f"Debrief round {iv['round']} ({d}): tell me how it went"))
            elif d <= horizon:
                out.append((d, f"Round {iv['round']} on {d}" + (f" with {iv['with']}" if iv.get("with") else "")
                               + ": run the staleness gate and the primer check"))
        ty = iv.get("thank_you") or {}
        if iv.get("status") == "done" and ty.get("due") and not ty.get("sent") and day(ty["due"]) <= horizon:
            to = ", ".join(ty.get("to") or []) or "the panel"
            out.append((day(ty["due"]), f"Send the round {iv['round']} thank-you to {to} (draft in the kit folder)"))
    # Timers run from the most recent dated event or interview on the job.
    events = [(day(e.get("date")), e.get("stage")) for e in pl.get("events", [])]
    events += [(day(iv.get("date")), "interview-done") for iv in ivs if iv.get("status") == "done"]
    events = [e for e in events if e[0]]  # undated or unreadable dates can't start a timer
    # A round still marked scheduled (upcoming, undated, or past and awaiting its debrief) means the ball isn't in
    # the employer's court yet, so no "no news" timer runs; the debrief reminder above covers a past round.
    upcoming = any(iv.get("status") == "scheduled" for iv in ivs)
    if events and not upcoming:
        last_date, last_stage = max(events)
        # Suggest a nudge from a connection only when the job has a 1st-degree one, and name them.
        names = [c.get("name") for c in job.get("connections_1st") or [] if isinstance(c, dict) and c.get("name")]
        nudge = f" or ask {' or '.join(names)} for a nudge" if names else ""
        rule = {"applied": (FOLLOW_APPLIED, f"no response since applying: send a short follow-up{nudge}"),
                "outreach": (FOLLOW_OUTREACH, "no reply from your connection: one friendly follow-up"),
                "interview-done": (FOLLOW_INTERVIEW, "no news since the interview: check in with the recruiter or "
                                                     "hiring manager"),
                "interview": (FOLLOW_INTERVIEW, "no news since the interview: check in with the recruiter or "
                                                "hiring manager")}.get(last_stage)
        if rule:
            when = last_date + dt.timedelta(days=rule[0])
            if when <= horizon:
                out.append((when, f"{rule[1]} (last step {last_stage.replace('-done', '')} {last_date})"))
    return sorted(out)


def due_table(P, today, soon=0):
    """Rows for the apply queue's Due section: (date, job, text)."""
    rows = []
    for f in sorted(P.jobs.glob("*.json")):
        j = load(f)
        for d, text in due_items(j, today, soon):
            rows.append((d, j, text))
    return sorted(rows, key=lambda r: r[0])


# ---- commands -----------------------------------------------------------------------------------------------------

def schedule(P, job, a):
    was = (job.get("pipeline") or {}).get("status")
    if was in TERMINAL and not a.reopen:  # checked before anything changes: a closed-out job is never revived quietly
        sys.exit(f"{short(job)} is marked '{was}'. If the employer has come back to you, rerun with --reopen to "
                 f"schedule the interview and reopen it; otherwise check the job ID.")
    iv = find_round(job, a.round, create=True)
    date = None if a.date == "unknown" else a.date
    iv.update({k: v for k, v in (("date", date), ("with", a.with_), ("format", a.format)) if v})
    iv["status"] = "scheduled"
    pl = job.setdefault("pipeline", {"events": []})
    if pl.get("status") not in ("interview", "offer"):
        note = f"Round {a.round} scheduled for {a.date or 'a date to confirm'}"
        if was in TERMINAL:
            note += f" (reopened; was {was})"
        pl.setdefault("events", []).append({"date": dt.date.today().isoformat(), "stage": "interview", "note": note})
        pl["status"] = "interview"
        pl.pop("next", None)
    pl["stage"] = f"round {a.round} on {a.date}" if a.date else f"round {a.round}"
    pl["updated"] = dt.date.today().isoformat()
    save(P, job)
    print(f"{short(job)}: round {a.round} scheduled ({a.date or 'date unknown'})")


def debrief(P, job, a):
    iv = find_round(job, a.round, create=True)
    data = read_json(Path(a.file))
    unknown = set(data) - set(DEBRIEF_KEYS)
    if unknown:
        sys.exit(f"Unknown debrief keys: {', '.join(sorted(unknown))}. Use: {', '.join(DEBRIEF_KEYS)}")
    db = iv.setdefault("debrief", {})
    for k, v in data.items():
        if isinstance(v, list):
            db[k] = list(dict.fromkeys((db.get(k) or []) + v))
        else:
            db[k] = v
    iv["status"] = "done"
    if not iv.get("date"):
        iv["date"] = a.date
    to = data.get("thank_you_to")
    if to is not None:
        when = day(iv["date"]) or dt.date.today()
        iv["thank_you"] = {"to": to, "due": (when + dt.timedelta(days=1)).isoformat(),
                           "sent": (iv.get("thank_you") or {}).get("sent")}
    pl = job.setdefault("pipeline", {"events": []})
    pl["stage"] = f"round {a.round} done {iv['date']}" + (f"; next: {data['next']}" if data.get("next") else "")
    pl["updated"] = dt.date.today().isoformat()
    save(P, job)
    print(f"{short(job)}: round {a.round} debriefed ({len(db.get('asked') or [])} questions, "
          f"{len(db.get('lessons') or [])} lessons)" + (f"; thank-you due {iv['thank_you']['due']}" if to else ""))


def sent(P, job, a):
    iv = find_round(job, a.round)
    iv.setdefault("thank_you", {})["sent"] = a.date
    save(P, job)
    print(f"{short(job)}: round {a.round} thank-you sent {a.date}")


def due(P, today, soon):
    rows = due_table(P, today, soon)
    if not rows:
        print("Nothing due." if not soon else f"Nothing due in the next {soon} days.")
    for d, j, text in rows:
        late = (today - d).days
        tag = "today" if late == 0 else (f"{late}d overdue" if late > 0 else f"in {-late}d")
        print(f"- [{tag}] {short(j)}: {text}")


def lessons(P):
    jobs = [load(f) for f in sorted(P.jobs.glob("*.json"))] + [t for t in tombstones(P.removed) if t.get("interviews")]
    rounds = [(j, iv) for j in jobs for iv in j.get("interviews") or [] if iv.get("debrief")]
    if not rounds:
        print("No debriefs yet.")
        return
    print(f"# Interview lessons ({len(rounds)} debriefed rounds)\n")
    for j, iv in rounds:
        db = iv["debrief"]
        print(f"## {short(j)}: round {iv['round']} ({iv.get('date') or 'date ?'})")
        for k, label in (("how", "How it went"), ("signals", "Signals")):
            if db.get(k):
                print(f"- {label}: {db[k]}")
        for k, label in (("landed", "Landed"), ("missed", "Missed"), ("lessons", "Lesson")):
            for x in db.get(k) or []:
                print(f"- {label}: {x}")
        print()
    asked = collections.Counter(re.sub(r"\s+", " ", q.strip().lower()) for _, iv in rounds
                                for q in iv["debrief"].get("asked") or [])
    print("## Questions asked (most frequent first)")
    for q, n in asked.most_common():
        print(f"- {n}x {q}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schedule")
    s.add_argument("job")
    s.add_argument("--round", required=True)
    s.add_argument("--date", type=iso_date, help="YYYY-MM-DD; leave out if unknown")
    s.add_argument("--with", dest="with_", help="who is on the panel")
    s.add_argument("--format", help="e.g. Teams video, phone, on site")
    s.add_argument("--reopen", action="store_true",
                   help="schedule on a job marked passed, rejected, withdrawn or closed, and reopen it")
    d = sub.add_parser("debrief")
    d.add_argument("job")
    d.add_argument("--round", required=True)
    d.add_argument("--file", required=True, help="debrief JSON (write it in the session scratchpad)")
    d.add_argument("--date", type=iso_date, default=None, help="interview date, if the round had none recorded")
    t = sub.add_parser("sent")
    t.add_argument("job")
    t.add_argument("--round", required=True)
    t.add_argument("--date", type=iso_date, default=dt.date.today().isoformat())
    u = sub.add_parser("due")
    u.add_argument("--soon", type=int, default=0, help="also list what falls due in the next N days")
    sub.add_parser("lessons")
    a = ap.parse_args()
    P = Paths(a.data)
    today = dt.date.today()
    if a.cmd == "due":
        return due(P, today, a.soon)
    if a.cmd == "lessons":
        return lessons(P)
    from pipeline import kits, resolve  # imported here: pipeline.py imports this module for the apply queue
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    job = jobs[resolve(P, jobs, kits(P), a.job)]
    {"schedule": schedule, "debrief": debrief, "sent": sent}[a.cmd](P, job, a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
