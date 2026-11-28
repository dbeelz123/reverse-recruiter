"""Where everything lives. Every script gets its locations from here, so a folder move is a one-line change.

Layout of the data folder, set 2026-11-16. Which folder: --data <folder> if given, else the folder named by the
REVERSE_RECRUITER_DATA environment variable, else <project>/my-data.
  1-inbox/job-pdfs/          saved LinkedIn job PDFs (you drop them here)
  1-inbox/search-results/    pasted search-result pages (.txt) for triage
  1-inbox/tracked-jobs/      pasted LinkedIn Job Tracker → Saved pages (.txt), used to check saves match the project
  1-inbox/role-explorer/     a role to research: title + job description (.docx/.pdf/.txt), for a Role Explorer brief
  2-reports/                 round reports and search links (you read these)
  3-applications/            one folder per job application kit
  4-profile/                 resume/, linkedin/, writing-samples/, career-master.md, voice-guide.md
  5-criteria/                spec.json, changelog.md, searches.json (your rules), places.json (your city table)
  6-system/                  machine data: jobs/, reviews/, calibration/, search-runs/, *.json
  7-recommendations/         one folder per person: LinkedIn recommendations given and received (recommendations.py)
"""
import json
import os
import re
import unicodedata
from pathlib import Path

import sys

# Every script imports this module, so this is where console output is made safe: on Windows before Python 3.15 a
# piped or redirected console is cp1252, and one "→" in a posting excerpt or an accented name stopped a script
# mid-run (a re-screen half done, a removal batch half applied).
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):  # a replaced or closed stream (test runners, some hosts)
        pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "my-data"
DATA_ENV = "REVERSE_RECRUITER_DATA"  # set once (e.g. in Claude Code settings) when the data lives elsewhere

# Relative to the data folder. JOB_PDFS is also the prefix stored in ledger keys and job records.
JOB_PDFS = "1-inbox/job-pdfs"
SEARCH_RESULTS = "1-inbox/search-results"
TRACKED_JOBS = "1-inbox/tracked-jobs"
ROLE_EXPLORER = "1-inbox/role-explorer"
REPORTS = "2-reports"
APPLICATIONS = "3-applications"
PROFILE = "4-profile"
CRITERIA = "5-criteria"
SYSTEM = "6-system"
RECOMMENDATIONS = "7-recommendations"


def iso_date(s):
    """argparse type for --date: a real YYYY-MM-DD date, returned unchanged ('unknown' passes through)."""
    import argparse
    import datetime
    if s == "unknown":
        return s
    try:
        if not YMD.fullmatch(s):  # Python also reads week dates ('2021-W01-1') and compact forms: not allowed here
            raise ValueError
        datetime.date.fromisoformat(s)
        return s
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {s!r}")


YMD = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def past_date(s):
    """argparse type for the date something happened (an open check, an application step): iso_date, and not after
    today. A future date is a typo (2026-12-25 for 11-25), and once stored it outranks every correct date after it."""
    import argparse
    import datetime
    s = iso_date(s)
    if s != "unknown" and datetime.date.fromisoformat(s) > datetime.date.today():
        raise argparse.ArgumentTypeError(f"{s} is in the future; give the day it happened")
    return s


LEGAL_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc",
                  "gmbh", "group", "holdings", "technologies", "technology"}


def company_key(name):
    """One key per employer, for grouping several roles at a company: the whole name, without a note in parentheses
    ("Acme (through a staffing firm)"), a leading "The", or trailing legal words ("Acme, Inc.", "Acme Group"). The
    first word alone is not a key: "The Home Depot" and "The Trade Desk" are different companies."""
    words = norm_name(str(name or "").split(" (")[0]).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words = words[:-1]
    return " ".join(words)


def read_run(path):
    """A search-run file (6-system/search-runs/*.json), checked for the shape every reader relies on: an object;
    'round', when present, a whole number; 'listings', when present, a list of objects; 'unrecorded_cards', when
    present, a whole number. Anything else stops with the file named, instead of a traceback or, worse, a run that
    silently drops out of the funnel."""
    d = read_json(path, expect=dict)
    whole = lambda v: isinstance(v, int) and not isinstance(v, bool)
    if "round" in d and not whole(d["round"]):
        raise DataFileError(f"Malformed {path}: 'round' must be a whole number, not {d['round']!r}.")
    ls = d.get("listings")
    if ls is not None and not (isinstance(ls, list) and all(isinstance(x, dict) for x in ls)):
        raise DataFileError(f"Malformed {path}: 'listings' must be a list of objects.")
    if d.get("unrecorded_cards") is not None and not whole(d["unrecorded_cards"]):
        raise DataFileError(f"Malformed {path}: 'unrecorded_cards' must be a whole number, "
                            f"not {d['unrecorded_cards']!r}.")
    return d


def to_date(s):
    """'2026-11-19' (or a complete ISO timestamp, 'T' or space after the date) -> date; anything missing or
    malformed -> None, never an exception. A longer value must parse as a whole timestamp, so '2026-11-24junk' and
    '2026-11-19Tjunk' are None. Every date read back from a data file goes through this, so one hand-edited value
    can't stop a command."""
    import datetime
    if not s:
        return None
    s = str(s)
    if not YMD.match(s):  # week dates ('2021-W01-1') and other ISO forms Python accepts are not data dates
        return None
    try:
        if len(s) == 10:
            return datetime.date.fromisoformat(s)
        if s[10] not in "T ":
            return None
        if s.endswith("Z"):  # Python 3.10's fromisoformat doesn't read 'Z'
            s = s[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(s).date()
    except (TypeError, ValueError, IndexError):
        return None


def blocklist(spec, path):
    """spec.json's company_blocklist entries, each checked to be an object with a text 'value' (the company name).
    A malformed entry stops the command and names it, rather than being skipped: a silently dropped entry would
    let that company's jobs back in."""
    entries = spec.get("company_blocklist", [])
    if not isinstance(entries, list):
        raise DataFileError(f"Malformed {path}: company_blocklist must be a list.")
    for i, b in enumerate(entries):
        if not (isinstance(b, dict) and isinstance(b.get("value"), str) and b["value"].strip()):
            raise DataFileError(f"Malformed {path}: company_blocklist[{i}] needs a 'value' with the company name.")
        al = b.get("aliases")
        if al is not None and not (isinstance(al, list) and all(isinstance(a, str) and a.strip() for a in al)):
            # A plain string would be read one character at a time, so "A" would block every "A ..." company.
            raise DataFileError(f"Malformed {path}: company_blocklist[{i}] 'aliases' must be a list of names.")
        # "case_by_case": "false" would read as true, and a misspelled "match" would fall back to whole-word
        # matching without a word, so both must be exactly what the matcher expects.
        if not isinstance(b.get("case_by_case", False), bool):
            raise DataFileError(f"Malformed {path}: company_blocklist[{i}] 'case_by_case' must be true or false.")
        if b.get("match", "exact") != "exact":
            raise DataFileError(f"Malformed {path}: company_blocklist[{i}] 'match' can only be \"exact\".")
    return entries


def norm_name(s):
    """Company name for blocklist matching: accents dropped ('TUSAŞ' -> 'tusas'), '&' read as 'and', case and
    punctuation ignored ('MOOG, Inc.' -> 'moog inc')."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    s = s.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def blocklist_names(entry):
    """The names one blocklist entry matches: the value's text before ' (' plus any 'aliases'. Category entries
    (values starting 'Companies ...', e.g. 'Companies owned by ...') match only through their aliases."""
    v = entry["value"]
    names = [] if v.lower().startswith("companies ") else [v.split(" (")[0].strip()]
    names += [a for a in entry.get("aliases", []) if isinstance(a, str) and a.strip()]
    return [n for n in names if n]


def case_by_case(entry):
    """A blocklist entry for a company that also does work outside the blocked area (e.g. a parent company whose
    defense unit is blocked): its listings are judged one by one, never blocked or hidden automatically."""
    return bool(entry.get("case_by_case"))


def blocked_by(company, entries, confirmed_only=False):
    """The blocklist entry that matches a company name, or None. Names match as whole words, case-insensitive
    ('SAIC' doesn't hit 'Mosaic', 'Arity' doesn't hit 'Clarity'); an entry with "match": "exact" must equal the
    whole company name (e.g. 'Via', which would otherwise also hit 'Via Transportation'). A firm entry wins over a
    case-by-case one, so 'Boeing Defense, Space & Security' matches the unit's entry, not the parent's."""
    c = norm_name(company)
    if not c:
        return None
    soft = None
    for b in entries:
        if confirmed_only and b.get("status") != "confirmed":
            continue
        for n in blocklist_names(b):
            n = norm_name(n)
            if not n:
                continue
            if b.get("match") == "exact":
                hit = c == n
            else:
                hit = bool(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", c))
            if hit:
                if not case_by_case(b):
                    return b
                soft = soft or b
    return soft


def latest_reviews(P, upto=None, check=None):
    """{job_id: (review entry, round)} from every reviews/round-NN.json up to round `upto` (all when None); a later
    round's entry wins. The review files are the source of truth: job records hold a copy that only build_report.py
    refreshes, so anything that runs before the report in a round (metrics.py) must read these. `check(path, jid,
    entry)` validates each entry."""
    import re
    out = {}
    files = sorted((int(m.group(1)), f) for f in P.reviews.glob("round-*.json")
                   if (m := re.fullmatch(r"round-(\d+)\.json", f.name)))
    for n, f in files:
        if upto is not None and n > upto:
            continue
        # expect=dict: a file that isn't an object (e.g. "[]") must stop the command, not silently drop a round.
        jobs = (read_json(f, None, expect=dict) or {}).get("jobs", {})
        if not isinstance(jobs, dict):
            raise DataFileError(f"Malformed review file {f}: 'jobs' must be an object keyed by job ID.")
        for jid, entry in jobs.items():
            if check:
                check(f, jid, entry)
            out[jid] = (entry, n)
    return out


def tombstones(path):
    """removed.json entries that are usable: objects with a text job_id. Anything else is skipped (an object or
    list as job_id would break the ID lookups)."""
    # expect=list: a file whose top level isn't a list stops with the file named (iterating an object's keys would
    # silently drop every removal). Single damaged entries are still skipped, by design (tests/test_robustness.py).
    return [t for t in read_json(path, [], expect=list) or []
            if isinstance(t, dict) and isinstance(t.get("job_id"), str) and t["job_id"].strip()]


def removed_before(path, job_id):
    """The latest removed.json tombstone for this job ID, or None: a job removed earlier and now saved or ingested
    again. The job is still processed (a reopened posting is a legitimate re-save), but flagged for the user."""
    hits = [t for t in tombstones(path) if t["job_id"] == job_id]
    return hits[-1] if hits else None


def is_score(x):
    """A real, finite number: true/false (a subclass of int) and NaN/infinity don't count."""
    import math
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def review_score_problems(r):
    """What's wrong with a review entry's numbers (empty when nothing is): 'fit' is a number from 0 to 100, or null
    only for tier X (excluded) or ? (incomplete) (review-rubric.md); 'network_bonus' and each adjustment's 'points'
    are numbers.
    Shared by build_report.py and rescreen.py."""
    problems = []
    fit = r.get("fit", "missing")
    if fit is not None and not (is_score(fit) and 0 <= fit <= 100):
        problems.append(f"'fit' must be a number from 0 to 100 (or null for an excluded job), not {fit!r}")
    if fit is None and r.get("tier") not in ("X", "?"):
        problems.append(f"a null 'fit' goes only with tier X (excluded) or ? (incomplete), not tier {r.get('tier')!r}")
    if not is_score(r.get("network_bonus", 0)):
        problems.append(f"'network_bonus' must be a number, not {r.get('network_bonus')!r}")
    adj = r.get("adjustments", [])
    if not isinstance(adj, list) or not all(isinstance(a, dict) and is_score(a.get("points"))
                                            and isinstance(a.get("reason"), str) and a["reason"].strip() for a in adj):
        problems.append("'adjustments' must be a list of {reason, points}: reason as text, points a number")
    return problems


def write_json(path, obj, indent=2, ensure_ascii=False, newline=False):
    """Write JSON atomically: a temporary file in the same folder, then os.replace, so a crash mid-write never
    leaves a half-written record. Every script writes its JSON through this.
    Deliberate (code reviews, 2026-11-25 and 2026-11-27): the temporary name is fixed (<name>.tmp), and a link planted
    at that name inside the user's own data folder is not guarded against; the folder is the user's, and a fixed
    name leaves at most one stray file after a crash."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii) + ("\n" if newline else ""),
                   encoding="utf-8")
    os.replace(tmp, path)


class DataFileError(SystemExit):
    pass


_REQUIRED = object()


def read_json(path, default=_REQUIRED, expect=None):
    """Read a JSON data file. A missing file returns `default` (or stops with a clear message when no default is
    given); a damaged file, or one whose top level isn't `expect` (dict or list), stops with a message naming the
    file instead of a raw traceback."""
    path = Path(path)
    if not path.exists():
        if default is _REQUIRED:
            raise DataFileError(f"Missing data file: {path}")
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DataFileError(f"Damaged data file: {path}\n  {e}\n  Fix it by hand or restore it from a backup, "
                            f"then rerun.")
    if expect is not None and not isinstance(data, expect):
        raise DataFileError(f"Unexpected content in {path}: expected a JSON {expect.__name__}, "
                            f"found {type(data).__name__}.")
    return data


class Paths:
    def __init__(self, data=None):
        env = os.environ.get(DATA_ENV, "").strip()
        if not data and env and not Path(env).is_dir():  # a typo here must not quietly fall back to my-data/
            raise DataFileError(f"{DATA_ENV} points to {env}, which isn't a folder. Fix the setting or pass --data.")
        d = Path(data) if data else Path(env) if env else DEFAULT_DATA
        self.data = d
        # inbox
        self.job_pdfs = d / JOB_PDFS
        self.search_results = d / SEARCH_RESULTS
        self.tracked_jobs = d / TRACKED_JOBS
        self.role_explorer = d / ROLE_EXPLORER
        # reports and applications
        self.reports = d / REPORTS
        self.search_links = d / REPORTS / "search-links.md"
        self.applications = d / APPLICATIONS
        # profile
        self.profile_dir = d / PROFILE
        self.resume_dir = d / PROFILE / "resume"
        self.linkedin_dir = d / PROFILE / "linkedin"
        self.career_master = d / PROFILE / "career-master.md"
        self.voice_guide = d / PROFILE / "voice-guide.md"
        # criteria
        self.spec = d / CRITERIA / "spec.json"
        self.places = d / CRITERIA / "places.json"  # the user's city table for the radius check (locations.py)
        self.changelog = d / CRITERIA / "changelog.md"
        self.searches = d / CRITERIA / "searches.json"
        self.connections = d / CRITERIA / "connections.json"  # the user's call on each connection (connections.py)
        # system data
        sysd = d / SYSTEM
        self.jobs = sysd / "jobs"
        self.reviews = sysd / "reviews"
        self.calibration = sysd / "calibration"
        self.search_runs = sysd / "search-runs"
        self.profile_json = sysd / "profile.json"
        self.skills_gap = sysd / "skills-gap.json"
        self.ledger = sysd / "ledger.json"
        self.triaged = sysd / "triaged.json"
        self.removed = sysd / "removed.json"
        self.metrics = sysd / "metrics.json"
        self.linkedin_project = sysd / "linkedin-project.json"  # numbers published on the LinkedIn project
        # LinkedIn recommendations, one folder per person
        self.recommendations = d / RECOMMENDATIONS

    def inside(self, p, folder=None):
        """True when p resolves inside folder (default: the data folder). Guards every delete and copy. The folder
        must itself resolve inside the data folder, so a linked folder (symlink or junction) pointing elsewhere
        never widens the boundary."""
        root = Path(self.data).resolve()
        base = Path(folder or self.data).resolve()
        try:
            base.relative_to(root)
            Path(p).resolve().relative_to(base)
            return True
        except ValueError:
            return False

    def rel(self, p):
        """Path relative to the data folder, with forward slashes (as stored in ledger keys and job records)."""
        return Path(p).resolve().relative_to(self.data.resolve()).as_posix()
