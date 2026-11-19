"""Where everything lives. Every script gets its locations from here, so a folder move is a one-line change.

Layout of the data folder (default: <project>/my-data), set 2026-11-16:
  1-inbox/job-pdfs/          saved LinkedIn job PDFs (you drop them here)
  1-inbox/search-results/    pasted search-result pages (.txt) for triage
  1-inbox/tracked-jobs/      pasted LinkedIn Job Tracker → Saved pages (.txt), used to check saves match the project
  1-inbox/role-explorer/     a role to research: title + job description (.docx/.pdf/.txt), for a Role Explorer brief
  2-reports/                 round reports and search links (you read these)
  3-applications/            one folder per job application kit
  4-profile/                 resume/, linkedin/, writing-samples/, career-master.md, voice-guide.md
  5-criteria/                spec.json, changelog.md, searches.json (your rules), places.json (your city table)
  6-system/                  machine data: jobs/, reviews/, calibration/, search-runs/, *.json
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "my-data"

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
    return entries


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
        d = Path(data) if data else DEFAULT_DATA
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
