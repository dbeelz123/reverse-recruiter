"""Staleness check: is a posting still open before anyone spends time on it?

Usage:
  python engine/staleness.py gate <job>                  # before kit work or applying: FRESH (exit 0) or CHECK FIRST (exit 1)
  python engine/staleness.py confirm <job> open|closed [--date YYYY-MM-DD] [--note "..."]
  python engine/staleness.py tracker <paste.txt> [--date YYYY-MM-DD]   # mark every job a Job Tracker paste lists
  python engine/staleness.py status [--all]              # every queued job: listing age, last check, verdict

<job> is a job ID, a kit folder name, or a word that matches one company (same as pipeline.py).

Data gathering stays manual: the script never opens a job site. Evidence comes from three places:
  1. the saved PDF: the "Posted / Reposted N ago" line and the print date give an estimated listing date;
  2. a pasted Job Tracker → Saved page (1-inbox/tracked-jobs/): a job listed with a "Posted/Reposted ... ago" line
     was still listed on the paste date; one marked "No longer accepting applications" is closed;
  3. the person saying so after opening the link ("confirm").
The latest check is kept on the job record as "open_check": {date, result: open|closed, source, note}.
A job is FRESH when it was confirmed open within FRESH_DAYS. A closed result never removes anything by itself:
closed jobs go through the removal prompt (engine/remove_job.py) like any other unsave.
"""
import argparse
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import Paths, iso_date, read_json, write_json, to_date  # noqa: E402

FRESH_DAYS = 3    # an open check younger than this lets kit work and applying go ahead
OLD_DAYS = 30     # listings at least this old (estimated) get a warning even when last seen open
UNITS = {"h": 0, "hour": 0, "min": 0, "minute": 0, "d": 1, "day": 1, "w": 7, "wk": 7, "week": 7,
         "mo": 30, "month": 30, "y": 365, "yr": 365, "year": 365}
CLOSED = r"no longer accepting|not accepting applications|job (is )?closed|this job has expired"
TERMINAL = ("passed", "rejected", "withdrawn", "closed")


def load(p, default=None):
    return read_json(Path(p), default)


def days_from(text):
    """'Reposted 3 weeks ago' / 'Posted 4d ago' / '1 month ago' -> days, or None."""
    m = re.search(r"(\d+)\s*(minute|min|hour|h|day|d|week|wk|w|month|mo|year|yr|y)s?\b", text or "", re.I)
    return int(m.group(1)) * UNITS[m.group(2).lower()] if m else None


def printed_date(job):
    p = job.get("printed")
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(p, fmt).date()
        except (TypeError, ValueError):
            pass
    return to_date(job.get("extracted_at"))  # None when missing or malformed


def listing_info(job, today):
    """Estimated listing date and age, whether it was a repost, and how old the PDF snapshot is."""
    snap = printed_date(job)
    d = days_from(job.get("posted"))
    listed = snap - dt.timedelta(days=d) if snap and d is not None else None
    return {"listed": listed, "age": (today - listed).days if listed else None,
            "reposted": bool(re.search(r"repost", job.get("posted") or "", re.I)),
            "snapshot": snap, "snapshot_age": (today - snap).days if snap else None}


def verdict(job, today):
    """(code, text): code is fresh, check, old or closed."""
    oc = job.get("open_check") or {}
    info = listing_info(job, today)
    if oc.get("result") == "closed":
        return "closed", f"closed ({oc.get('source')}, {oc.get('date')}): removal prompt"
    try:
        checked = dt.date.fromisoformat(oc.get("date") or "")
    except ValueError:  # missing or hand-edited date: treat as never confirmed
        checked = None
    if checked and checked > today:  # a date in the future is a typo, not evidence
        return "check", f"open check dated {oc['date']}, which is in the future: check again"
    if oc.get("result") == "open" and checked:
        ago = (today - checked).days
        seen = f"seen open {oc['date']} ({oc.get('source')}, {ago} day{'' if ago == 1 else 's'} ago)"
        if ago <= FRESH_DAYS:
            if info["age"] is not None and info["age"] >= OLD_DAYS:
                return "old", f"{seen}; listed about {info['age']} days ago, so ask whether it's still active"
            return "fresh", seen
        return "check", f"{seen}; check again"
    if job.get("external"):
        return "check", "external job: ask the recruiter or company whether it's still open"
    snap = info["snapshot_age"]
    return "check", f"never confirmed; PDF {snap} day{'' if snap == 1 else 's'} old" if snap is not None \
        else "never confirmed"


def describe_age(job, today):
    info = listing_info(job, today)
    if info["age"] is None:
        return "-"
    return f"~{info['age']}d" + (" (repost)" if info["reposted"] else "")


def save(P, job):
    write_json((P.jobs / f"{job['job_id']}.json"), job, indent=2)


def set_check(P, job, result, date, source, note=None):
    prev = job.get("open_check")
    if prev and prev.get("date") and prev["date"] > date:
        return False  # never let an older paste overwrite a newer check
    job["open_check"] = {"date": date, "result": result, "source": source}
    if note:
        job["open_check"]["note"] = note
    save(P, job)
    return True


# ---- Job Tracker paste --------------------------------------------------------------------------------------------

def norm(s):
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co)\b\.?", "", (s or "").lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]", "", s)


def parse_tracker(text):
    """[(title, company, status_line)] from a pasted Job Tracker → Saved page."""
    lines = [l.strip() for l in text.splitlines()]
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^(.+?) · (.+)$", line)
        if not m or m.group(2).strip().isdigit():  # "Saved · 68" is the page header, not a job
            continue
        title = next((lines[k] for k in range(i - 1, max(i - 4, -1), -1) if lines[k]), "")
        title = re.split(r"\s*\(Verified job\)", title)[0].strip()
        status = ""
        for k in range(i + 1, min(i + 8, len(lines))):
            if re.search(r"^(Posted|Reposted)\b", lines[k], re.I) or re.search(CLOSED, lines[k], re.I):
                status = lines[k]
                break
            if re.match(r"^(.+?) · (.+)$", lines[k]):
                break
        if not status and not re.search(r"\w", title):
            continue
        out.append((title, m.group(1).strip(), status))
    return out


def match_job(jobs, title, company):
    cands = [j for j in jobs.values() if norm(company) and (norm(company) in norm(j.get("company"))
                                                             or norm(j.get("company")) in norm(company))]
    exact = [j for j in cands if norm(j.get("title")) == norm(title)]
    if len(exact) == 1:
        return exact[0]
    # Fuzzy fallback only when exactly one job at the company is close: two near-identical titles (one posting at
    # two levels, or a repost) would otherwise let a paste mark the wrong job open or closed.
    close = [j for j in cands if difflib.SequenceMatcher(None, norm(j.get("title")), norm(title)).ratio() >= 0.85]
    return close[0] if len(close) == 1 else None


def tracker(P, path, date):
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    text = Path(path).read_text(encoding="utf-8")
    entries = parse_tracker(text)
    header = re.search(r"Saved · (\d+)", text)
    opened = closed = skipped = 0
    unmatched = []
    for title, company, status in entries:
        j = match_job(jobs, title, company)
        if not j:
            unmatched.append(f"{company}: {title}")
            continue
        if re.search(CLOSED, status, re.I):
            result = "closed"
        elif status:
            result = "open"
        else:
            unmatched.append(f"{company}: {title} (no Posted/closed line; check by hand)")
            continue
        if set_check(P, j, result, date, "tracker paste", status):
            opened += result == "open"
            closed += result == "closed"
        else:
            skipped += 1
    print(f"{Path(path).name} ({date}): {len(entries)} listed"
          + (f" of Saved · {header.group(1)}" if header else "")
          + f"; marked {opened} open, {closed} closed; {skipped} kept a newer check")
    if header and len(entries) < int(header.group(1)):
        print(f"  ! the paste lists {len(entries)} of {header.group(1)} saved jobs: a page may be missing "
              f"(closed jobs can also show without a Posted line)")
    for u in unmatched:
        print(f"  - not in the project: {u}")
    if closed:
        print("  Closed jobs need the removal prompt (engine/remove_job.py); `status` lists them.")


# ---- commands -----------------------------------------------------------------------------------------------------

def gate(P, job, today):
    code, text = verdict(job, today)
    name = f"{job.get('company')} - {job.get('title')}"
    if code == "fresh":
        print(f"FRESH: {name}: {text}")
        return True
    print(f"CHECK FIRST: {name}: {text}")
    print(f"  Listing age: {describe_age(job, today)} · link: {job.get('url')}")
    print("  Open the link (or paste Job Tracker → Saved), then: "
          f"python engine/staleness.py confirm {job['job_id']} open|closed")
    return False


def status(P, today, show_all):
    import pipeline  # imported here: pipeline.py imports this module for the apply queue
    jobs = {f.stem: load(f) for f in sorted(P.jobs.glob("*.json"))}
    rows = []
    for j in jobs.values():
        rev = j.get("review") or {}
        pl = j.get("pipeline") or {}
        if pl.get("status") in TERMINAL:
            continue
        applied = pipeline.reached(pl, False) >= pipeline.STAGES.index("applied")
        if not show_all and (applied or rev.get("tier") not in ("A", "B")):
            continue
        code, text = verdict(j, today)
        rows.append((["closed", "old", "check", "fresh"].index(code), -(rev.get("total") or 0), j, code, text))
    rows.sort(key=lambda r: r[:2])
    print(f"| Job | Score | Listed | Verdict |\n|---|---|---|---|")
    for _, _, j, code, text in rows:
        print(f"| {j.get('company')}: {j.get('title')} | {(j.get('review') or {}).get('total', '-')} | "
              f"{describe_age(j, today)} | **{code}**: {text} |")
    counts = {c: sum(1 for r in rows if r[3] == c) for c in ("fresh", "check", "old", "closed")}
    print("\n" + ", ".join(f"{v} {k}" for k, v in counts.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate").add_argument("job")
    c = sub.add_parser("confirm")
    c.add_argument("job")
    c.add_argument("result", choices=["open", "closed"])
    c.add_argument("--date", type=iso_date, default=dt.date.today().isoformat())
    c.add_argument("--note")
    t = sub.add_parser("tracker")
    t.add_argument("paste")
    t.add_argument("--date", type=iso_date, help="the day the page was copied (default: a date in the file name, else the file's "
                                  "modified date)")
    s = sub.add_parser("status")
    s.add_argument("--all", action="store_true", help="include applied jobs and C/D tiers")
    a = ap.parse_args()
    P = Paths(a.data)
    today = dt.date.today()
    if a.cmd == "tracker":
        named = re.search(r"\d{4}-\d{2}-\d{2}", Path(a.paste).name)  # tracked-2026-11-17.txt
        date = a.date or (named.group(0) if named else
                          dt.date.fromtimestamp(Path(a.paste).stat().st_mtime).isoformat())
        tracker(P, a.paste, date)
        return
    if a.cmd == "status":
        status(P, today, a.all)
        return
    from pipeline import kits, resolve
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    job = jobs[resolve(P, jobs, kits(P), a.job)]
    if a.cmd == "gate":
        sys.exit(0 if gate(P, job, today) else 1)
    set_check(P, job, a.result, a.date, "confirmed by hand", a.note)
    print(f"{job['company']} - {job['title']}: {a.result} on {a.date}")
    if a.result == "closed":
        print("  Closed: put it through the removal prompt (ask, then engine/remove_job.py) and record "
              f"`python engine/pipeline.py record {job['job_id']} closed` if it was in the apply queue.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
