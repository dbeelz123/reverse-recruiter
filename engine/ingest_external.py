"""Ingest a job description from outside LinkedIn as a regular job record (external-job path, v1, 2026-11-18).

Usage:
  python engine/ingest_external.py <description file> --id ext-<slug> --company "..." --title "..."
         [--location "Springfield, IL"] [--workplace Remote|Hybrid|On-site] [--employment Full-time|Contract|...]
         [--source "Acme Staffing (recruiter, via referral)"] [--status interview] [--stage "round 2 on 2026-01-15"]
         [--pay "..."] [--data my-data]

Input: .docx, .pdf or .txt/.md, anywhere under the data folder (usually the kit folder in 3-applications/).
Output: 6-system/jobs/<id>.json with the same fields extract.py writes for a LinkedIn PDF, plus:
  external: true, source, pipeline {status, stage}, and url = a relative link to the description file
  (from 2-reports/, so the report's job links open it).
The record then goes through the normal round steps: review (rubric), re-screen, metrics, report, kit.
1st-degree connections are LinkedIn-only: add them by hand to connections_1st if the user names them.
Re-running updates the record and keeps any fields set by hand (connections, workplace notes).
"""
import argparse
import datetime as dt
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

from paths import Paths, read_json, removed_before, write_json

SALARY = re.compile(r"\$\s?\d[\d,.]*\s?[Kk]?(?:\s?(?:-|–|to)\s?\$\s?\d[\d,.]*\s?[Kk]?)?")


def read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        try:
            xml = zipfile.ZipFile(io.BytesIO(path.read_bytes())).read("word/document.xml").decode("utf-8")
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
            sys.exit(f"Can't read {path} as a Word document ({e}). Re-save it from Word as .docx, or save the "
                     f"description as .txt, and rerun.")
        out = []
        for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
            p = re.sub(r"<w:br[^>]*/>", "<w:t>\n</w:t>", p)  # a line break inside a paragraph ("About the role" heading)
            p = re.sub(r"<w:tab/>", "<w:t> </w:t>", p)
            t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
            t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            if t.strip():
                out.append(("- " if "<w:numPr>" in p else "") + t.strip())
        return "\n".join(out)
    if ext == ".pdf":
        import pymupdf
        return "\n".join(p.get_text(sort=True) for p in pymupdf.open(path)).strip()
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8").strip()
    raise SystemExit(f"Unsupported file type {ext}: use .docx, .pdf, .txt or .md")


def pay_mentions(text, pay, stored):
    """Pay figures for the record: the --pay option first (kept from an earlier run when left out now), then
    figures in the description that read as annual or hourly pay."""
    def is_pay(s):  # as extract.looks_like_pay: "$150K", "$120,000", "$65/hr"; not "$3 billion" or "$50 stipend"
        nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]
        return bool(nums) and (bool(re.search(r"\d\s?[Kk]\b", s)) or max(nums) >= 20000 or "/hr" in s)
    found = [m.strip(" .") for m in SALARY.findall(text) if is_pay(m)]
    given = [pay] if pay else [s for s in (stored or []) if isinstance(s, str) and s not in found]
    return list(dict.fromkeys(given + found))


from pipeline import STAGES, TERMINAL, OTHER  # noqa: E402

STATUSES = STAGES + OTHER + TERMINAL


def normalize(argv):
    """Accept the older spelling '--status interviewing' and store the pipeline's own name, 'interview'."""
    return ["interview" if x == "interviewing" and i and argv[i - 1] == "--status" else x for i, x in enumerate(argv)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--id", required=True, help="stable ID, e.g. ext-acme-clinical-ai-pm")
    ap.add_argument("--company", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--location", default=None)
    ap.add_argument("--workplace", default=None, choices=["Remote", "Hybrid", "On-site"])
    ap.add_argument("--employment", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--status", default=None, choices=STATUSES,
                    help="pipeline status (engine/pipeline.py stages), e.g. interview")
    ap.add_argument("--stage", default=None)
    ap.add_argument("--pay", default=None)
    ap.add_argument("--data", default=None)
    a = ap.parse_args(normalize(sys.argv[1:]))
    # The ID becomes a file name (6-system/jobs/<id>.json), so it can't carry a path: no separators or dots.
    if not re.fullmatch(r"ext-[A-Za-z0-9_-]+", a.id):
        raise SystemExit("External job IDs start with 'ext-' (so they never collide with LinkedIn job IDs), followed "
                         f"by letters, digits, hyphens or underscores, e.g. ext-acme-clinical-ai-pm; got {a.id!r}.")
    P = Paths(a.data)
    src = Path(a.file).resolve()
    if not src.is_file():
        raise SystemExit(f"No such file: {src}")
    if not P.inside(src):
        raise SystemExit(f"{src} is outside the data folder ({P.data}). Put the description in the job's kit folder "
                         f"(3-applications/<company-role>/) first, so the report can link to it.")
    P.jobs.mkdir(parents=True, exist_ok=True)
    key = P.rel(src)
    text = read_text(src)
    out = P.jobs / f"{a.id}.json"
    # Both are checked before anything is written, so a damaged file stops the ingest with the file named.
    rec = read_json(out, {}, expect=dict)
    ledger = read_json(P.ledger, {}, expect=dict)
    now = dt.datetime.now().isoformat(timespec="seconds")
    rec.update({
        "job_id": a.id,
        "url": "../" + quote(key),  # relative to 2-reports/, where the report links it
        "list": "saved",
        "external": True,
        # An option left out on a re-run keeps the stored value (as workplace always did): re-ingesting to record
        # a new status must not erase the location, source or employment type given the first time.
        "source": a.source or rec.get("source"),
        "source_files": sorted(set(rec.get("source_files", [])) | {key}),
        "title": a.title, "company": a.company, "location": a.location or rec.get("location"),
        "posted": None, "applicants": None,
        "workplace": a.workplace or rec.get("workplace"),
        "employment_type": a.employment or rec.get("employment_type"),
        "network_teaser": [], "posting_text": text, "company_text": "", "company_meta": None,
        # --pay always counts; figures in the text count only when they read as pay ("$3 billion company" doesn't).
        "salary_mentions": pay_mentions(text, a.pay, rec.get("salary_mentions")),
        "truncated": False, "leads": [], "main_file": key, "printed": None,
        "extracted_at": now,
    })
    if a.status or a.stage:  # merge: re-ingesting never erases recorded events or the next step
        pl = rec.setdefault("pipeline", {})
        pl.update({k: v for k, v in (("status", a.status), ("stage", a.stage)) if v})
        pl["updated"] = now[:10]
    rec.setdefault("connections_1st", [])
    before = removed_before(P.removed, a.id)  # this ID was removed earlier: ingest it, but flag it for the user
    if before:
        rec["previously_removed"] = {"removed": before.get("removed"), "reason": before.get("reason")}
    write_json(out, rec, indent=2)
    if before:
        print(f"PREVIOUSLY REMOVED: {a.id} was removed {before.get('removed')}: {before.get('reason')}. "
              f"Ask the user before reviewing it again.")
    st = src.stat()
    ledger[key] = {"job_id": a.id, "kind": "external", "sig": {"size": st.st_size, "mtime": int(st.st_mtime)},
                   "processed_at": now}
    write_json(P.ledger, ledger, indent=2)
    print(f"external {a.id}  {key}  ({len(text)} chars) -> {P.rel(out)}")
    print("Next: review it (engine/prompts/review-rubric.md) in the current round's reviews file, then rebuild the report.")


if __name__ == "__main__":
    main()
