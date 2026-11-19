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

from paths import Paths


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
    ledger = json.loads(ledger_p.read_text(encoding="utf-8")) if ledger_p.exists() else {}
    tomb_p = P.removed
    tombs = json.loads(tomb_p.read_text(encoding="utf-8")) if tomb_p.exists() else []

    for jid in args.job_ids:
        done = []
        rec_p = P.jobs / f"{jid}.json"
        label = jid
        company = title = rec_p_pipeline = None
        if rec_p.exists():
            rec = json.loads(rec_p.read_text(encoding="utf-8"))
            company, title, rec_p_pipeline = rec.get("company"), rec.get("title"), rec.get("pipeline")
            label = f"{company} - {title} ({jid})"
            for f in rec.get("source_files", []):
                pdf = data / f
                if pdf.exists():
                    pdf.unlink()
                    done.append(f"deleted {f}")
            rec_p.unlink()
            done.append("deleted job record")
        for key in [k for k, v in ledger.items() if v.get("job_id") == jid]:
            del ledger[key]
            done.append(f"ledger entry {key}")
        for rv in sorted(P.reviews.glob("*.json")):
            r = json.loads(rv.read_text(encoding="utf-8"))
            if jid in r.get("jobs", {}):
                del r["jobs"][jid]
                rv.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
                done.append(f"review {rv.name}")
        if not args.no_tombstone and not any(t["job_id"] == jid for t in tombs):
            tomb = {"job_id": jid, "removed": dt.date.today().isoformat(), "reason": args.reason}
            if company:
                tomb.update(company=company, title=title)
            if rec_p_pipeline:  # keep application history so engine/pipeline.py's outcome funnel still counts it
                tomb["pipeline"] = rec_p_pipeline
            tombs.append(tomb)
        print(f"{label}: " + (", ".join(done) or "nothing found"))

    ledger_p.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    if not args.no_tombstone:
        tomb_p.write_text(json.dumps(tombs, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
