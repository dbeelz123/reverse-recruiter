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

from paths import Paths, write_json, read_json


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("job_ids", nargs="+")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--data", default=None)
    ap.add_argument("--no-tombstone", action="store_true")
    args = ap.parse_args()
    P = Paths(args.data)
    data = P.data

    ledger_p = P.ledger
    ledger = read_json(ledger_p, {})
    tomb_p = P.removed
    tombs = read_json(tomb_p, [])

    for jid in args.job_ids:
        if not re.fullmatch(r"[\w-]+", jid):
            sys.exit(f"Not a job ID: {jid!r}")
        done = []
        rec_p = P.jobs / f"{jid}.json"
        label = jid
        rec = read_json(rec_p, {})
        company, title, pipeline = rec.get("company"), rec.get("title"), rec.get("pipeline")
        if rec:
            label = f"{company} - {title} ({jid})"
        # Only files inside the saved-PDF inbox are ever deleted; anything else in source_files is left alone.
        pdfs, refused = [], []
        for f in rec.get("source_files", []):
            (pdfs if P.inside(data / f, P.job_pdfs) else refused).append(f)
        # The tombstone is written first, so an interrupted removal is still recognized and can be rerun.
        if not args.no_tombstone and not any(t["job_id"] == jid for t in tombs):
            tomb = {"job_id": jid, "removed": dt.date.today().isoformat(), "reason": args.reason}
            if company:
                tomb.update(company=company, title=title)
            if pipeline:  # keep application history so engine/pipeline.py's outcome funnel still counts it
                tomb["pipeline"] = pipeline
            tombs.append(tomb)
            write_json(tomb_p, tombs)
        for rv in sorted(P.reviews.glob("*.json")):
            r = read_json(rv)
            if jid in r.get("jobs", {}):
                del r["jobs"][jid]
                write_json(rv, r)
                done.append(f"review {rv.name}")
        for key in [k for k, v in ledger.items() if v.get("job_id") == jid]:
            del ledger[key]
            done.append(f"ledger entry {key}")
        write_json(ledger_p, ledger)
        for f in pdfs:
            if (data / f).exists():
                (data / f).unlink()
                done.append(f"deleted {f}")
        if rec_p.exists():
            rec_p.unlink()
            done.append("deleted job record")
        for f in refused:
            done.append(f"LEFT ALONE (outside {P.rel(P.job_pdfs)}): {f}")
        print(f"{label}: " + (", ".join(done) or "nothing found"))


if __name__ == "__main__":
    main()
