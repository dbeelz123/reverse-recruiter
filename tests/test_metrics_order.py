"""metrics.py runs before build_report.py in a round (docs: run order), so it must count qualified targets from the
review files, not from the job records' copies, which only the report refreshes."""
import json

import helpers


class MetricsBeforeReport(helpers.SampleCase):
    def ranked_end(self, rnd):
        m = json.loads((self.data / "6-system" / "metrics.json").read_text(encoding="utf-8"))
        return next(r for r in m["rounds"] if r["round"] == rnd)["ranked_end"]

    def test_a_dealbreaker_added_in_the_review_file_counts_before_the_report(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        self.ok("metrics.py", "--data", self.data, "--round", "2")
        before = self.ranked_end(2)
        # Calibration or the re-screen marks a ranked job X in its review file; the report hasn't run yet.
        for f in sorted((self.data / "6-system" / "reviews").glob("round-*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            ranked = [k for k, e in r["jobs"].items() if e.get("tier") not in ("X", "?")]
            if ranked:
                r["jobs"][ranked[0]]["tier"] = "X"
                f.write_text(json.dumps(r), encoding="utf-8")
                break
        self.ok("metrics.py", "--data", self.data, "--round", "2")
        self.assertEqual(self.ranked_end(2), before - 1)

    def test_a_new_review_counts_before_the_report(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        self.ok("metrics.py", "--data", self.data, "--round", "2")
        before = self.ranked_end(2)
        # A job reviewed for the first time this round: its record has no review yet.
        rf = self.data / "6-system" / "reviews" / "round-02.json"
        r = json.loads(rf.read_text(encoding="utf-8"))
        jobs = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (self.data / "6-system" / "jobs").glob("*.json")}
        jid, rec = next((k, j) for k, j in jobs.items() if (j.get("review") or {}).get("tier") in ("X", "?"))
        r["jobs"][jid] = {"fit": 70, "tier": "B", "network_bonus": 0, "adjustments": [], "summary": "re-reviewed"}
        rf.write_text(json.dumps(r), encoding="utf-8")
        self.ok("metrics.py", "--data", self.data, "--round", "2")
        self.assertEqual(self.ranked_end(2), before + 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
