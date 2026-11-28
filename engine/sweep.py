"""Backlog-sweep cleanup searches: LinkedIn search links that bring back the jobs a sweep removed, so the user can
dismiss them (the X on each "Viewed" card) and keep them out of future search results.

Usage:  python engine/sweep.py --removed-on 2026-11-23 [--reason "round 9"] [--chunk 12] [--data my-data]
        python engine/sweep.py --ids 123 456 ...   (--ids adds to a --removed-on selection when both are given)
Writes  <data>/2-reports/sweep-links-<date>.md (an earlier sweep-links file moves to 2-reports/archive/)

Why: a backlog sweep saves many jobs quickly, and most are removed after review. Once unsaved, a job shows as
"Viewed" in LinkedIn's results, and the user can hide it for good with the X on its card. These links aim at the
swept jobs: the keywords name the swept companies (LinkedIn matches keywords against the posting, which names its
company) and the title families the swept jobs used, so the results are mostly jobs to dismiss.

Only builds URLs from tombstones in removed.json; it never opens or queries LinkedIn (Manual mode).
"""
import argparse
import datetime as dt
import re
import shutil
from urllib.parse import urlencode

from paths import Paths, tombstones
from searches import POSTED, US_GEO_ID

# Title families, most specific first. The first family whose pattern matches a title is the phrase searched for.
FAMILIES = [
    ("technical program manager", r"technical program manager|\btpm\b"),
    ("program manager", r"program manager"),
    ("technical product manager", r"technical product manager"),
    ("head of product", r"head of product"),
    ("product director", r"product (management )?director|director,? (of )?product"),
    ("product manager", r"product manag|product manger|product / program|\bpm\b"),
    ("product owner", r"product owner"),
    ("product lead", r"product lead|lead,? product|product leader"),
    ("product strategy", r"product strateg"),
    ("solutions owner", r"solutions owner"),
    ("transformation manager", r"transformation manager"),
    ("ai engineer", r"\bai engineer"),
    ("ai strategist", r"\bai strategist"),
    ("agent builder", r"agent builder"),
]
# One-word company names that are also everyday words: in an OR list they match almost every posting, so they get a
# search of their own (LinkedIn's company filter is the better tool for them).
COMMON_WORDS = {"lead", "point", "future", "engine", "flex", "peach", "equip", "root", "revel", "assured", "evolve",
                "medallion", "wayfinder", "halcyon", "apex", "bolt", "ramp", "notion", "box", "square", "block",
                "current", "plaid", "scale", "signal", "pulse", "beacon", "anchor", "compass", "harbor"}
# Company-name endings that postings often leave out.
SUFFIX = re.compile(r"[,\s]+(inc\.?|llc|ltd\.?|corp\.?|corporation|co\.|company|se & co\. kgaa|plc|gmbh)$", re.I)


def family(title):
    """The search phrase for a job title: a known family, or the title itself without parentheses and level words."""
    t = title.lower()
    for name, pat in FAMILIES:
        if re.search(pat, t):
            return name
    core = re.sub(r"\(.*?\)|[|/,].*$|\s[-–]\s.*$", "", t)
    core = re.sub(r"\b(senior|sr\.?|staff|principal|lead|junior|jr\.?|i{1,3}|iv)\b", "", core)
    return " ".join(re.sub(r"[^a-z0-9 &+.-]", " ", core).split()) or t.strip()


def company_term(name):
    """A company name as LinkedIn keywords should quote it: no trademark signs, parentheticals or legal suffixes."""
    n = re.sub(r"[™®©]", "", name)
    n = re.sub(r"\s*\(.*?\)", "", n).strip()
    prev = None
    while prev != n:
        prev, n = n, SUFFIX.sub("", n).strip()
    return n.replace('"', "")


def quote(term):
    return f'"{term}"' if " " in term or not term.isalnum() else term


def build(jobs, chunk=12, posted="month", remote=True):
    """Group jobs by company and split the companies into searches of at most `chunk` companies.
    posted: "day", "week", "month" or "any"; remote: add LinkedIn's Remote filter. Past month + Remote is the default
    because it worked best in the first real run (round 9, 2026-11-24): most swept jobs were remote and recent.
    Returns [{companies, families, keywords, url, jobs}]."""
    by_co = {}
    for j in jobs:
        by_co.setdefault(company_term(j["company"]), []).append(j)
    names = sorted(by_co, key=str.lower)
    common = [n for n in names if n.lower() in COMMON_WORDS]
    rest = [n for n in names if n not in common]
    groups = [rest[i:i + max(1, chunk)] for i in range(0, len(rest), max(1, chunk))]
    groups += [common[i:i + max(1, chunk)] for i in range(0, len(common), max(1, chunk))]
    out = []
    for cos in groups:
        fams = sorted({family(j["title"]) for c in cos for j in by_co[c]})
        kw = f"({' OR '.join(quote(c) for c in cos)}) AND ({' OR '.join(quote(f) for f in fams)})"
        params = {"keywords": kw, "location": "United States", "geoId": US_GEO_ID,
                  **({"f_TPR": POSTED[posted]} if posted in POSTED else {}), **({"f_WT": "2"} if remote else {}),
                  "sortBy": "DD"}
        url = "https://www.linkedin.com/jobs/search/?" + urlencode(params)
        out.append({"companies": cos, "families": fams, "keywords": kw, "url": url,
                    "jobs": [j for c in cos for j in by_co[c]], "noisy": all(c in common for c in cos)})
    return out


def select(tombs, removed_on=None, reason=None, ids=None):
    """Tombstones for the sweep: by job ID, or by removal date and an optional reason substring."""
    want = {str(i) for i in ids or []}
    by_date = removed_on or reason
    return [t for t in tombs if str(t["job_id"]) in want or (by_date and
            (not removed_on or str(t.get("removed", ""))[:10] == removed_on)
            and (not reason or reason.lower() in str(t.get("reason", "")).lower()))]


def render(searches, label):
    n = sum(len(s["jobs"]) for s in searches)
    out = [f"# Backlog-sweep cleanup searches ({dt.date.today().isoformat()})\n",
           f"{n} removed jobs from {label}, in {len(searches)} searches. Each search names the swept companies and the "
           "job-title families they used, so most results are jobs you've already unsaved (shown as **Viewed**).\n",
           "**How to use:** open a search, scroll the results, and click the **X** at the top right of each card "
           "you don't want to see again: every job listed under the search, plus any other Viewed card you've "
           "already ruled out. Dismissed jobs stay out of your future searches. Closed jobs may not appear at all; "
           "that's fine.\n",
           "**If a link shows no results:** LinkedIn may cap long keyword queries. Rerun with a smaller `--chunk`.\n"]
    for k, s in enumerate(searches, 1):
        out.append(f"## Search {k}: {', '.join(s['companies'][:3])}{' …' if len(s['companies']) > 3 else ''} "
                   f"({len(s['jobs'])} jobs)\n")
        out.append(f"**[Open search on LinkedIn]({s['url']})**\n")
        out.append(f"Keywords (to paste or edit by hand):\n\n```\n{s['keywords']}\n```\n")
        out.append("Jobs this search should bring back:\n")
        out += [f"- [ ] {j['company']}: {j['title']} ([{j['job_id']}](https://www.linkedin.com/jobs/view/{j['job_id']}/))"
                for j in sorted(s["jobs"], key=lambda j: (j["company"].lower(), j["title"]))]
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None)
    ap.add_argument("--removed-on", help="removal date of the sweep's tombstones (YYYY-MM-DD)")
    ap.add_argument("--reason", help="only tombstones whose reason contains this text")
    ap.add_argument("--ids", nargs="+", help="job IDs to include (alone, or added to a --removed-on selection)")
    ap.add_argument("--chunk", type=int, default=12, help="companies per search (default 12)")
    ap.add_argument("--posted", choices=["day", "week", "month", "any"], default="month",
                    help="posted-within filter (default month)")
    ap.add_argument("--all-workplaces", action="store_true",
                    help="drop the Remote filter, to reach swept hybrid or on-site jobs")
    a = ap.parse_args()
    if not (a.removed_on or a.ids):
        ap.error("give --removed-on or --ids")
    P = Paths(a.data)
    jobs = select(tombstones(P.removed), a.removed_on, a.reason, a.ids)
    jobs = [j for j in jobs if j.get("company") and j.get("title")]
    if not jobs:
        raise SystemExit("No matching tombstones in removed.json.")
    label = (f"the sweep removed on {a.removed_on}" if a.removed_on else "the listed job IDs") + \
            (f" (reason contains \"{a.reason}\")" if a.reason else "")
    searches = build(jobs, a.chunk, a.posted, not a.all_workplaces)
    P.reports.mkdir(parents=True, exist_ok=True)
    path = P.reports / f"sweep-links-{dt.date.today().isoformat()}.md"
    arch = P.reports / "archive"
    for old in P.reports.glob("sweep-links-*.md"):
        if old != path:
            arch.mkdir(exist_ok=True)
            shutil.move(str(old), str(arch / old.name))
    path.write_text(render(searches, label), encoding="utf-8")
    print(f"Wrote {path}: {len(jobs)} jobs in {len(searches)} searches")


if __name__ == "__main__":
    main()
