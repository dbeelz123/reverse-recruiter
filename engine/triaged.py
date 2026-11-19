"""Already-triaged listings: skip jobs that earlier search runs already decided.

Usage:
  python engine/triaged.py seed                 rebuild 6-system/triaged.json from all 6-system/search-runs/*-run-*.json,
                                                *-triage-*.json and removed.json
  python engine/triaged.py add <run.json>       append one run's decided listings (after a triage is finished)
  python engine/triaged.py check <cards.json>   mark each card {company, title[, job_id]} as seen or new; cards with
                                                status Saved, Viewed or Applied are skipped
  python engine/triaged.py keeps <run.json>     end of triage: Markdown checklist of every keep (with links) to
                                                confirm each is marked Saved on LinkedIn
  python engine/triaged.py match-saved <run.json>   after extract.py: link saved jobs to an open run's rows
                                                (off-batch saves drop out of later batches; new saves that
                                                match no row are listed as "saved outside triage")
Every command also takes --data <folder> (default: my-data next to the engine).

Matching is on normalized company + title (pasted or filmed cards rarely carry a job ID), or on
job_id when both sides have one. A repost with the same title is caught; a changed title counts as new.
Abbreviations used in triage files (PM, Sr, TPM) are expanded so they match the full titles on cards.
An entry with title "*" covers the whole company (blocklisted companies and aggregators).
"""
import json
import re
import sys
from pathlib import Path

from paths import Paths

P = Paths()
ROOT = P.data.parent
DATA = P.data
OUT = P.triaged

ABBR = [
    (r"\bsr\b\.?", "senior"),
    (r"\btpm\b", "technical program manager"),
    (r"\bpm\b", "product manager"),
    (r"\bmgr\b", "manager"),
    (r"\bmgmt\b", "management"),
    (r"\bal\b", "ai"),  # frame-reading typo: "Al" for "AI"
    (r"&", " and "),
]


def norm_title(t):
    t = t.lower()
    t = re.sub(r"\([^)]*\)", " ", t)  # (Remote), (USA), (several), (cut off)
    for pat, rep in ABBR:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def norm_company(c):
    c = c.lower().replace("&", " and ")
    c = re.sub(r"\s+-\s+[a-z]{1,4}$", " ", c)  # ATS tag on the Job Tracker name, e.g. "Acme - GH" (2026-11-17)
    c = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|group|technologies|technology)\b\.?", " ", c)
    c = re.sub(r"[^a-z0-9]+", " ", c)
    return " ".join(c.split())


def key(company, title):
    return norm_company(company) + "|" + ("*" if title == "*" else norm_title(title))


def listing_entries(run, src):
    """Turn one triage/run file into entries. Saved jobs are skipped (they live in jobs/)."""
    search, date = run.get("search", "?"), run.get("date", "?")
    for x in run.get("listings", []):
        status = x.get("status")
        if status == "saved":
            continue
        decision = x.get("decision") or ("dq" if status in ("auto DQ", "already DQ") else None)
        if decision is None:
            continue  # undecided listing: not triaged
        reason = x.get("reason") or x.get("note") or status or ""
        company = x["company"]
        if reason.startswith("blocklist"):
            titles = ["*"]
        else:
            titles = [t.strip() for t in x["title"].split(";") if t.strip()]
        for t in titles:
            yield {
                "company": company,
                "title": t,
                "decision": decision,
                "reason": reason,
                "seen": [{"search": search, "date": date, "id": x.get("id")}],
                "source": src,
            }


def merge(entries, new):
    idx = {key(e["company"], e["title"]): e for e in entries}
    added = updated = 0
    for n in new:
        k = key(n["company"], n["title"])
        if k in idx:
            e = idx[k]
            e["seen"] += [s for s in n["seen"] if s not in e["seen"]]
            if n["decision"] != e["decision"] or n["reason"] != e["reason"]:
                e["decision"], e["reason"] = n["decision"], n["reason"]  # latest decision wins
            for f in ("job_id",):
                if n.get(f) and not e.get(f):
                    e[f] = n[f]
            updated += 1
        else:
            entries.append(n)
            idx[k] = n
            added += 1
    return added, updated


def load():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"updated": None, "note": __doc__.split("\n\n")[0], "entries": []}


def save(db):
    db["entries"].sort(key=lambda e: (norm_company(e["company"]), norm_title(e["title"]) if e["title"] != "*" else ""))
    OUT.write_text(json.dumps(db, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def seed():
    db = {"updated": None, "note": __doc__.split("\n\n")[0], "entries": []}
    files = sorted(P.search_runs.glob("*-triage-*.json")) + sorted(P.search_runs.glob("*-run-*.json"))
    for f in files:
        a, u = merge(db["entries"], listing_entries(json.loads(f.read_text(encoding="utf-8")), P.rel(f)))
        print(f"{f.name}: {a} added, {u} already present")
    removed = json.loads(P.removed.read_text(encoding="utf-8"))
    rem = []
    for r in removed:
        company, title = r.get("company", ""), r.get("title", "")
        rem.append({
            "company": company, "title": title, "job_id": r["job_id"], "decision": "dq",
            "reason": "removed: " + r["reason"], "seen": [{"search": "saved", "date": r["removed"]}],
            "source": "removed.json",
        })
    for e in rem:
        if e["company"]:
            merge(db["entries"], [e])
        else:
            db["entries"].append(e)  # older tombstone without company/title: matches only by job ID
    db["updated"] = max(r["removed"] for r in removed)
    save(db)
    print(f"{len(db['entries'])} entries -> {OUT.relative_to(ROOT)}")


def add(path):
    p = Path(path).resolve()
    run = json.loads(p.read_text(encoding="utf-8"))
    # Triage mode (docs/PLAN.md -> Triage modes): stamp the current mode on the run, and check that every card
    # The user decided in a batch carries the agent's own call ("likely"), so agreement can be measured.
    if "mode" not in run:
        import modes
        run = modes.with_mode(run, modes.mode(P).get("mode", "catch-up"))
        p.write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    missing = [x.get("id") for x in run.get("listings", []) if x.get("batch") and x.get("decision")
               and not x.get("likely") and not str(x.get("status", "")).startswith("saved")]
    if missing:
        print(f"WARNING: {len(missing)} decided batch cards have no 'likely' call (agent's prediction): "
              f"{', '.join(str(i) for i in missing[:12])}{' ...' if len(missing) > 12 else ''}")
    db = load()
    src = p.relative_to(DATA).as_posix() if DATA in p.parents else p.name
    a, u = merge(db["entries"], listing_entries(run, src))
    db["updated"] = run.get("date", db["updated"])
    save(db)
    print(f"{a} added, {u} updated -> {len(db['entries'])} entries")


def check(path):
    cards = json.loads(Path(path).read_text(encoding="utf-8"))
    db = load()
    by_key = {key(e["company"], e["title"]): e for e in db["entries"] if e["company"]}
    by_id = {e["job_id"]: e for e in db["entries"] if e.get("job_id")}
    for c in cards:
        status = c.get("status") or []
        # Saved/Applied on LinkedIn: already in the user's saves (synced with the project) or applied -> no triage.
        # Opportunistic saves made during batches are linked at round start by match-saved.
        # Viewed: the user already looked at it and didn't save it, or saved it and it was DQ'd -> no triage.
        for flag, act in (("Saved", "skip (saved)"), ("Applied", "skip (applied)"), ("Viewed", "skip (viewed)")):
            if flag in status:
                c["triaged"] = {"decision": None, "reason": flag, "action": act}
                break
        if c.get("triaged"):
            continue
        hit = (c.get("job_id") and by_id.get(c["job_id"])) or by_key.get(key(c["company"], c["title"])) \
            or by_key.get(key(c["company"], "*"))
        # DQ'd before -> skip. Kept/maybe before but not saved -> flag it rather than skip.
        if hit:
            # Company-group cuts are not judgments on the job itself (rule changed 2026-11-17): flag, don't skip.
            group_cut = "company group" in (hit.get("reason") or "")
            c["triaged"] = {"decision": hit["decision"], "reason": hit["reason"], "seen": hit["seen"][-1],
                            "action": "skip" if hit["decision"] == "dq" and not group_cut else "flag"}
        else:
            c["triaged"] = None
    Path(path).write_text(json.dumps(cards, indent=1, ensure_ascii=False), encoding="utf-8")
    acts = [c["triaged"]["action"] if c["triaged"] else "new" for c in cards]
    print(f"{len(cards)} cards: {acts.count('skip (saved)')} skip (Saved), {acts.count('skip (viewed)')} skip (Viewed), "
          f"{acts.count('skip (applied)')} skip (Applied), {acts.count('skip')} skip (DQ'd before), "
          f"{acts.count('flag')} flag (kept before), {acts.count('new')} new; marked in {path}")


def match_saved(path):
    """Link saved jobs (jobs/*.json, after extract.py) to the rows of an open triage run.

    Covers saves made off-batch: from a Find link that landed on another job, or a job LinkedIn showed
    beside the search. A matched row that isn't decided yet becomes keep / "saved (off-batch)", so it drops
    out of later batches. New jobs (no review yet) that match no row are listed as "saved outside triage";
    they still get the full review in the round, like every saved job.
    """
    p = Path(path)
    run = json.loads(p.read_text(encoding="utf-8"))
    rows = {}
    for e in run.get("listings", []):
        rows.setdefault(key(e["company"], e["title"]), []).append(e)
    linked, conflicts, outside = [], [], []
    for f in sorted(P.jobs.glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        hits = rows.get(key(j.get("company", ""), j.get("title", "")), [])
        for e in hits:
            if e.get("job_id") == j["job_id"]:
                continue
            e["job_id"] = j["job_id"]
            if e.get("status") == "saved":  # already marked Saved on the results card
                continue
            if e.get("decision") == "dq":
                conflicts.append(f'{j["company"]} - {j["title"]} ({j["job_id"]}): saved, but DQ in this run ({e.get("reason", "")})')
            elif not e.get("decision"):
                e["decision"], e["reason"], e["status"] = "keep", "saved off-batch", "saved (off-batch)"
                linked.append(f'{e["id"]} {j["company"]} - {j["title"]} ({j["job_id"]})')
        if not hits and not j.get("review"):
            outside.append(f'{j["company"]} - {j["title"]} ({j["job_id"]})')
    p.write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(linked)} undecided rows now saved (off-batch):", *linked, sep="\n  ")
    print(f"{len(conflicts)} saved jobs DQ'd in this run (check):", *conflicts, sep="\n  ")
    print(f"{len(outside)} new saved jobs outside this triage:", *outside, sep="\n  ")


def keeps(path):
    """Save-check list at the end of a triage: every keep in the run, as a Markdown table with links,
    so the user can confirm each one is marked Saved on LinkedIn before saving the PDFs."""
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = [e for e in run.get("listings", []) if e.get("decision") == "keep"]
    print(f"{len(rows)} keeps in {run.get('search', '?')} ({run.get('date', '?')}). Confirm each is Saved on LinkedIn.\n")
    print("| # | Job | Location | Batch | LinkedIn match | PDF saved |")
    print("|---|---|---|---|---|---|")
    for i, e in enumerate(rows, 1):
        link = e.get("url") or e.get("find")
        pdf = "yes" if e.get("job_id") else ""
        print(f"| {i} | [{e['company']}: {e['title']}]({link}) | {e.get('location', '')} | {e.get('batch', '')} | "
              f"{e.get('linkedin_match', '')} | {pdf} |")


def use_data(folder):
    """Point the module at another data folder (--data); the defaults above serve imports like metrics.py's."""
    global P, ROOT, DATA, OUT
    P = Paths(folder)
    ROOT, DATA, OUT = P.data.parent, P.data, P.triaged


if __name__ == "__main__":
    if "--data" in sys.argv:  # accepted anywhere on the line, like the other scripts
        i = sys.argv.index("--data")
        use_data(sys.argv[i + 1])
        del sys.argv[i:i + 2]
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "seed":
        seed()
    elif cmd == "keeps" and len(sys.argv) == 3:
        keeps(sys.argv[2])
    elif cmd == "match-saved" and len(sys.argv) == 3:
        match_saved(sys.argv[2])
    elif cmd == "add" and len(sys.argv) == 3:
        add(sys.argv[2])
    elif cmd == "check" and len(sys.argv) == 3:
        check(sys.argv[2])
    else:
        print(__doc__)
