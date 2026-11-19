"""Ingest a job description from outside LinkedIn as a regular job record (external-job path, v1, 2026-11-18).

Usage:
  python engine/ingest_external.py <description file> --id ext-<slug> --company "..." --title "..."
         [--location "Springfield, IL"] [--workplace Remote|Hybrid|On-site] [--employment Full-time|Contract|...]
         [--source "Acme Staffing (recruiter, via referral)"] [--status "interviewing"] [--stage "round 2 on 2026-01-15"]
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
import zipfile
from pathlib import Path
from urllib.parse import quote

from paths import Paths

SALARY = re.compile(r"\$\s?\d[\d,.]*\s?[Kk]?(?:\s?(?:-|–|to)\s?\$\s?\d[\d,.]*\s?[Kk]?)?")


def read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        xml = zipfile.ZipFile(io.BytesIO(path.read_bytes())).read("word/document.xml").decode("utf-8")
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
    ap.add_argument("--status", default=None, help="pipeline status, e.g. interviewing")
    ap.add_argument("--stage", default=None)
    ap.add_argument("--pay", default=None)
    ap.add_argument("--data", default=None)
    a = ap.parse_args()
    if not a.id.startswith("ext-"):
        raise SystemExit("External job IDs start with 'ext-' so they never collide with LinkedIn job IDs.")
    P = Paths(a.data)
    src = Path(a.file).resolve()
    key = P.rel(src)
    text = read_text(src)
    out = P.jobs / f"{a.id}.json"
    rec = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    now = dt.datetime.now().isoformat(timespec="seconds")
    rec.update({
        "job_id": a.id,
        "url": "../" + quote(key),  # relative to 2-reports/, where the report links it
        "list": "saved",
        "external": True,
        "source": a.source,
        "source_files": sorted(set(rec.get("source_files", [])) | {key}),
        "title": a.title, "company": a.company, "location": a.location,
        "posted": None, "applicants": None,
        "workplace": a.workplace or rec.get("workplace"),
        "employment_type": a.employment,
        "network_teaser": [], "posting_text": text, "company_text": "", "company_meta": None,
        "salary_mentions": SALARY.findall(text) or ([a.pay] if a.pay else []),
        "truncated": False, "leads": [], "main_file": key, "printed": None,
        "extracted_at": now,
    })
    if a.status or a.stage:
        rec["pipeline"] = {"status": a.status, "stage": a.stage, "updated": now[:10]}
    rec.setdefault("connections_1st", [])
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    ledger = json.loads(P.ledger.read_text(encoding="utf-8")) if P.ledger.exists() else {}
    st = src.stat()
    ledger[key] = {"job_id": a.id, "kind": "external", "sig": {"size": st.st_size, "mtime": int(st.st_mtime)},
                   "processed_at": now}
    P.ledger.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"external {a.id}  {key}  ({len(text)} chars) -> {P.rel(out)}")
    print("Next: review it (engine/prompts/review-rubric.md) in the current round's reviews file, then rebuild the report.")


if __name__ == "__main__":
    main()
