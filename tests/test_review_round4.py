"""Fixes from the fourth code review: each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest

from helpers import SampleCase, run


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class SearchRadius(SampleCase):
    def test_links_use_the_specs_radius(self):
        def radius(spec):
            spec["work_arrangement"]["machine_rule"]["radius_miles"] = 25
        edit_json(self.data / "5-criteria/spec.json", radius)
        self.ok("searches.py", "--data", self.data)
        links = (self.data / "2-reports/search-links.md").read_text(encoding="utf-8")
        self.assertIn("distance=25", links)
        self.assertNotIn("distance=50", links)
        self.assertIn("within 25 miles", links)

    def test_radius_maps_to_a_distance_that_covers_it(self):
        from searches import link_distance
        self.assertEqual([link_distance(r) for r in (5, 20, 50, 60, 500)], [5, 25, 50, 75, 100])


class MalformedRecords(SampleCase):
    def junk_tombstones(self):
        p = self.data / "6-system/removed.json"
        edit_json(p, lambda t: t + ["junk", {"reason": "no id"}])

    def test_removal_survives_junk_tombstones_and_ledger_entries(self):
        self.junk_tombstones()
        edit_json(self.data / "6-system/ledger.json", lambda l: dict(l, **{"x.pdf": "junk", "y.pdf": None}))
        self.ok("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        tombs = json.loads((self.data / "6-system/removed.json").read_text(encoding="utf-8"))
        self.assertIn("junk", tombs)                               # other entries are left as they were
        self.assertTrue(any(isinstance(t, dict) and t.get("job_id") == "9100000006" for t in tombs))

    def test_extraction_and_reports_survive_junk_tombstones(self):
        self.junk_tombstones()
        edit_json(self.data / "6-system/ledger.json", lambda l: dict(l, **{"1-inbox/job-pdfs/x.pdf": "junk"}))
        self.ok("extract.py", "--data", self.data)
        self.ok("pipeline.py", "queue", "--data", self.data)
        self.ok("precision.py", "--data", self.data)
        self.ok("metrics.py", "--data", self.data)
        self.ok("interviews.py", "--data", self.data, "lessons")


class MalformedDates(SampleCase):
    def test_queue_survives_a_bad_event_date(self):
        p = self.data / "6-system/jobs/9100000001.json"
        edit_json(p, lambda j: j["pipeline"]["events"].append({"date": "next week", "stage": "response"}))
        self.ok("pipeline.py", "queue", "--data", self.data)
        self.ok("interviews.py", "--data", self.data, "due", "--soon", "30")

    def test_modes_survive_a_bad_round_date(self):
        def bad(m):
            m["rounds"][0]["date"] = "2026-99-99"
        edit_json(self.data / "6-system/metrics.json", bad)
        self.ok("modes.py", "signals", "--data", self.data)
        self.ok("build_report.py", "--data", self.data, "--round", "2")

    def test_staleness_survives_a_bad_extracted_at(self):
        p = self.data / "6-system/jobs/ext-northwind-freight-sr-pm.json"
        edit_json(p, lambda j: j.update(extracted_at="unknown"))
        self.ok("staleness.py", "--data", self.data, "status", "--all")
        code, out = run("staleness.py", "--data", self.data, "gate", "northwind")
        self.assertEqual(code, 1)
        self.assertIn("CHECK FIRST", out)

    def test_safe_date_helper(self):
        from paths import to_date
        self.assertIsNone(to_date("2026-99-99"))
        self.assertIsNone(to_date(None))
        self.assertEqual(str(to_date("2026-11-19T05:13:00")), "2026-11-19")

    def test_safe_date_rejects_trailing_junk(self):
        # Copilot review round 3: slicing to 10 characters read '2026-11-24junk' as a real date.
        from paths import to_date
        import triaged
        self.assertIsNone(to_date("2026-11-24junk"))
        self.assertIsNone(to_date("2026-11-241"))
        self.assertEqual(str(to_date("2026-11-19 05:13:00")), "2026-11-19")
        self.assertEqual(str(to_date("2026-11-19")), "2026-11-19")
        self.assertEqual(triaged._dates({"seen": [{"date": "2026-11-24junk"}]}), [])


class Metrics(SampleCase):
    def test_round_after_backfilled_rounds_is_estimated_not_inflated(self):
        def backfilled(m):
            for r in m["rounds"]:
                r.pop("job_ids", None)
            m["rounds"] = [r for r in m["rounds"] if r["round"] == 1]   # round 1 backfilled, no job IDs
        edit_json(self.data / "6-system/metrics.json", backfilled)
        out = self.ok("metrics.py", "--round", "2", "--data", self.data)
        m = json.loads((self.data / "6-system/metrics.json").read_text(encoding="utf-8"))
        r2 = next(r for r in m["rounds"] if r["round"] == 2)
        all_jobs = len(r2["job_ids"])
        self.assertLess(r2["pdfs_new"], all_jobs)
        self.assertTrue(r2.get("pdfs_new_estimated"))
        self.assertIn("estimated", out)


if __name__ == "__main__":
    unittest.main()
