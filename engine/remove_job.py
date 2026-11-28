"""Remove a job from the project entirely.

Usage:  python engine/remove_job.py <job_id> [<job_id> ...] --reason "travel 50%" [--data my-data] [--no-tombstone]

Deletes:  jobs/<id>.json, its entries in reviews/*.json and ledger.json, and any source PDFs still in
          1-inbox/job-pdfs/ (or the retired rejected-jobs/, if present).
Keeps:    a one-line tombstone in removed.json (job ID, company, title, date, reason) so a later re-save,
          a discovered duplicate or a search-results card (engine/triaged.py) is recognized instead of re-reviewed. Skip with --no-tombstone.
Reports, spec evidence, skills-gap entries and calibration questions that mention the job are cleaned
by the judgment step and the next build_report.py run.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import re
import sys

from paths import Paths, is_score, latest_reviews, write_json, read_json


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("job_ids", nargs="+")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--data", default=None)
    ap.add_argument("--no-tombstone", action="store_true")
    ap.add_argument("--confirm-connections", action="store_true",
                    help="the user has confirmed removing jobs that have a 1st-degree connection")
    args = ap.parse_args()
    P = Paths(args.data)
    data = P.data

    ledger_p = P.ledger
    # Both are checked up front, so a damaged file stops the removal before anything has changed.
    ledger = read_json(ledger_p, {}, expect=dict)
    tomb_p = P.removed
    tombs = read_json(tomb_p, [], expect=list)

    # Jobs with a 1st-degree connection are never removed automatically: every job in the batch is checked before
    # anything changes, and the connections are named, so the user confirms with them in view.
    for jid in args.job_ids:
        if not re.fullmatch(r"[\w-]+", jid):
            sys.exit(f"Not a job ID: {jid!r}")
    import connections
    import recommendations
    people = connections.load(P)
    recs = recommendations.load(P)
    reviews = latest_reviews(P)
    held = []
    for jid in args.job_ids:
        rec = read_json(P.jobs / f"{jid}.json", {}, expect=dict)
        named = [n for n, _ in connections.people_at(dict(rec, job_id=jid), recs, people)]
        if not named:
            # A connection recorded only as the review's bonus (a referral noted by hand, or a connection whose list
            # wasn't captured): the report shows it as a connection, so it holds the removal as well.
            bonus = (reviews[jid][0] if jid in reviews else rec.get("review") or {}).get("network_bonus")
            if is_score(bonus) and bonus > 0:
                named = [f"the review records a connection bonus (+{bonus:g}) with no name"]
        if not named:
            # No connection recorded for this job, but the posting's own teaser points to one (the connection list
            # wasn't captured, and nobody is tied to the job in connections.json): that holds the removal too.
            named = [f"the posting's teaser says '{t}' (no connection recorded for this job)"
                     for t in connections.teaser_hints(rec)]
        if named:
            held.append(f"{rec.get('company') or jid} - {rec.get('title') or ''} ({jid}): {', '.join(named)}")
    if held and not args.confirm_connections:
        sys.exit("Not removed: these jobs have a 1st-degree connection, which is never removed automatically.\n  "
                 + "\n  ".join(held) + "\nAsk the user; on a yes, rerun with --confirm-connections.")
    for h in held:
        print(f"Removing with the user's confirmation; connection: {h}")
    # Every review file is read once before anything changes (the removal loop rewrites them).
    review_files = {rv: read_json(rv, expect=dict) for rv in sorted(P.reviews.glob("*.json"))}
    # An ID the project has never held is a typo: stopping here keeps a tombstone for a job that doesn't exist out
    # of removed.json, where it would later flag a real job with that ID as "previously removed". A job removed
    # earlier (tombstone, nothing else left) is simply reported as done.
    owned = {v.get("job_id") for v in ledger.values() if isinstance(v, dict)}
    gone = {t.get("job_id") for t in tombs if isinstance(t, dict)}
    unknown = [j for j in args.job_ids if not (P.jobs / f"{j}.json").exists() and j not in reviews
               and j not in owned and j not in gone
               and not any(j in (r.get("jobs") or {}) for r in review_files.values())]
    if unknown:
        sys.exit(f"No such job: {', '.join(unknown)} (no job record, review or ledger entry, and never removed "
                 f"before). Nothing was changed; check the job ID.")

    for jid in args.job_ids:
        done = []
        rec_p = P.jobs / f"{jid}.json"
        label = jid
        rec = read_json(rec_p, {}, expect=dict)  # a damaged record stops here, before anything has changed
        company, title, pipeline = rec.get("company"), rec.get("title"), rec.get("pipeline")
        if rec:
            label = f"{company} - {title} ({jid})"
        # Only files inside the saved-PDF inbox are ever deleted; anything else in source_files is left alone.
        # A file the ledger now ties to another job is that job's: LinkedIn names a PDF after the title and company,
        # so a location twin or a repost saved over this job's file has the same name.
        pdfs, refused, others = [], [], []
        for f in rec.get("source_files", []):
            owner = (ledger.get(f) or {}).get("job_id") if isinstance(ledger.get(f), dict) else None
            if not P.inside(data / f, P.job_pdfs):
                refused.append(f)
            elif owner and owner != jid:
                others.append(f"{f} (now job {owner})")
            else:
                pdfs.append(f)
        # The tombstone is written first, so an interrupted removal is still recognized and can be rerun.
        today = dt.date.today().isoformat()
        prior = next((t for t in reversed(tombs) if isinstance(t, dict) and t.get("job_id") == jid), None)
        if not args.no_tombstone and prior is None:
            tomb = {"job_id": jid, "removed": today, "reason": args.reason}
            if company:
                tomb.update(company=company, title=title)
            if pipeline:  # keep application history so engine/pipeline.py's outcome funnel still counts it
                tomb["pipeline"] = pipeline
            tombs.append(tomb)
            write_json(tomb_p, tombs)
        elif (not args.no_tombstone and rec and (prior.get("reason") != args.reason or prior.get("removed") != today)):
            # Removed before, saved again and now removed again: the tombstone takes this removal's date, reason
            # and application history (one tombstone per job, so nothing counts it twice), and keeps the earlier
            # removal in "earlier". A rerun of an interrupted removal (same day, same reason) changes nothing.
            prior.setdefault("earlier", []).append({"removed": prior.get("removed"), "reason": prior.get("reason")})
            prior.update(removed=today, reason=args.reason)
            if company:
                prior.update(company=company, title=title)
            if pipeline:
                prior["pipeline"] = pipeline
            write_json(tomb_p, tombs)
            done.append("tombstone updated (removed before)")
        if not rec and prior is not None and jid not in owned and jid not in reviews:
            print(f"{jid}: already removed ({prior.get('removed')}: {prior.get('reason')})")
            continue
        for rv in review_files:
            r = read_json(rv, expect=dict)
            if jid in r.get("jobs", {}):
                del r["jobs"][jid]
                write_json(rv, r)
                done.append(f"review {rv.name}")
        for key in [k for k, v in ledger.items() if isinstance(v, dict) and v.get("job_id") == jid]:
            del ledger[key]
            done.append(f"ledger entry {key}")
        write_json(ledger_p, ledger)
        locked = []
        for f in pdfs:
            if (data / f).exists():
                try:
                    (data / f).unlink()
                    done.append(f"deleted {f}")
                except OSError as e:  # e.g. open in a PDF viewer (Windows won't delete an open file)
                    locked.append(f"{f} ({e.strerror or e})")
        if locked:
            # The job record is kept, so rerunning finds the remaining PDFs; the tombstone is already in place.
            print(f"{label}: " + ", ".join(done))
            sys.exit(f"Could not delete: {'; '.join(locked)}. Close the file (e.g. in a PDF viewer) and rerun the "
                     f"same command to finish the removal.")
        if rec_p.exists():
            rec_p.unlink()
            done.append("deleted job record")
        for f in refused:
            done.append(f"LEFT ALONE (outside {P.rel(P.job_pdfs)}): {f}")
        for f in others:
            done.append(f"LEFT ALONE (belongs to another job): {f}")
        print(f"{label}: " + (", ".join(done) or "nothing found"))


if __name__ == "__main__":
    main()
