"""Fixes from the whole-project code review (2026-11-25): each test reproduces the reported problem and checks the
fixed behavior."""
import json
import unittest

from helpers import SampleCase, run


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class ResavedRemovedJob(SampleCase):
    """A job removed earlier and saved again (same job ID) is flagged, not silently reviewed again."""
    JOB = "9100000006"

    def tombstone(self):
        rec = read(self.data / f"6-system/jobs/{self.JOB}.json")
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": self.JOB, "removed": "2026-11-12", "reason": "hybrid too far",
            "company": rec["company"], "title": rec["title"]}])
        return rec

    def test_extract_flags_a_resaved_removed_job(self):
        self.tombstone()
        from paths import Paths
        from extract import repost_check
        P = Paths(str(self.data))
        out = repost_check(P, self.data, [self.JOB], [])
        self.assertTrue(any("PREVIOUSLY REMOVED" in line and self.JOB in line and "hybrid too far" in line
                            for line in out), out)
        rec = read(self.data / f"6-system/jobs/{self.JOB}.json")
        self.assertEqual(rec["previously_removed"], {"removed": "2026-11-12", "reason": "hybrid too far"})

    def test_a_job_never_removed_is_not_flagged(self):
        from paths import Paths
        from extract import repost_check
        out = repost_check(Paths(str(self.data)), self.data, [self.JOB], [])
        self.assertFalse(any("PREVIOUSLY REMOVED" in line for line in out), out)
        self.assertNotIn("previously_removed", read(self.data / f"6-system/jobs/{self.JOB}.json"))

    def test_external_ingest_flags_a_removed_id(self):
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": "ext-gone", "removed": "2026-11-12", "reason": "role filled"}])
        desc = self.data / "3-applications/gone/d.txt"
        desc.parent.mkdir(parents=True)
        desc.write_text("About the role", encoding="utf-8")
        out = self.ok("ingest_external.py", desc, "--id", "ext-gone", "--company", "A", "--title", "B",
                      "--data", self.data)
        self.assertIn("PREVIOUSLY REMOVED", out)
        self.assertIn("role filled", out)
        rec = read(self.data / "6-system/jobs/ext-gone.json")
        self.assertEqual(rec["previously_removed"]["reason"], "role filled")


class ReviewScoreBounds(SampleCase):
    """fit must be null or a finite number from 0 to 100; true/false and NaN are not numbers here."""

    def set_first(self, field, value):
        p = self.data / "6-system/reviews/round-02.json"
        r = read(p)
        jid = next(iter(r["jobs"]))
        r["jobs"][jid][field] = value
        # json.dumps writes NaN as the bare token NaN, which Python's json reads back as float('nan').
        p.write_text(json.dumps(r), encoding="utf-8")
        return jid

    def test_bad_fit_values_stop_the_report_and_the_rescreen(self):
        for value in (-1, 101, 999, True, float("nan"), "80"):
            with self.subTest(fit=value):
                jid = self.set_first("fit", value)
                for script, args in (("build_report.py", ("--round", "2")), ("rescreen.py", ())):
                    code, out = run(script, "--data", self.data, *args)
                    self.assertNotEqual(code, 0, f"{script} accepted fit={value!r}:\n{out}")
                    self.assertNotIn("Traceback", out)
                    self.assertIn(jid, out)
                    self.assertIn("fit", out)

    def test_boolean_or_nan_points_and_bonus_stop_the_report(self):
        for field, value in (("network_bonus", True), ("network_bonus", float("nan")),
                             ("adjustments", [{"reason": "x", "points": False}])):
            with self.subTest(field=field, value=value):
                self.set_first(field, value)
                code, out = run("build_report.py", "--data", self.data, "--round", "2")
                self.assertNotEqual(code, 0, f"accepted {field}={value!r}:\n{out}")
                self.assertNotIn("Traceback", out)

    def test_edge_values_and_null_still_pass(self):
        for value in (0, 100, 72.5, None):
            with self.subTest(fit=value):
                self.set_first("fit", value)
                if value is None:  # a null fit goes only with tier X or ? (second whole-project review, #7)
                    self.set_first("tier", "X")
                self.ok("build_report.py", "--data", self.data, "--round", "2")


class UnreviewedJobsListed(SampleCase):
    def test_a_job_without_a_review_is_listed_not_dropped(self):
        new = {"job_id": "9100000555", "company": "Quillfeather Analytics", "title": "Staff PM, Unreviewed",
               "url": "https://www.linkedin.com/jobs/view/9100000555/", "connections_1st": []}
        (self.data / "6-system/jobs/9100000555.json").write_text(json.dumps(new), encoding="utf-8")
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        report = next((self.data / "2-reports").glob("*-round-02-report.md")).read_text(encoding="utf-8")
        self.assertIn("Not reviewed yet", report)
        section = report.split("Not reviewed yet", 1)[1]
        self.assertIn("Staff PM, Unreviewed", section)
        self.assertIn("1 not reviewed yet", report)

    def test_no_section_when_every_job_is_reviewed(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        report = next((self.data / "2-reports").glob("*-round-02-report.md")).read_text(encoding="utf-8")
        self.assertNotIn("Not reviewed yet", report)


class RemovalConnectionGuard(SampleCase):
    JOB = "9100000001"  # the sample job with a 1st-degree connection (Sam Ortiz)

    def test_a_job_with_a_connection_needs_confirmation(self):
        before = (self.data / "6-system/removed.json").read_text(encoding="utf-8")
        code, out = run("remove_job.py", self.JOB, "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("Sam Ortiz", out)
        self.assertIn("--confirm-connections", out)
        self.assertTrue((self.data / f"6-system/jobs/{self.JOB}.json").exists())
        self.assertEqual((self.data / "6-system/removed.json").read_text(encoding="utf-8"), before)

    def test_nothing_is_removed_when_any_job_in_the_batch_has_a_connection(self):
        code, out = run("remove_job.py", "9100000006", self.JOB, "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertTrue((self.data / "6-system/jobs/9100000006.json").exists())

    def test_a_connection_named_only_in_connections_json_counts(self):
        (self.data / "5-criteria/connections.json").write_text(json.dumps({"people": {
            "pat-quill": {"name": "Pat Quill", "strength": "neutral", "job_ids": ["9100000006"]}}}), encoding="utf-8")
        code, out = run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0, out)
        self.assertIn("Pat Quill", out)

    def test_confirmed_removal_goes_ahead(self):
        out = self.ok("remove_job.py", self.JOB, "--reason", "test", "--confirm-connections", "--data", self.data)
        self.assertIn("Sam Ortiz", out)
        self.assertFalse((self.data / f"6-system/jobs/{self.JOB}.json").exists())


class DependencyBound(unittest.TestCase):
    def test_pymupdf_has_an_upper_bound(self):
        from helpers import REPO
        line = next(l for l in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if l.startswith("pymupdf"))
        self.assertRegex(line.split("#")[0], r"pymupdf>=1\.24,\s*<2\b")


if __name__ == "__main__":
    unittest.main()
