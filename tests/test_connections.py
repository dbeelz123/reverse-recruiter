"""Connection levels (engine/connections.py): recommendation / plus / neutral set the network points; the best
connection at the company counts; unclassified people score at the spec's default and are listed for calibration."""
import json
import unittest

import helpers
from paths import Paths

JOB = "9100000001"  # the sample job with a 1st-degree connection, "Sam Ortiz (fictional)"
SLUG = "sam-ortiz-fictional"
LEVELS = {"scoring": {"network": {"points": 8, "plus_points": 8, "neutral_points": 4, "recommendation_points": 12}}}


def job(*names, job_id="1"):
    return {"job_id": job_id, "connections_1st": [{"name": n} for n in names]}


class Units(unittest.TestCase):
    def test_levels(self):
        from connections import network_points
        people = {SLUG: {"name": "Sam Ortiz (fictional)", "strength": "neutral", "job_ids": []},
                  "pat-plus": {"name": "Pat Plus", "strength": "plus", "job_ids": []}}
        self.assertEqual(network_points(LEVELS, 8, job("Sam Ortiz (fictional)"), {}, people)[0], 4)
        self.assertEqual(network_points(LEVELS, 8, job("Pat Plus"), {}, people)[0], 8)
        self.assertEqual(network_points(LEVELS, 8, job("Sam Ortiz (fictional)"), {SLUG: "given"}, people)[0], 12)

    def test_best_connection_counts_not_the_sum(self):
        from connections import network_points
        people = {SLUG: {"name": "Sam", "strength": "neutral", "job_ids": []},
                  "pat-plus": {"name": "Pat Plus", "strength": "plus", "job_ids": []}}
        pts, found = network_points(LEVELS, 8, job("Sam Ortiz (fictional)", "Pat Plus"), {}, people)
        self.assertEqual(pts, 8)
        self.assertEqual([lv for _, lv in found], ["neutral", "plus"])

    def test_unclassified_uses_the_spec_default(self):
        from connections import network_points
        pts, found = network_points(LEVELS, 8, job("New Person"), {}, {})
        self.assertEqual((pts, found), (8, [("New Person", "unclassified")]))
        spec = json.loads(json.dumps(LEVELS))
        spec["scoring"]["network"]["unclassified"] = "neutral"
        self.assertEqual(network_points(spec, 8, job("New Person"), {}, {})[0], 4)
        spec["scoring"]["network"]["unclassified"] = "bogus"
        with self.assertRaises(SystemExit):
            network_points(spec, 8, job("New Person"), {}, {})

    def test_teaser_only_person_tied_by_job_id(self):
        from connections import network_points
        people = {"pat-teaser": {"name": "Pat (teaser)", "strength": "neutral", "job_ids": ["42"]}}
        self.assertEqual(network_points(LEVELS, 0, {"job_id": "42"}, {}, people), (4, [("Pat (teaser)", "neutral")]))
        self.assertEqual(network_points(LEVELS, 0, {"job_id": "43"}, {}, people), (0, []))

    def test_no_named_connection_keeps_the_reviews_bonus(self):
        from connections import network_points
        self.assertEqual(network_points(LEVELS, 8, {"job_id": "7", "connections_1st": []}, {}, {}), (8, []))  # referral

    def test_without_neutral_points_the_old_rule_stands(self):
        from connections import network_points
        spec = {"scoring": {"network": {"points": 8, "recommendation_points": 12}}}
        self.assertEqual(network_points(spec, 8, job("Sam Ortiz (fictional)"), {}, {})[0], 8)
        self.assertEqual(network_points(spec, 8, job("Sam Ortiz (fictional)"), {SLUG: "both"}, {})[0], 12)

    def test_levels_off_still_counts_a_teaser_only_recommender(self):
        from connections import network_points
        spec = {"scoring": {"network": {"points": 8, "recommendation_points": 12}}}
        people = {SLUG: {"name": "Sam Ortiz (fictional)", "strength": "plus", "job_ids": ["42"]}}
        self.assertEqual(network_points(spec, 8, {"job_id": "42"}, {SLUG: "received"}, people)[0], 12)
        self.assertEqual(network_points(spec, 8, {"job_id": "43"}, {SLUG: "received"}, people)[0], 8)


class WithData(helpers.SampleCase):
    def set_spec(self):
        f = self.data / "5-criteria" / "spec.json"
        spec = json.loads(f.read_text(encoding="utf-8"))
        spec["scoring"]["network"] = dict(LEVELS["scoring"]["network"], rule="12 / 8 / 4 by level")
        f.write_text(json.dumps(spec), encoding="utf-8")

    def classify(self, strength):
        (self.data / "5-criteria" / "connections.json").write_text(json.dumps(
            {"people": {SLUG: {"name": "Sam Ortiz (fictional)", "strength": strength, "decided": "2026-01-01"}}}),
            encoding="utf-8")

    def review(self):
        return json.loads((self.data / "6-system" / "jobs" / f"{JOB}.json").read_text(encoding="utf-8"))["review"]

    def report(self):
        return sorted((self.data / "2-reports").glob("*-round-02-report.md"))[-1].read_text(encoding="utf-8")

    def test_neutral_lowers_and_unclassified_is_listed(self):
        self.set_spec()
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        before = self.review()
        self.assertEqual(before["network"], [{"name": "Sam Ortiz (fictional)", "level": "unclassified"}])
        self.assertIn("Connections not yet classified", self.report())
        self.assertIn("Sam Ortiz (fictional) (not yet classified)", self.report())
        self.classify("neutral")
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        after = self.review()
        self.assertEqual(after["network_bonus"], 4)
        self.assertEqual(before["total"] - after["total"], before["network_bonus"] - 4)
        report = self.report()
        self.assertIn("Sam Ortiz (fictional) (neutral)", report)
        self.assertIn("neutral: you wouldn't ask for a referral", report)
        self.assertNotIn("Connections not yet classified", report)
        self.assertIn("+4 when you wouldn't", report)

    def test_levels_off_leaves_the_report_as_before(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        r = self.review()
        self.assertNotIn("network", r)
        self.assertEqual(r["network_bonus"], 8)

    def test_bad_strength_is_a_clear_error(self):
        self.set_spec()
        (self.data / "5-criteria" / "connections.json").write_text(
            json.dumps({"people": {SLUG: {"strength": "strong"}}}), encoding="utf-8")
        code, out = helpers.run("build_report.py", "--data", self.data, "--round", "2")
        self.assertNotEqual(code, 0)
        self.assertIn("plus", out)

    def test_people_must_be_an_object(self):
        self.set_spec()
        (self.data / "5-criteria" / "connections.json").write_text(json.dumps({"people": []}), encoding="utf-8")
        code, out = helpers.run("build_report.py", "--data", self.data, "--round", "2")
        self.assertNotEqual(code, 0)
        self.assertIn("must be an object", out)
        self.assertNotIn("Traceback", out)

    def test_job_ids_must_be_a_list(self):
        from connections import load
        f = self.data / "5-criteria" / "connections.json"
        for bad in ("4482029334", 42, ["42", "not an id"]):
            f.write_text(json.dumps({"people": {"pat-x": {"strength": "neutral", "job_ids": bad}}}), encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                load(Paths(self.data))
            self.assertIn("must be a list of job IDs", str(cm.exception))
        f.write_text(json.dumps({"people": {"pat-x": {"strength": "neutral", "job_ids": ["42", 43]}}}), encoding="utf-8")
        self.assertEqual(load(Paths(self.data))["pat-x"]["job_ids"], ["42", "43"])

    def test_cli_lists_levels(self):
        self.set_spec()
        self.classify("plus")
        out = self.ok("connections.py", "--data", self.data)
        self.assertIn("plus", out)
        self.assertIn("Sam Ortiz (fictional)", out)
        from connections import load
        self.assertEqual(load(Paths(self.data))[SLUG]["strength"], "plus")


if __name__ == "__main__":
    unittest.main()
