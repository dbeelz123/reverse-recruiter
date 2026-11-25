"""Already-triaged listings: skip jobs that earlier search runs already decided.

Usage:
  python engine/triaged.py seed                 rebuild 6-system/triaged.json from all 6-system/search-runs/*-run-*.json,
                                                *-triage-*.json and removed.json
  python engine/triaged.py add <run.json>       append one run's decided listings (after a triage is finished)
  python engine/triaged.py check <cards.json>   mark each card {company, title[, job_id]} as seen or new; cards with
                                                status Saved, Viewed or Applied are skipped; a listing from a
                                                blocklisted company not decided before is marked
                                                "blocklist (confirm)" with the entry and reason, for the user
                                                to confirm (never DQ'd silently)
  python engine/triaged.py keeps <run.json>     end of triage: Markdown checklist of every keep (with links) to
                                                confirm each is marked Saved on LinkedIn
  python engine/triaged.py match-saved <run.json>   after extract.py: link saved jobs to an open run's rows
                                                (off-batch saves drop out of later batches; new saves that
                                                match no row are listed as "saved outside triage")
  python engine/triaged.py reposts              repost watch: writes 2-reports/repost-watch.md (listings that keep
                                                coming back, companies that repost often, terms that changed)
Every command also takes --data <folder> (default: my-data next to the engine).

Matching is on normalized company + title (pasted or filmed cards rarely carry a job ID), or on
job_id when both sides have one. A repost with the same title is caught; a changed title counts as new.
Each sighting keeps the card's salary, location and posted line, so check can tell when a listing DQ'd before
comes back with different terms (a salary or location not seen before): it is flagged for a fresh look, not skipped.
Abbreviations used in triage files (PM, Sr, TPM) are expanded so they match the full titles on cards.
An entry with title "*" covers the whole company: written for a listing whose DQ reason starts with "blocklist"
(blocklisted companies, job-board aggregators included).
"""
import datetime
import json
import re
import sys
from pathlib import Path

from paths import DataFileError, Paths, blocked_by, blocklist, case_by_case, read_json, to_date, write_json, tombstones

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


def run_listings(run, src):
    """A run file's listings, checked to be a list of objects; anything else stops with the file named (a skipped
    listing could silently drop a triage decision)."""
    listings = run.get("listings", []) if isinstance(run, dict) else None
    if not isinstance(listings, list):
        raise DataFileError(f"Malformed {src}: expected an object with a 'listings' list.")
    for i, x in enumerate(listings):
        if not isinstance(x, dict):
            raise DataFileError(f"Malformed {src}: listings[{i}] is not an object.")
    return listings


def require_names(x, i, src, what="listings"):
    """Stop with the file named unless a listing or card has a company and a title."""
    for f in ("company", "title"):
        if not (isinstance(x.get(f), str) and x[f].strip()):
            raise DataFileError(f"Malformed {src}: {what}[{i}] ({x.get('id', x.get('n', 'no id'))}) has no {f}.")


def listing_entries(run, src):
    """Turn one triage/run file into entries. Saved jobs are skipped (they live in jobs/)."""
    search, date = run.get("search", "?"), run.get("date", "?")
    for i, x in enumerate(run_listings(run, src)):
        # A malformed decided listing stops with the file named: skipping it would silently drop a decision.
        status = x.get("status")
        if status == "saved":
            continue
        decision = x.get("decision") or ("dq" if status in ("auto DQ", "already DQ") else None)
        if decision is None:
            continue  # undecided listing: not triaged
        reason = x.get("reason") or x.get("note") or status or ""
        company = x.get("company")
        if not isinstance(company, str) or not company.strip():
            raise DataFileError(f"Malformed {src}: listings[{i}] ({x.get('id', 'no id')}) is decided but has no company.")
        if reason.startswith("blocklist"):
            titles = ["*"]
        elif isinstance(x.get("title"), str):
            titles = [t.strip() for t in x["title"].split(";") if t.strip()]
        else:
            raise DataFileError(f"Malformed {src}: listings[{i}] ({x.get('id', 'no id')}) is decided but has no title.")
        seen = {"search": search, "date": date, "id": x.get("id")}
        seen.update({f: x[f] for f in TERMS + ("posted",) if isinstance(x.get(f), str) and x[f].strip()})
        for t in titles:
            yield {
                "company": company,
                "title": t,
                "decision": decision,
                "reason": reason,
                "seen": [dict(seen)],
                "source": src,
            }


TERMS = ("salary", "location")  # card terms kept on each sighting; a value never seen before counts as a change


def norm_terms(s):
    s = re.sub(r"\.00\b", "", s.lower())
    return " ".join(re.sub(r"[^a-z0-9$%+\-]+", " ", s).split())


def sightings(entry):
    """An entry's sightings that are objects; a missing, null or hand-edited 'seen' (or odd items in it) is skipped."""
    seen = entry.get("seen") if isinstance(entry, dict) else None
    return [s for s in seen if isinstance(s, dict)] if isinstance(seen, list) else []


def changed_terms(card, entry):
    """Terms on this card that no earlier sighting of the entry showed. Comparing against every earlier value,
    not just the last, keeps one posting listed in several cities (or at several levels) from looking changed.
    A side with no value (older sightings, cards without a salary line) is not a change."""
    out = {}
    for f in TERMS:
        new = card.get(f)
        olds = [s[f] for s in sightings(entry) if isinstance(s.get(f), str) and s[f].strip()]
        if isinstance(new, str) and new.strip() and olds and norm_terms(new) not in {norm_terms(o) for o in olds}:
            out[f] = {"was": olds[-1], "now": new}
    return out


def merge(entries, new):
    idx = {key(e["company"], e["title"]): e for e in entries}
    added = updated = 0
    for n in new:
        k = key(n["company"], n["title"])
        if k in idx:
            e = idx[k]
            e["seen"] = sightings(e) + [s for s in n["seen"] if s not in sightings(e)]
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
        db = read_json(OUT, expect=dict)
        entries = db.get("entries")
        if not isinstance(entries, list):
            raise DataFileError(f"Malformed {OUT}: 'entries' must be a list.")
        # Every entry must be an object with a company and title (strings; company may be "" for an old tombstone)
        # and, if it has one, a text job_id (an object or list would break the ID lookups).
        for i, e in enumerate(entries):
            if not (isinstance(e, dict) and isinstance(e.get("company"), str) and isinstance(e.get("title"), str)
                    and isinstance(e.get("job_id") or "", str)):
                raise DataFileError(f"Malformed {OUT}: entries[{i}] needs 'company' and 'title' (and a text "
                                    f"'job_id', if any). Fix it by hand or rebuild the file with 'triaged.py seed'.")
        return db
    return {"updated": None, "note": __doc__.split("\n\n")[0], "entries": []}


def save(db):
    db["entries"].sort(key=lambda e: (norm_company(e["company"]), norm_title(e["title"]) if e["title"] != "*" else ""))
    write_json(OUT, db, indent=1, newline=True)


def add_tombstones(entries, only_new=False):
    """Merge removed.json tombstones into entries (each removed job counts as DQ'd). With only_new, skip
    tombstones whose job ID is already present, so a lookup copy picks up removals made since the last seed."""
    removed = tombstones(P.removed)  # malformed entries are skipped
    have = {e.get("job_id") for e in entries if e.get("job_id")} if only_new else set()
    for r in removed:
        if r["job_id"] in have:
            continue
        e = {"company": r.get("company", ""), "title": r.get("title", ""), "job_id": r["job_id"], "decision": "dq",
             "reason": "removed: " + r.get("reason", "(no reason recorded)"),
             "seen": [{"search": "saved", "date": r.get("removed")}], "source": "removed.json"}
        old = next((x for x in entries if e["company"] and key(x["company"], x["title"]) == key(e["company"], e["title"])),
                   None)
        if old is None:
            entries.append(e)  # (an older tombstone without company/title matches only by job ID)
            continue
        # A removal older than the entry's latest decision (e.g. a posting that closed, then was relisted and kept)
        # adds its date but doesn't overrule that decision. A removal on the same day does: within a day, removal
        # follows the decision (a job kept in triage, then removed in the round). No removal date: can't order it.
        gone = to_date(r.get("removed"))
        later = gone is None or any((to_date(s.get("date")) or gone) > gone for s in sightings(old))
        old["seen"] = sightings(old) + [s for s in e["seen"] if s not in sightings(old)]
        if not later:
            old["decision"], old["reason"] = e["decision"], e["reason"]
        if not old.get("job_id"):
            old["job_id"] = e["job_id"]
    return removed


def seed():
    db = {"updated": None, "note": __doc__.split("\n\n")[0], "entries": []}
    files = sorted(P.search_runs.glob("*-triage-*.json")) + sorted(P.search_runs.glob("*-run-*.json"))
    for f in files:
        a, u = merge(db["entries"], listing_entries(read_json(f), P.rel(f)))
        print(f"{f.name}: {a} added, {u} already present")
    removed = add_tombstones(db["entries"])
    dates = [d for d in (to_date(r.get("removed")) for r in removed) if d]  # malformed dates are skipped
    db["updated"] = (max(dates) if dates else datetime.date.today()).isoformat()
    save(db)
    print(f"{len(db['entries'])} entries -> {OUT.relative_to(ROOT)}")


def add(path):
    p = Path(path).resolve()
    run = read_json(p)
    run_listings(run, p.name)
    # Triage mode (docs/PLAN.md -> Triage modes): stamp the current mode on the run, and check that every card
    # The user decided in a batch carries the agent's own call ("likely"), so agreement can be measured.
    if "mode" not in run:
        import modes
        run = modes.with_mode(run, modes.mode(P).get("mode", "catch-up"))
        write_json(p, run, indent=1)
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
    cards = read_json(Path(path))
    if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
        raise DataFileError(f"Malformed {Path(path).name}: expected a list of card objects (from ingest_results.py).")
    for i, c in enumerate(cards):
        require_names(c, i, Path(path).name, what="cards")
    db = load()
    # Jobs removed since the last seed are in removed.json only: add them to this lookup (triaged.json is unchanged).
    add_tombstones(db["entries"], only_new=True)
    by_key = {key(e["company"], e["title"]): e for e in db["entries"] if e["company"]}
    by_id = {e["job_id"]: e for e in db["entries"] if e.get("job_id")}
    spec = read_json(P.spec, {}, expect=dict)
    blocks = blocklist(spec, P.spec)
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
        hit = (c.get("job_id") and by_id.get(c["job_id"])) or by_key.get(key(c["company"], c["title"]))
        # A blocklisted company's listing not decided before: shown with the entry and its reason for the user to
        # confirm (set by the user 2026-11-24), never DQ'd silently.
        bl = None if hit else blocked_by(c["company"], blocks)
        if bl:
            c["triaged"] = {"decision": None, "action": "blocklist (confirm)", "blocklist": bl["value"],
                            "reason": bl.get("reason", ""), "case_by_case": case_by_case(bl)}
            continue
        hit = hit or by_key.get(key(c["company"], "*"))
        # DQ'd before -> skip. Kept/maybe before but not saved -> flag it rather than skip.
        if hit:
            # Company-group cuts are not judgments on the job itself (rule changed 2026-11-17): flag, don't skip.
            group_cut = "company group" in (hit.get("reason") or "")
            c["triaged"] = {"decision": hit["decision"], "reason": hit["reason"],
                            "seen": (sightings(hit) or [None])[-1],
                            "action": "skip" if hit["decision"] == "dq" and not group_cut else "flag"}
            # A DQ'd listing back with terms not seen before (e.g. a higher salary, now remote): look again.
            changed = changed_terms(c, hit) if c["triaged"]["action"] == "skip" else {}
            if changed:
                c["triaged"].update(action="flag (terms changed)", changed=changed)
        else:
            c["triaged"] = None
    write_json(Path(path), cards, indent=1)
    acts = [c["triaged"]["action"] if c["triaged"] else "new" for c in cards]
    print(f"{len(cards)} cards: {acts.count('skip (saved)')} skip (Saved), {acts.count('skip (viewed)')} skip (Viewed), "
          f"{acts.count('skip (applied)')} skip (Applied), {acts.count('skip')} skip (DQ'd before), "
          f"{acts.count('flag (terms changed)')} flag (DQ'd before, terms changed), "
          f"{acts.count('blocklist (confirm)')} blocklisted (confirm), "
          f"{acts.count('flag')} flag (kept before), {acts.count('new')} new; marked in {path}")
    for c in cards:
        if c["triaged"] and c["triaged"]["action"] == "blocklist (confirm)":
            soft = " [case by case: is this role in the blocked area?]" if c["triaged"]["case_by_case"] else ""
            print(f"  blocklisted{soft}: {c['company']} - {c['title']} -> {c['triaged']['blocklist']}: "
                  f"{c['triaged']['reason']}")
    for c in cards:
        if c["triaged"] and c["triaged"]["action"] == "flag (terms changed)":
            what = "; ".join(f"{f}: {v['was']} -> {v['now']}" for f, v in c["triaged"]["changed"].items())
            print(f"  terms changed: {c['company']} - {c['title']} ({what}); DQ'd before: {c['triaged']['reason']}")


def match_saved(path):
    """Link saved jobs (jobs/*.json, after extract.py) to the rows of an open triage run.

    Covers saves made off-batch: from a Find link that landed on another job, or a job LinkedIn showed
    beside the search. A matched row that isn't decided yet becomes keep / "saved (off-batch)", so it drops
    out of later batches. New jobs (no review yet) that match no row are listed as "saved outside triage";
    they still get the full review in the round, like every saved job.
    """
    p = Path(path)
    run = read_json(p)
    rows = {}
    for i, e in enumerate(run_listings(run, p.name)):
        require_names(e, i, p.name)
        rows.setdefault(key(e["company"], e["title"]), []).append(e)
    linked, conflicts, outside = [], [], []
    for f in sorted(P.jobs.glob("*.json")):
        j = read_json(f)
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
    write_json(p, run, indent=1)
    print(f"{len(linked)} undecided rows now saved (off-batch):", *linked, sep="\n  ")
    print(f"{len(conflicts)} saved jobs DQ'd in this run (check):", *conflicts, sep="\n  ")
    print(f"{len(outside)} new saved jobs outside this triage:", *outside, sep="\n  ")


def keeps(path):
    """Save-check list at the end of a triage: every keep in the run, as a Markdown table with links,
    so the user can confirm each one is marked Saved on LinkedIn before saving the PDFs."""
    run = read_json(Path(path))
    rows = [e for e in run_listings(run, Path(path).name) if e.get("decision") == "keep"]
    for i, e in enumerate(rows):
        require_names(e, i, Path(path).name, what="keeps")
    print(f"{len(rows)} keeps in {run.get('search', '?')} ({run.get('date', '?')}). Confirm each is Saved on LinkedIn.\n")
    print("| # | Job | Location | Batch | LinkedIn match | PDF saved |")
    print("|---|---|---|---|---|---|")
    for i, e in enumerate(rows, 1):
        link = e.get("url") or e.get("find")
        pdf = "yes" if e.get("job_id") else ""
        print(f"| {i} | [{e['company']}: {e['title']}]({link}) | {e.get('location', '')} | {e.get('batch', '')} | "
              f"{e.get('linkedin_match', '')} | {pdf} |")


EVERGREEN_DAYS = 21  # seen across at least this many days ...
EVERGREEN_DATES = 3  # ... on at least this many separate days: likely evergreen (a pipeline or ghost listing)
RESURFACE_GAP = 7  # gone from the results for at least this many days, then back: a relisting


def _dates(entry, saved=False):
    """Separate days the entry was seen in search results (saved=True: days a saved copy was removed instead)."""
    out = set()
    for s in sightings(entry):
        if (str(s.get("search")).lower() == "saved") != saved:
            continue
        d = to_date(s.get("date"))  # malformed or missing dates are skipped (paths.to_date)
        if d:
            out.add(d)
    return sorted(out)


def _search_id(name):
    """'S2 v4' -> 'S2': versions of one search count as the same search."""
    return str(name or "").split()[0].upper() if name else ""


def watch(entries):
    """Per listing: separate days seen, span, whether it went away and came back, a 'Reposted' label, and
    salaries seen. Listings with no company or a whole-company ('*') entry are left out.

    'Gone and back' needs proof it was gone: a gap of RESURFACE_GAP+ days during which a search that found the
    listing ran without it. A gap that only means the search wasn't run is not a relisting."""
    runs = {}  # search id -> dates it ran (from every sighting on record)
    for e in entries:
        for s in sightings(e):
            d = to_date(s.get("date"))
            if d:
                runs.setdefault(_search_id(s.get("search")), set()).add(d)
    runs.pop("SAVED", None)
    rows = []
    for e in entries:
        if not e.get("company") or e.get("title") == "*":
            continue
        d = _dates(e)
        if not d:
            continue
        gone = _dates(e, saved=True)
        mine = {_search_id(s.get("search")) for s in sightings(e)} - {"SAVED"}
        ran = set().union(*(runs.get(m, set()) for m in mine)) if mine else set()
        gaps = [(b - a).days for a, b in zip(d, d[1:]) if any(a < r < b for r in ran)]
        salaries = []
        for s in sightings(e):
            v = s.get("salary")
            if isinstance(v, str) and v.strip() and norm_terms(v) not in {norm_terms(x) for x in salaries}:
                salaries.append(v)
        rows.append({
            "entry": e, "days": len(d), "first": d[0], "last": d[-1], "span": (d[-1] - d[0]).days,
            "resurfaced": any(g >= RESURFACE_GAP for g in gaps),
            # A saved copy was removed (closed, DQ'd), and the listing showed up in search results after that:
            # the latest such removal before the last sighting.
            "after_removal": max((g for g in gone if g < d[-1]), default=None),
            "reposted": any("repost" in str(s.get("posted", "")).lower() for s in sightings(e)),
            "salaries": salaries,
        })
    for r in rows:
        r["evergreen"] = r["days"] >= EVERGREEN_DATES and r["span"] >= EVERGREEN_DAYS
    return rows


def reposts():
    """Repost watch: write 2-reports/repost-watch.md from the sightings in triaged.json.

    Relisting is mostly in good faith (evergreen roles, several openings, a refreshed date, a failed search), but a
    listing that never goes away can be a pipeline or ghost posting, and a company that reposts constantly may be
    collecting profiles. This only reports patterns; it never removes or skips anything by itself."""
    db = load()
    add_tombstones(db["entries"], only_new=True)  # removals since the last seed show as DQ'd here too
    rows = watch(db["entries"])
    if not rows:
        print("No dated sightings in triaged.json yet.")
        return
    first = min(r["first"] for r in rows)
    last = max(r["last"] for r in rows)
    history = (last - first).days
    ever = sorted([r for r in rows if r["evergreen"]], key=lambda r: (-r["span"], -r["days"]))
    back = sorted([r for r in rows if r["resurfaced"] and not r["evergreen"]], key=lambda r: -r["span"])
    paid = [r for r in rows if len(r["salaries"]) > 1]
    again = sorted([r for r in rows if r["after_removal"]], key=lambda r: r["after_removal"])
    comp = {}
    for r in rows:
        c = comp.setdefault(norm_company(r["entry"]["company"]), {"name": r["entry"]["company"], "listings": 0,
                                                                  "back": 0, "reposted": 0})
        c["listings"] += 1
        c["back"] += r["resurfaced"] or r["evergreen"]
        c["reposted"] += r["reposted"]
    comps = sorted([c for c in comp.values() if c["back"] or c["reposted"] >= 2],
                   key=lambda c: (-c["back"], -c["reposted"], -c["listings"]))
    current = {}
    for f in sorted(P.jobs.glob("*.json")):
        j = read_json(f)
        current[key(j.get("company", ""), j.get("title", ""))] = j
    cur_ever = [r for r in ever if key(r["entry"]["company"], r["entry"]["title"]) in current]

    def name(r):
        e = r["entry"]
        return f"{e['company']}: {e['title']}"

    L = ["# Repost watch", "",
         f"*Built {datetime.date.today().isoformat()} from {len(rows)} listings in triaged.json, sighted "
         f"{first.isoformat()} to {last.isoformat()} ({history} days). Rebuilt each round "
         "(`python engine/triaged.py reposts`).*", "",
         "Relisting is usually in good faith: an evergreen role, several openings, a refreshed date or a failed search. "
         "A listing that never goes away can also be a pipeline or ghost posting, and a company that relists "
         "constantly may be collecting profiles. This page only shows patterns; nothing is removed or skipped "
         "because of it.", ""]
    if history < EVERGREEN_DAYS:
        L += [f"**Too early to judge:** the sightings cover {history} days, under the {EVERGREEN_DAYS} needed to call "
              "anything evergreen. Listings seen on several dates so far are mostly the same live posting turning up "
              "in different searches.", ""]
    L += [f"## Current jobs that look evergreen ({len(cur_ever)})", "",
          f"Saved jobs whose company and title have shown up on {EVERGREEN_DATES}+ separate days across "
          f"{EVERGREEN_DAYS}+ days. Worth a staleness check before any kit work.", ""]
    L += [f"- {name(r)}: {r['days']} days seen over {r['span']} days ({r['first']} to {r['last']})" for r in cur_ever] \
        or ["None."]
    L += ["", f"## Evergreen listings ({len(ever)})", "",
          f"Seen on {EVERGREEN_DATES}+ separate days across {EVERGREEN_DAYS}+ days.", ""]
    if ever:
        L += ["| Listing | Decision | Days seen | Span | First | Last | Reposted label |", "|---|---|---|---|---|---|---|"]
        L += [f"| {name(r)} | {r['entry']['decision']} | {r['days']} | {r['span']}d | {r['first']} | {r['last']} | "
              f"{'yes' if r['reposted'] else ''} |" for r in ever]
    else:
        L += ["None yet."]
    L += ["", f"## Gone and back ({len(back)})", "",
          f"Missing from the results for {RESURFACE_GAP}+ days, then seen again.", ""]
    L += [f"- {name(r)} ({r['entry']['decision']}): {r['first']} to {r['last']}" for r in back] or ["None yet."]
    L += ["", f"## Removed, then listed again ({len(again)})", "",
          "A saved copy was removed from the project (closed, DQ'd or a duplicate), and the same company and title "
          "showed up in search results later: a relisting under a new job ID, or the same posting still up "
          "(a card shows no job ID, so open it to tell).", ""]
    L += [f"- {name(r)} ({r['entry']['decision']}): removed {r['after_removal']}, seen again {r['last']}"
          for r in again] or ["None yet."]
    L += ["", f"## Salary changed between sightings ({len(paid)})", "",
          "The same company and title shown with different pay (or one posting at several levels). "
          "A DQ'd listing back with new terms is also flagged at triage (`triaged.py check`).", ""]
    L += [f"- {name(r)} ({r['entry']['decision']}): " + " / ".join(r["salaries"]) for r in paid] or ["None yet."]
    L += ["", f"## Companies that relist ({len(comps)})", "",
          "Companies with listings that came back or stayed up, or two or more 'Reposted' labels.", ""]
    if comps:
        L += ["| Company | Listings seen | Came back or evergreen | Reposted labels |", "|---|---|---|---|"]
        L += [f"| {c['name']} | {c['listings']} | {c['back']} | {c['reposted']} |" for c in comps[:25]]
    else:
        L += ["None yet."]
    out = P.reports / "repost-watch.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Repost watch: {len(ever)} evergreen ({len(cur_ever)} among current jobs), {len(back)} gone and back, "
          f"{len(again)} listed again after removal, "
          f"{len(paid)} with changed pay, {len(comps)} companies; history {history} days -> {P.rel(out)}")


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
    elif cmd == "reposts" and len(sys.argv) == 2:
        reposts()
    else:
        print(__doc__)
