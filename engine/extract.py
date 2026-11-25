"""Extract structured job records from LinkedIn job pages saved as PDF.

Usage:  python engine/extract.py [--data my-data] [--all]

Reads   <data>/1-inbox/job-pdfs/*.pdf (top level only; archive/ is ignored). Locations: engine/paths.py.
Writes  <data>/6-system/jobs/<job_id>.json   (one record per job; an existing "review" block is preserved)
        <data>/6-system/ledger.json          (which files were processed; only new/changed files run unless --all)

Requires: pymupdf  (pip install pymupdf)
Only reads local files; never touches LinkedIn.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

from paths import Paths, read_json, write_json, tombstones

import pymupdf

PAGE_HEADER = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2}\s*[AP]M\b")
PAGE_FOOTER = re.compile(r"^\s*https://www\.linkedin\.com/\S+\s+\d+/\d+\s*$")
LOOSE_HEADER = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2},")
FOOTER_TAIL = re.compile(r"\s*https://www\.linkedin\.com/\S+(?:\s+\d+/\d+)?\s*$")
JOB_URL = re.compile(r"https://www\.linkedin\.com/jobs/view/(\d+)/")
PRINT_DATE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2})")
# Name, optionally followed by credentials after a comma ("Jane Doe, M.S."), then the degree marker.
PERSON = re.compile(r"^\s*([A-Z][\w.'\-]+(?: [A-Z][\w.'\-]+){1,3})(?:,\s*[\w.\-]+(?:\s[\w.\-]+){0,2})?\s*[•·]\s*(1st|2nd|3rd)\b")
WORKPLACE = ("Remote", "Hybrid", "On-site")
EMPLOYMENT = ("Full-time", "Part-time", "Contract", "Temporary", "Internship")
SALARY = re.compile(r"\$\s?\d[\d,.]*\s?[Kk]?(?:\s?(?:/yr|/hr|per year|per hour|USD))?"
                    r"(?:\s?(?:-|–|to)\s?\$\s?\d[\d,.]*\s?[Kk]?(?:\s?(?:/yr|/hr|per year|per hour|USD))?)?")
LEAD_END = ("See more jobs like this", "Job search smarter with Premium", "Looking for talent?")
JUNK_LINES = {"Message", "Connect", "Follow", "Show all", "Show more", "Saved", "Apply", "Easy Apply"}


def page_lines(pdf: Path):
    """Text in reading order with LinkedIn's print header/footer lines removed."""
    with pymupdf.open(pdf) as doc:  # closed even when a page fails to read
        raw = "\n".join(p.get_text(sort=True) for p in doc)
    job_id = (JOB_URL.search(raw) or [None, None])[1]
    m = PRINT_DATE.search(raw)
    printed = m.group(1) if m else None
    # The browser's print header carries "Title | Company | LinkedIn" on one line, even when the
    # on-page title wraps, so it is the most reliable source for title and company.
    title_company = None
    for ln in raw.splitlines():
        if PAGE_HEADER.match(ln):
            parts = [p.strip() for p in re.split(r"\s{2,}", ln.strip(), maxsplit=1)[-1].split(" | ")]
            if len(parts) >= 3 and parts[-1] == "LinkedIn":
                title_company = (" | ".join(parts[:-2]), parts[-2])
            break
    lines = []
    for ln in raw.splitlines():
        # The print header often overlaps body text, so match it loosely: any line that starts with the
        # print date ("11/17/26,") is a header (2026-11-17: 26 leaked headers found in posting_text).
        if PAGE_HEADER.match(ln) or LOOSE_HEADER.match(ln) or PAGE_FOOTER.match(ln):
            continue
        m = FOOTER_TAIL.search(ln)
        if m:  # footer URL (+ page number) printed on the same line as body text
            ln = ln[:m.start()]
            if not re.search(r"[A-Za-z]{3}", ln):  # only stray glyphs were left ("O       i")
                continue
        lines.append(ln.rstrip())
    return job_id, printed, title_company, lines


def is_garbled(line: str) -> bool:
    """Lines split across a page break print as fragments like 'D fi th d t i i'."""
    toks = line.split()
    return len(toks) >= 5 and sum(len(t) <= 2 for t in toks) / len(toks) > 0.6


def clean(lines):
    out, blank = [], False
    for ln in lines:
        s = ln.strip()
        if not s:
            if not blank and out:
                out.append("")
            blank = True
            continue
        if is_garbled(s):
            continue
        out.append(s)
        blank = False
    return "\n".join(out).strip()


def looks_like_pay(s: str) -> bool:
    """Keep annual/hourly pay figures; drop things like '$175B market' or '$50 stipend'."""
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]
    if not nums:
        return False
    if re.search(r"\d\s?[Kk]\b", s):
        return True
    return max(nums) >= 20000 or ("/hr" in s or "per hour" in s)


def find(lines, *markers, start=0):
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if any(s.startswith(m) for m in markers):
            return i
    return None


def parse_header(lines, stop):
    head = [l.strip() for l in lines[:stop] if l.strip()]
    rec = {"title": None, "company": None, "location": None, "posted": None,
           "applicants": None, "workplace": None, "employment_type": None}
    for i, s in enumerate(head):
        if " · " in s and re.search(r"ago|applicants|clicked apply", s):
            parts = [p.strip() for p in s.split(" · ")]
            rec["location"] = parts[0]
            rec["posted"] = next((p for p in parts if "ago" in p), None)
            rec["applicants"] = next((p for p in parts if re.search(r"applicants|clicked apply", p)), None)
            if i >= 1:
                rec["title"] = head[i - 1]
            if i >= 2:
                rec["company"] = head[i - 2]
            break
    tokens = " ".join(head)
    rec["workplace"] = next((w for w in WORKPLACE if re.search(rf"\b{w}\b", tokens)), None)
    rec["employment_type"] = next((e for e in EMPLOYMENT if e in tokens), None)
    # Network teaser, e.g. "John and others in your network" or a single named person
    t = find(lines[:stop], "People you can reach out to")
    teaser = []
    if t is not None:
        for s in (l.strip() for l in lines[t + 1:t + 6]):
            s = re.sub(r"\s{2,}(Message|Connect|Follow|Show all)\s*$", "", s)
            if s and s not in JUNK_LINES:
                teaser.append(s)
    rec["network_teaser"] = teaser
    return rec


def parse_leads(lines):
    """Similar-job listings from the 'More jobs' section: leads only, never preference evidence."""
    blocks, cur = [], []
    for ln in lines:
        s = ln.strip()
        if any(s.startswith(e) for e in LEAD_END):
            break
        if not s:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(s)
    if cur:
        blocks.append(cur)
    leads = []
    for b in blocks:
        is_lead = len(b) >= 3 and re.search(r"\((Remote|Hybrid|On-site)\)|,\s*[A-Z]{2}\b|United States", b[2])
        if is_lead:
            lead = {"title": b[0], "company": b[1], "location": b[2]}
            leads.append(lead)
            extras = b[3:]
        elif leads:
            lead, extras = leads[-1], b  # detail lines printed after a blank line belong to the previous lead
        else:
            continue
        for extra in extras:
            if "$" in extra:
                lead["salary"] = extra.split(" • ")[0]
            if re.search(r"\bconnections? works? here", extra):
                lead["connections_note"] = extra
            if extra.startswith("Promoted") or "ago" in extra:
                lead["posted"] = extra
    return leads


def parse_main(lines):
    a = find(lines, "About the job")
    if a is None:
        return None
    rec = parse_header(lines, a)
    end = find(lines, "Set alert for similar jobs", "About the company", start=a)
    rec["posting_text"] = clean(lines[a + 1:end])
    c = find(lines, "About the company", start=a)
    mj = find(lines, "More jobs", start=c or a)
    company = clean(lines[c + 1:mj]) if c is not None else ""
    rec["company_text"] = company
    rec["company_meta"] = next((l for l in company.splitlines() if "employees" in l), None)
    flat = re.sub(r"\s+", " ", rec["posting_text"])
    rec["salary_mentions"] = sorted(set(m.group(0).strip(" .") for m in SALARY.finditer(flat)
                                        if looks_like_pay(m.group(0))))
    # A collapsed description ("See more" not expanded before printing) ends in an ellipsis.
    tail = rec["posting_text"][-40:]
    rec["truncated"] = bool(re.search(r"…\s*(mo\w*…?)?\s*$|\.\.\.\s*$", tail)) or len(flat.split()) < 150
    rec["leads"] = parse_leads(lines[mj + 1:]) if mj is not None else []
    return rec


def parse_people(lines):
    """Connections dialog: keep 1st-degree connections only (by explicit decision)."""
    people = {}
    for i, ln in enumerate(lines):
        m = PERSON.match(ln)
        if not m or m.group(2) != "1st":
            continue
        name = m.group(1)
        if name in people:
            continue
        headline = None
        for nxt in lines[i + 1:i + 3]:
            s = re.sub(r"\s{2,}.*$", "", nxt.strip())
            if s and s not in JUNK_LINES:
                headline = s
                break
        people[name] = {"name": name, "headline": headline}
    # Overlapping print layers can glue page text onto a name ("Community GuidelinesJane Doe");
    # drop any entry that merely contains another captured name.
    kept = [p for n, p in people.items() if not any(o != n and o in n for o in people)]
    # Overlapping layers can also interleave letters ("About TheJaneRoleDoe" for Jane Doe), so the name
    # isn't a plain substring. Two entries with the same headline are one person: keep the shorter name (2026-11-17).
    by_headline = {}
    for p in kept:
        h = p["headline"]
        if h and h in by_headline:
            if len(p["name"]) < len(by_headline[h]["name"]):
                by_headline[h] = p
        else:
            by_headline[h or id(p)] = p
    return list(by_headline.values())


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--data", default=None)
    ap.add_argument("--all", action="store_true", help="reprocess every file, not just new/changed ones")
    args = ap.parse_args()
    P = Paths(args.data)
    data = P.data
    jobs_dir = P.jobs
    jobs_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = P.ledger
    ledger = read_json(ledger_path, {})
    now = dt.datetime.now().isoformat(timespec="seconds")
    summary = []

    for folder, list_name in ((P.job_pdfs, "saved"),):
        if not folder.is_dir():
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            key = P.rel(pdf)
            st = pdf.stat()
            # Size plus whole-second mtime: a re-saved posting differs in at least one of them in practice, and
            # --all reprocesses everything. A content hash would change every stored signature, so every PDF
            # would be re-extracted once, for a same-size, same-second replacement that manual saving doesn't produce.
            sig = {"size": st.st_size, "mtime": int(st.st_mtime)}
            if not args.all and isinstance(ledger.get(key), dict) and ledger[key].get("sig") == sig:
                continue
            try:
                job_id, printed, title_company, lines = page_lines(pdf)
            except Exception as e:  # damaged, password-protected or not really a PDF
                summary.append(f"SKIP (unreadable PDF: {type(e).__name__}: {e}): {key}")
                continue
            if not job_id:
                summary.append(f"SKIP (no job URL found): {key}")
                continue
            is_people = any(l.strip().startswith("Connections who work at") for l in lines)
            out = jobs_dir / f"{job_id}.json"
            rec = read_json(out, {})
            rec.setdefault("job_id", job_id)
            rec["url"] = f"https://www.linkedin.com/jobs/view/{job_id}/"
            rec["list"] = list_name
            files = set(rec.get("source_files", [])) | {key}
            rec["source_files"] = sorted(files)
            if is_people:
                rec["connections_1st"] = parse_people(lines)
                rec["people_file"] = key
                kind = "people"
            else:
                main_rec = parse_main(lines)
                if main_rec is None:
                    summary.append(f"SKIP (no 'About the job' section): {key}")
                    continue
                if rec.get("main_file") and rec["main_file"] != key and (data / rec["main_file"]).exists():
                    # Same job saved twice: keep whichever copy has the fuller description.
                    keep_old = len(rec.get("posting_text") or "") >= len(main_rec["posting_text"])
                    summary.append(f"DUPLICATE job {job_id}: {key} and {rec['main_file']} "
                                   f"(using {'the earlier' if keep_old else 'this'} copy)")
                    if keep_old:
                        ledger[key] = {"job_id": job_id, "kind": "main-duplicate", "sig": sig, "processed_at": now}
                        rec["source_files"] = sorted(files)
                        write_json(out, rec, indent=2)
                        continue
                if main_rec.get("workplace") is None and rec.get("workplace"):
                    # The page shows no workplace chip; keep the one set or confirmed earlier (e.g. a job confirmed remote
                    # outside the PDF). Re-extraction must never erase it (2026-11-17).
                    main_rec["workplace"] = rec["workplace"]
                rec.update(main_rec)
                if title_company:
                    rec["title"], rec["company"] = title_company
                rec["main_file"] = key
                rec["printed"] = printed
                kind = "main"
            rec.setdefault("connections_1st", [])
            rec["extracted_at"] = now
            write_json(out, rec, indent=2)
            ledger[key] = {"job_id": job_id, "kind": kind, "sig": sig, "processed_at": now}
            flag = "  [TRUNCATED: re-save with 'See more' expanded]" if rec.get("truncated") and kind == "main" else ""
            summary.append(f"{kind:6} {job_id}  {key}{flag}")

    write_json(ledger_path, ledger, indent=2, ensure_ascii=True)
    summary += repost_check(P, data, [s.split()[1] for s in summary if s.startswith("main ")],
                            [P.rel(p) for p in P.job_pdfs.glob("*.pdf") if dup_original(p.name)])
    print("\n".join(summary) if summary else "Nothing new to process.")


DUP_SUFFIXES = ("_possibleduplicate", "_possdup")  # the long name, or a short form for quick saves


def dup_original(name):
    """'<name>_possibleduplicate.pdf' or '<name>_possdup.pdf' -> '<name>.pdf' (keeping any folder prefix);
    None for any other file."""
    for s in DUP_SUFFIXES:
        if name.lower().endswith(s + ".pdf"):
            return name[:-len(s + ".pdf")] + ".pdf"
    return None


def repost_check(P, data, new_ids, dup_files):
    """Flag new jobs that may be a duplicate save or a repost of a job already seen.

    The user names a PDF '<LinkedIn default name>_possibleduplicate.pdf' (or the short '_possdup.pdf') when the save
    dialog says the file exists.
    Same job ID as the original file -> a duplicate save. Different job ID, same company with the same title or a
    near-identical description -> a possible repost, checked against current jobs and removed.json tombstones.
    Each new job with a match gets rec['possible_repost_of'] for the judgment step; nothing is deleted here.
    """
    import difflib
    from triaged import norm_company, norm_title

    def sim(a, b):
        a, b = (a or "")[:4000], (b or "")[:4000]
        return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 2) if a and b else 0.0

    jobs = {f.stem: read_json(f) for f in P.jobs.glob("*.json")}
    tombs = tombstones(P.removed)
    out = []
    for f in dup_files:  # name-collision saves
        orig = dup_original(f)
        dup_id = next((i for i, r in jobs.items() if f in r.get("source_files", [])), None)
        orig_id = next((i for i, r in jobs.items() if orig in r.get("source_files", [])), None)
        if dup_id and dup_id == orig_id:
            out.append(f"DUPLICATE SAVE (same job {dup_id}): {f} repeats {orig}; the copy can be deleted (the user's file: ask)")
        elif dup_id and orig_id:
            out.append(f"SAME NAME, DIFFERENT JOB: {f} is job {dup_id}, {orig} is job {orig_id}; see the repost check below")
        elif dup_id:
            out.append(f"NAME COLLISION: {f} is job {dup_id}; no current job uses {orig} (original may have been removed)")
    for jid in dict.fromkeys(new_ids):
        rec = jobs.get(jid)
        if not rec:
            continue
        co, ti, text = norm_company(rec.get("company") or ""), norm_title(rec.get("title") or ""), rec.get("posting_text")
        hits = []
        for oid, o in jobs.items():
            if oid == jid or norm_company(o.get("company") or "") != co:
                continue
            same_title = norm_title(o.get("title") or "") == ti
            s = sim(text, o.get("posting_text"))
            if same_title or s >= 0.8:
                r = o.get("review") or {}
                hits.append({"job_id": oid, "where": "current", "title": o.get("title"), "same_title": same_title,
                             "text_similarity": s, "posted": o.get("posted"), "tier": r.get("tier"), "total": r.get("total")})
        for t in tombs:
            if t.get("job_id") != jid and t.get("company") and norm_company(t["company"]) == co \
                    and norm_title(t.get("title") or "") == ti:
                hits.append({"job_id": t["job_id"], "where": "removed", "title": t.get("title"), "same_title": True,
                             "removed": t.get("removed"), "reason": t.get("reason")})
        # The same job ID removed earlier and now saved again: still extracted (a reopened posting is a fair re-save),
        # but flagged so the earlier removal reason is seen before the job is reviewed again.
        before = next((t for t in reversed(tombs) if t["job_id"] == jid), None)
        if before:
            rec["previously_removed"] = {"removed": before.get("removed"), "reason": before.get("reason")}
            out.append(f"PREVIOUSLY REMOVED: {jid} {rec.get('company')} - {rec.get('title')} was removed "
                       f"{before.get('removed')}: {before.get('reason')}. Ask the user before reviewing it again.")
        if hits:
            rec["possible_repost_of"] = hits
        if hits or before:
            write_json((P.jobs / f"{jid}.json"), rec, indent=2)
            for h in hits:
                detail = (f"current, {h['tier']} {h['total']}, text {h['text_similarity']:.0%} alike" if h["where"] == "current"
                          else f"removed {h['removed']}: {h['reason']}")
                label = "POSSIBLE REPOST" if h["same_title"] else "SAME POSTING, DIFFERENT TITLE (e.g. one role at two levels)"
                out.append(f"{label}: {jid} {rec.get('company')} - {rec.get('title')} matches {h['job_id']} ({detail})")
    return out


if __name__ == "__main__":
    main()
