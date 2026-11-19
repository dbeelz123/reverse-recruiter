"""Turn a captured LinkedIn search-results file into cards for triage.

Usage:  python engine/ingest_results.py <results file> <cards.json out>

Supported input (the only supported way to capture a search run):
  .txt / .md  LinkedIn results copied by hand from the laptop browser and pasted page after page.
              Cards are anchored on the location line (title, company, location are the first three lines).
              LinkedIn's "may not be exact matches" banner is detected and marks every later card.
  .csv        One row per card with a header row. Required columns: title, company, location.
  .json       A list of objects with the same fields.
              Optional columns/fields: salary, posted, status ("Saved; Viewed"), network, section.

CSV/JSON is the hand-off format for any other capture method the user chooses to run themselves. Such methods
are not provided or supported here, and the user is responsible for following each site's terms of use.

Output: a list of cards {n, title, company, location, workplace, salary, posted, status[], network[],
section, line, find}. find is a LinkedIn search link with title and company quoted as exact phrases. workplace is Remote / Hybrid / On-site, or "workplace unknown" when the card shows a city
only (check it; don't assume on-site). Next step: python engine/triaged.py check <cards.json>.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from paths import read_json, write_json

STATUS = ("Viewed", "Saved", "Applied", "Promoted", "Easy Apply", "Be an early applicant", "Actively reviewing applicants")
LOC = re.compile(r"\((Remote|Hybrid|On-site)\)$|^[A-Z][\w .'-]+, [A-Z]{2}$|Metropolitan Area$|^United States$|, United States$")


def is_loc(s):
    return bool(LOC.search(s)) and not re.search(r"Product|Manager|Lead|Director|Owner|Verified job", s)


def clean_title(s):
    s = re.sub(r"^Selected, ", "", s)
    m = re.match(r"^(.*?) \(Verified job\)(.*)$", s)
    if m:
        return m.group(1).strip()
    n = len(s)
    if n % 2 == 0 and s[: n // 2] == s[n // 2:]:  # LinkedIn copies the title twice
        return s[: n // 2].strip()
    return s


def find_link(title, company):
    """LinkedIn search for one listing. Title and company are quoted as exact phrases: unquoted, LinkedIn
    weights the title and often lands on another company's job."""
    q = f'"{title.replace(chr(34), "")}" "{company.replace(chr(34), "")}"'
    # Pin location (all of the US) in the URL: without it LinkedIn reuses the location from the last search, e.g. a
    # local S7 radius hid every remote job behind the Find links (2026-11-17). No date filter: a "Past month" filter
    # hid Bitwarden's older (reposted) listing the same day, and leaving it out searches any time.
    return ("https://www.linkedin.com/jobs/search/?keywords=" + quote(q, safe="")
            + "&location=United%20States&geoId=103644278")


def workplace(loc):
    for w in ("Remote", "Hybrid", "On-site"):
        if f"({w})" in loc:
            return w
    return "workplace unknown"


def parse_paste(text):
    lines = [(i + 1, l.strip()) for i, l in enumerate(text.splitlines())]
    ne = [(i, s) for i, s in lines if s and s not in ("·", "•")]
    cards, cur, section, k = [], None, "exact", 0
    while k < len(ne):
        i, s = ne[k]
        if "may not be exact matches" in s:
            section = "after banner"
            k += 1
            continue
        if (k + 2 < len(ne) and is_loc(ne[k + 2][1]) and not is_loc(s) and not is_loc(ne[k + 1][1])
                and not re.search(r"/yr|/hr|^Posted|works? here", s)):
            loc = ne[k + 2][1]
            cur = {"n": len(cards) + 1, "title": clean_title(s), "company": ne[k + 1][1], "location": loc,
                   "workplace": workplace(loc), "salary": None, "posted": None, "status": [], "network": [],
                   "section": section, "line": i}
            cards.append(cur)
            k += 3
            continue
        if cur is not None:
            if re.search(r"/yr|/hr", s):
                cur["salary"] = s
            elif s.startswith(("Posted", "Reposted")):
                cur["posted"] = re.sub(r"^(.*? ago)\1$", r"\1", s.replace("Posted ", ""))
            elif s in STATUS:
                cur["status"].append(s)
            elif re.search(r"works? here|connection", s):
                cur["network"].append(s)
        k += 1
    return cards


def from_rows(rows):
    cards = []
    for n, r in enumerate(rows, 1):
        r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
        bad = [k for k in ("title", "company", "location", "salary", "posted", "section")
               if r.get(k) is not None and not isinstance(r[k], str)]
        bad += [k for k in ("status", "network") if r.get(k) is not None and not (
            isinstance(r[k], str) or (isinstance(r[k], list) and all(isinstance(x, str) for x in r[k])))]
        if bad:
            sys.exit(f"row {n}: {', '.join(bad)} must be text" + (" (status and network may be a list of text)"
                     if {"status", "network"} & set(bad) else "") + "; fix the row and rerun")
        if not (r.get("title") and r.get("company")):
            continue
        loc = r.get("location") or ""
        st = r.get("status") or []
        cards.append({"n": len(cards) + 1, "title": r["title"], "company": r["company"], "location": loc,
                      "workplace": workplace(loc), "salary": r.get("salary") or None, "posted": r.get("posted") or None,
                      "status": st if isinstance(st, list) else [x.strip() for x in st.split(";") if x.strip()],
                      "network": [r["network"]] if isinstance(r.get("network"), str) and r["network"] else (r.get("network") or []),
                      "section": r.get("section") or "exact", "line": None})
    return cards


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    ext = src.suffix.lower()
    if ext in (".txt", ".md"):
        cards = parse_paste(src.read_text(encoding="utf-8"))
    elif ext == ".csv":
        with src.open(encoding="utf-8-sig", newline="") as f:
            cards = from_rows(csv.DictReader(f))
    elif ext == ".json":
        rows = read_json(src, expect=list)
        if not all(isinstance(r, dict) for r in rows):
            sys.exit(f"{src}: every item must be an object with title, company and location")
        cards = from_rows(rows)
    else:
        sys.exit(f"Unsupported file type {ext}: use .txt/.md (pasted results), .csv or .json")
    for c in cards:
        c["find"] = find_link(c["title"], c["company"])
    write_json(out, cards, indent=1)
    banner = next((c["n"] for c in cards if c["section"] == "after banner"), None)
    print(f"{len(cards)} cards -> {out}")
    print("workplace:", dict(Counter(c["workplace"] for c in cards)))
    print("Saved:", sum("Saved" in c["status"] for c in cards), " Viewed:", sum("Viewed" in c["status"] for c in cards),
          " banner before card:", banner)
    # Filter guard: a remote search should return (almost) only Remote or city-only cards.
    non_remote = [c for c in cards if c["workplace"] in ("Hybrid", "On-site")]
    if cards and len(non_remote) / len(cards) > 0.05:
        print(f"WARNING: {len(non_remote)} of {len(cards)} cards are Hybrid/On-site. If this was a remote search, the Remote "
              "filter was probably off: re-run it with the pre-run checklist before triaging. (Expected for local searches like S7.)")


if __name__ == "__main__":
    main()
