"""Connections with a LinkedIn recommendation (either way) score recommendation_points instead of the plain bonus."""
import json
import unittest

import helpers
from paths import Paths

JOB = "9100000001"  # the sample job with a 1st-degree connection, "Sam Ortiz (fictional)"
SLUG = "sam-ortiz-fictional"


class Units(unittest.TestCase):
    def test_slug_matches_folder_names(self):
        from recommendations import slug
        self.assertEqual(slug("Sam Ortiz (fictional)"), SLUG)
        self.assertEqual(slug("  José  O'Brien-Smith "), "jose-o-brien-smith")
        self.assertEqual(slug(None), "")

    def test_points(self):
        from recommendations import network_points
        spec = {"scoring": {"network": {"points": 8, "recommendation_points": 12}}}
        job = {"connections_1st": [{"name": "Sam Ortiz (fictional)"}, {"name": "Other Person"}]}
        self.assertEqual(network_points(spec, 8, job, {SLUG: "received"}), 12)
        self.assertEqual(network_points(spec, 0, job, {SLUG: "given"}), 12)  # a match counts even if review missed it
        self.assertEqual(network_points(spec, 8, job, {"someone-else": "both"}), 8)
        self.assertEqual(network_points({}, 8, job, {SLUG: "both"}), 8)  # no setting in spec.json: review stands
        self.assertEqual(network_points(spec, 8, {"connections_1st": None}, {SLUG: "both"}), 8)


class WithData(helpers.SampleCase):
    def person(self, received=False, given=False):
        d = self.data / "7-recommendations" / SLUG
        (d / "profile").mkdir(parents=True)
        if received:
            (d / "received").mkdir()
            (d / "received" / "recommendation.md").write_text("text", encoding="utf-8")
        if given:
            (d / "given").mkdir()
            (d / "given" / "final.md").write_text("text", encoding="utf-8")

    def set_points(self):
        f = self.data / "5-criteria" / "spec.json"
        spec = json.loads(f.read_text(encoding="utf-8"))
        spec["scoring"]["network"] = {"rule": "+8; +12 with a recommendation", "points": 8, "recommendation_points": 12}
        f.write_text(json.dumps(spec), encoding="utf-8")

    def review(self):
        return json.loads((self.data / "6-system" / "jobs" / f"{JOB}.json").read_text(encoding="utf-8"))["review"]

    def test_directions_and_pending(self):
        from recommendations import load
        self.assertEqual(load(Paths(self.data)), {})  # no folder at all
        self.person()  # a request still pending: no recommendation file yet
        self.assertEqual(load(Paths(self.data)), {})
        (self.data / "7-recommendations" / SLUG / "given").mkdir()
        (self.data / "7-recommendations" / SLUG / "given" / "final.md").write_text("x", encoding="utf-8")
        self.assertEqual(load(Paths(self.data)), {SLUG: "given"})

    def test_report_raises_the_bonus_and_marks_the_person(self):
        self.set_points()
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        before = self.review()
        self.assertNotIn("recommendation", before)
        self.person(received=True, given=True)
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        after = self.review()
        self.assertEqual(after["network_bonus"], 12)
        self.assertEqual(after["total"] - before["total"], 12 - before["network_bonus"])
        self.assertEqual(after["recommendation"], [{"name": "Sam Ortiz (fictional)", "direction": "both"}])
        report = sorted((self.data / "2-reports").glob("*-round-02-report.md"))[-1].read_text(encoding="utf-8")
        self.assertIn("Sam Ortiz (fictional) (recommendation)", report)
        self.assertIn("recommendations both ways", report)

    def test_removing_the_folder_restores_the_plain_bonus(self):
        self.set_points()
        self.person(received=True)
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        self.assertEqual(self.review()["network_bonus"], 12)
        import shutil
        shutil.rmtree(self.data / "7-recommendations")
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        r = self.review()
        self.assertEqual(r["network_bonus"], 8)
        self.assertNotIn("recommendation", r)

    def test_cli_lists_people_and_jobs(self):
        self.person(received=True)
        out = self.ok("recommendations.py", "--data", self.data)
        self.assertIn(f"{SLUG}: received", out)
        self.assertIn("Sam Ortiz (fictional) (received)", out)


if __name__ == "__main__":
    unittest.main()
