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
        datetime.date.fromisoformat(s)
        return s
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {s!r}")


def to_date(s):
    """'2026-11-19' (or a longer ISO timestamp) -> date; anything missing or malformed -> None, never an exception.
    Every date read back from a data file goes through this, so one hand-edited value can't stop a command."""
    import datetime
    try:
        return datetime.date.fromisoformat(str(s)[:10]) if s else None
    except (TypeError, ValueError):
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
    """removed.json entries that are usable: objects with a job_id. Anything else is skipped."""
    return [t for t in read_json(path, []) or [] if isinstance(t, dict) and t.get("job_id")]


def write_json(path, obj, indent=2, ensure_ascii=False, newline=False):
    """Write JSON atomically: a temporary file in the same folder, then os.replace, so a crash mid-write never
    leaves a half-written record. Every script writes its JSON through this."""
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
        """True when p resolves inside folder (default: the data folder). Guards every delete and copy."""
        base = Path(folder or self.data).resolve()
        try:
            Path(p).resolve().relative_to(base)
            return True
        except ValueError:
            return False

    def rel(self, p):
        """Path relative to the data folder, with forward slashes (as stored in ledger keys and job records)."""
        return Path(p).resolve().relative_to(self.data.resolve()).as_posix()
