"""Fixes from the review of commit 722797c (2026-11-28, areas 4 and 5: scoring and the report; funnel, modes and
public numbers): each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest
from pathlib import Path
from unittest import mock

from helpers import SampleCase, run

JOB = "9100000009"  # reviewed in round 2
SENTENCE = "about 3 in every 100 listings processed make the cut as qualified targets"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def edit_json(path, change):
    d = read(path)
    change(d)
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


class ProjectUpdate(SampleCase):
    """#1: the public update (two images, the description, the record) is marked while it runs, so a failure part
    way never passes for a finished update: nothing is marked ready, `check` says so, `live` refuses, and running
    `update` again finishes it."""

    def setUp(self):
        super().setUp()
        import linkedin_project
        from paths import Paths
        self.lp = linkedin_project
        self.P = Paths(str(self.data))
        self.P.linkedin_dir.mkdir(parents=True, exist_ok=True)
        self.ref = self.P.linkedin_dir / "linkedin-profile.md"
        self.ref.write_text(f"## Project\nSo far {SENTENCE}.\n", encoding="utf-8")
        self.before = self.ref.read_text(encoding="utf-8")
        self.rendered = {"round": 2, "funnel": {"processed": 100, "decided": 30, "pdfs": 13, "ranked": 9},
                         "grades": {"A": 4, "B": 3, "C": 2, "D": 0}, "per100": True,
                         "files": ["4-profile/linkedin/project-images/a.png", "4-profile/linkedin/project-images/b.png"]}

    def record(self):
        return read(self.P.linkedin_project) if self.P.linkedin_project.exists() else {}

    def update(self, replace_file=None):
        """Run update with the render stubbed out, and optionally with the description's final swap failing."""
        with mock.patch.object(self.lp.linkedin_images, "main", return_value=self.rendered):
            if replace_file is None:
                self.lp.update(self.P)
            else:
                with mock.patch.object(self.lp, "replace_file", replace_file):
                    self.lp.update(self.P)

    def assert_interrupted(self):
        rec = self.record()
        self.assertIn("updating", rec)
        self.assertNotIn("ready", rec)
        code, out = run("linkedin_project.py", "check", "--data", self.data)
        self.assertIn("INTERRUPTED", out)
        code, out = run("linkedin_project.py", "live", "--data", self.data)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("update", out)

    def test_a_failed_description_write_is_not_a_finished_update(self):
        def locked(src, dst):
            raise PermissionError(13, "Access is denied")
        with self.assertRaises(SystemExit) as e:
            self.update(replace_file=locked)
        self.assertIn("linkedin_project.py update", str(e.exception))
        self.assertEqual(self.ref.read_text(encoding="utf-8"), self.before)
        self.assertEqual([p.name for p in self.P.linkedin_dir.glob("*.tmp")], [])
        self.assert_interrupted()

    def test_a_failed_render_is_not_a_finished_update(self):
        def no_browser(args):
            raise SystemExit("No Edge or Chrome found to render the images.")
        with mock.patch.object(self.lp.linkedin_images, "main", no_browser):
            with self.assertRaises(SystemExit) as e:
                self.lp.update(self.P)
        self.assertIn("No Edge or Chrome", str(e.exception))
        self.assertEqual(self.ref.read_text(encoding="utf-8"), self.before)
        self.assert_interrupted()

    def test_an_earlier_ready_update_is_not_left_standing(self):
        """An update waiting for upload describes the images it rendered; once a new update starts replacing them
        it no longer holds, whether or not the new one finishes."""
        edit = {"ready": {"round": 1, "prepared": "2026-11-10", "processed": 50, "decided": 10, "pdfs": 5, "ranked": 4}}
        self.P.linkedin_project.write_text(json.dumps(edit), encoding="utf-8")

        def locked(src, dst):
            raise PermissionError(13, "Access is denied")
        with self.assertRaises(SystemExit):
            self.update(replace_file=locked)
        self.assert_interrupted()

    def test_nothing_is_rendered_when_the_record_cannot_be_written(self):
        from paths import DataFileError

        def full(P, rec):
            raise DataFileError("Could not write linkedin-project.json: No space left on device.")
        with mock.patch.object(self.lp.linkedin_images, "main") as render, mock.patch.object(self.lp, "save", full):
            with self.assertRaises(SystemExit):
                self.lp.update(self.P)
        render.assert_not_called()
        self.assertEqual(self.ref.read_text(encoding="utf-8"), self.before)

    def test_running_update_again_finishes_it(self):
        def locked(src, dst):
            raise PermissionError(13, "Access is denied")
        with self.assertRaises(SystemExit):
            self.update(replace_file=locked)
        self.update()
        rec = self.record()
        self.assertNotIn("updating", rec)
        self.assertEqual(rec["ready"]["images"], self.rendered["files"])
        self.assertNotEqual(self.ref.read_text(encoding="utf-8"), self.before)
        self.assertIn("in every 100 listings processed", self.ref.read_text(encoding="utf-8"))
        self.assertNotIn("INTERRUPTED", run("linkedin_project.py", "check", "--data", self.data)[1])
        self.assertEqual(run("linkedin_project.py", "live", "--data", self.data)[0], 0)


class NetworkBonus(SampleCase):
    """#2: a review's network_bonus is 0 or the plain connection bonus (8, or the spec's own figure). Any other
    number, -100 or 7.5 or 16, moved a job's score without a word."""

    def bonus(self, value):
        edit_json(self.data / "6-system/reviews/round-02.json", lambda d: d["jobs"][JOB].update(network_bonus=value))

    def test_other_values_stop_the_report_and_the_rescreen(self):
        for value in (-1, -100, 1, 7.5, 16, None):
            for args in (("build_report.py", "--round", "2"), ("rescreen.py",)):
                with self.subTest(value=value, script=args[0]):
                    self.bonus(value)
                    code, out = run(*args, "--data", self.data)
                    self.assertNotEqual(code, 0, out)
                    self.assertNotIn("Traceback", out)
                    self.assertIn(JOB, out)
                    self.assertIn("round-02.json", out)
                    self.assertIn("network_bonus", out)

    def test_zero_and_eight_pass(self):
        for value in (0, 8, 8.0):
            with self.subTest(value=value):
                self.bonus(value)
                self.ok("build_report.py", "--round", "2", "--data", self.data)
                self.ok("rescreen.py", "--data", self.data)

    def test_the_specs_own_plain_bonus_passes(self):
        def own(d):
            d.setdefault("scoring", {})["network"] = {"points": 10, "plus_points": 10, "neutral_points": 5,
                                                      "recommendation_points": 14}
        edit_json(self.data / "5-criteria/spec.json", own)
        for value in (10, 8, 0):
            with self.subTest(value=value):
                self.bonus(value)
                self.ok("build_report.py", "--round", "2", "--data", self.data)
        self.bonus(14)  # the recommendation figure is set by the report, never written in a review
        self.assertNotEqual(run("build_report.py", "--round", "2", "--data", self.data)[0], 0)

    def test_a_missing_bonus_still_counts_as_none(self):
        edit_json(self.data / "6-system/reviews/round-02.json", lambda d: d["jobs"][JOB].pop("network_bonus", None))
        self.ok("build_report.py", "--round", "2", "--data", self.data)


if __name__ == "__main__":
    unittest.main()
