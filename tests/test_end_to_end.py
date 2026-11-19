"""Every engine command runs cleanly against the fictional sample candidate."""
import unittest

from helpers import SampleCase


class EndToEnd(SampleCase):
    def test_every_command_runs(self):
        d = ["--data", self.data]
        self.ok("extract.py", *d)
        self.ok("rescreen.py", *d)
        self.ok("searches.py", *d)
        self.ok("metrics.py", *d)
        self.ok("modes.py", "signals", *d)
        self.ok("precision.py", *d)
        self.ok("pipeline.py", "queue", *d)
        self.ok("staleness.py", *d, "status", "--all")
        self.ok("interviews.py", *d, "due", "--soon", "30")
        self.ok("interviews.py", *d, "lessons")
        self.ok("primer.py", *d, "draft", "arcadia")
        self.ok("linkedin_project.py", "check", *d)
        self.ok("triaged.py", "keeps", self.data / "6-system/search-runs/s1-run-2026-11-13.json", *d)
        out = self.ok("build_report.py", *d, "--round", "2")
        self.assertIn("11 jobs", out)

    def test_report_ranks_and_excludes(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        report = (self.data / "2-reports/2026-11-14-round-02-report.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | 90 (80 +2 +8 net) | A |", report)          # connection bonus and adjustments
        self.assertIn("Hybrid in Chicago", report)                        # dealbreaker shown with its reason
        self.assertIn("(~37 mi)", report)                                 # local radius from places.json

    def test_primer_check_passes_on_the_sample_kit(self):
        out = self.ok("primer.py", "--data", self.data, "check", "northwind")
        self.assertIn("PRIMER COMPLETE", out)

    def test_funnel_per_100(self):
        out = self.ok("linkedin_project.py", "check", "--data", self.data)
        self.assertIn("per 100 100 / 31 / 13 / 9", out)


if __name__ == "__main__":
    unittest.main()
