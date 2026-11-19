"""Fixes from the seventh code review: each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest

from helpers import SampleCase, run


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class ReportReviewFiles(SampleCase):
    def test_a_review_round_that_is_not_an_object_is_named(self):
        (self.data / "6-system/reviews/round-01.json").write_text("[]", encoding="utf-8")
        code, out = run("build_report.py", "--data", self.data, "--round", "2")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("round-01.json", out)


class RemovalJobRecord(SampleCase):
    def test_a_damaged_job_record_stops_before_anything_changes(self):
        rec = self.data / "6-system/jobs/9100000006.json"
        rec.write_text("[]", encoding="utf-8")
        before = (self.data / "6-system/removed.json").read_text(encoding="utf-8")
        code, out = run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("9100000006.json", out)
        self.assertEqual((self.data / "6-system/removed.json").read_text(encoding="utf-8"), before)
        self.assertTrue(rec.exists())


class InterviewOnClosedJob(SampleCase):
    JOB = "9100000006"

    def close_job(self):
        self.ok("pipeline.py", "record", self.JOB, "closed", "--date", "2026-11-12", "--data", self.data)

    def status(self):
        rec = json.loads((self.data / f"6-system/jobs/{self.JOB}.json").read_text(encoding="utf-8"))
        return (rec.get("pipeline") or {}).get("status")

    def test_scheduling_does_not_silently_reopen_a_closed_job(self):
        self.close_job()
        code, out = run("interviews.py", "--data", self.data, "schedule", self.JOB, "--round", "1")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("--reopen", out)
        self.assertEqual(self.status(), "closed")

    def test_reopen_schedules_and_records_why(self):
        self.close_job()
        self.ok("interviews.py", "--data", self.data, "schedule", self.JOB, "--round", "1", "--reopen")
        self.assertEqual(self.status(), "interview")
        rec = json.loads((self.data / f"6-system/jobs/{self.JOB}.json").read_text(encoding="utf-8"))
        self.assertIn("reopened", rec["pipeline"]["events"][-1]["note"])


class TailorOutputFolder(SampleCase):
    def test_a_missing_output_folder_is_a_clear_error(self):
        import zipfile
        src = self.tmp / "resume.docx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
                                            '</w:body></w:document>')
        edits = self.tmp / "edits.json"
        edits.write_text(json.dumps([["Hello", "", "Hello", "Hi", ""]]), encoding="utf-8")
        dst = self.tmp / "missing" / "out.docx"
        code, out = run("tailor_resume.py", src, dst, edits)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("missing", out)
        self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
