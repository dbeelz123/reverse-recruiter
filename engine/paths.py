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

    def rel(self, p):
        """Path relative to the data folder, with forward slashes (as stored in ledger keys and job records)."""
        return Path(p).resolve().relative_to(self.data.resolve()).as_posix()
