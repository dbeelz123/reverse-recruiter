"""Bad or missing input stops with a clear message, never a raw traceback, and never stops a whole round."""
import json
import os
import unittest

from helpers import SampleCase, run


class Json(SampleCase):
    def test_damaged_file_named_in_the_error(self):
        spec = self.data / "5-criteria/spec.json"
        spec.write_text('{"version": "0.2",', encoding="utf-8")
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertIn("Damaged data file", out)
        self.assertIn("spec.json", out)
        self.assertNotIn("Traceback", out)

    def test_write_json_is_atomic_and_keeps_format(self):
        from paths import read_json, write_json
        p = self.tmp / "x.json"
        write_json(p, {"a": "é"}, indent=1, ensure_ascii=True, newline=True)
        self.assertEqual(p.read_text(encoding="utf-8"), '{\n "a": "\\u00e9"\n}\n')
        self.assertFalse((self.tmp / "x.json.tmp").exists())
        self.assertEqual(read_json(p), {"a": "é"})
        self.assertEqual(read_json(self.tmp / "missing.json", []), [])
        with self.assertRaises(SystemExit):
            read_json(self.tmp / "missing.json")


class Report(SampleCase):
    def test_missing_round(self):
        code, out = run("build_report.py", "--data", self.data, "--round", "9")
        self.assertNotEqual(code, 0)
        self.assertIn("No usable review file for round 9", out)

    def test_earlier_rounds_are_archived(self):
        reports = self.data / "2-reports"
        (reports / "2026-11-10-round-01-report.md").write_text("old", encoding="utf-8")
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        self.assertFalse((reports / "2026-11-10-round-01-report.md").exists())
        self.assertTrue((reports / "archive/2026-11-10-round-01-report.md").exists())
        self.assertTrue((reports / "2026-11-14-round-02-report.md").exists())


class Dates(SampleCase):
    def set_open_check(self, date):
        p = self.data / "6-system/jobs/9100000002.json"
        j = json.loads(p.read_text(encoding="utf-8"))
        j["open_check"] = {"date": date, "result": "open", "source": "test"}
        p.write_text(json.dumps(j), encoding="utf-8")

    def test_bad_date_arguments_rejected(self):
        code, _ = run("staleness.py", "--data", self.data, "confirm", "cobalt", "open", "--date", "2026-13-45")
        self.assertEqual(code, 2)
        code, _ = run("pipeline.py", "record", "cobalt", "outreach", "--date", "notadate", "--data", self.data)
        self.assertEqual(code, 2)

    def test_bad_stored_date_means_check_first(self):
        self.set_open_check("last tuesday")
        code, out = run("staleness.py", "--data", self.data, "gate", "cobalt")
        self.assertEqual(code, 1)
        self.assertIn("CHECK FIRST", out)

    def test_future_date_is_never_fresh(self):
        self.set_open_check("2999-01-01")
        code, out = run("staleness.py", "--data", self.data, "gate", "cobalt")
        self.assertEqual(code, 1)
        self.assertIn("in the future", out)


class Inputs(SampleCase):
    def test_triage_seed_without_or_with_bad_tombstones(self):
        os.remove(self.data / "6-system/removed.json")
        self.ok("triaged.py", "seed", "--data", self.data)
        (self.data / "6-system/removed.json").write_text('[{"job_id": "x1"}, "junk", {"reason": "no id"}]',
                                                         encoding="utf-8")
        self.ok("triaged.py", "seed", "--data", self.data)

    def test_external_job_must_be_inside_the_data_folder(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("About the role", encoding="utf-8")
        code, out = run("ingest_external.py", outside, "--id", "ext-x", "--company", "A", "--title", "B",
                        "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertIn("outside the data folder", out)

    def test_external_job_on_a_fresh_folder_and_old_status_spelling(self):
        fresh = self.tmp / "fresh"
        desc = fresh / "3-applications/k/d.txt"
        desc.parent.mkdir(parents=True)
        desc.write_text("About the role", encoding="utf-8")
        self.ok("ingest_external.py", desc, "--id", "ext-y", "--company", "A", "--title", "B",
                "--status", "interviewing", "--data", fresh)
        rec = json.loads((fresh / "6-system/jobs/ext-y.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["pipeline"]["status"], "interview")

    def test_old_interviewing_status_counts_in_the_funnel(self):
        from pipeline import STAGES, reached
        self.assertEqual(reached({"status": "interviewing", "events": []}, False), STAGES.index("interview"))

    def test_unreadable_pdf_is_skipped_not_fatal(self):
        bad = self.data / "1-inbox/job-pdfs/broken.pdf"
        bad.write_bytes(b"not really a pdf")
        out = self.ok("extract.py", "--data", self.data)
        self.assertIn("SKIP (unreadable PDF", out)
        ledger = (self.data / "6-system/ledger.json")
        self.assertNotIn("broken.pdf", ledger.read_text(encoding="utf-8") if ledger.exists() else "")


if __name__ == "__main__":
    unittest.main()
