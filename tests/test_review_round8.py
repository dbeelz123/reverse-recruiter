"""Fixes from the eighth code review: each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest

from helpers import SampleCase, run


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class OpenCheckDates(SampleCase):
    def test_a_malformed_stored_date_does_not_block_a_new_check(self):
        p = self.data / "6-system/jobs/9100000006.json"
        edit_json(p, lambda j: j.update(open_check={"date": "last week", "result": "open", "source": "hand"}))
        self.ok("staleness.py", "--data", self.data, "confirm", "9100000006", "closed", "--date", "2026-11-19")
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["open_check"]["result"], "closed")

    def test_an_older_check_still_never_overwrites_a_newer_one(self):
        from staleness import set_check
        from paths import Paths
        P = Paths(self.data)
        job = {"job_id": "x", "open_check": {"date": "2026-11-19", "result": "open", "source": "hand"}}
        P.jobs.mkdir(parents=True, exist_ok=True)
        self.assertFalse(set_check(P, job, "closed", "2026-11-10", "paste"))
        self.assertEqual(job["open_check"]["result"], "open")


class DamagedDocx(SampleCase):
    def fake_docx(self, name="bad.docx", content=b"not a zip file"):
        p = self.tmp / name
        p.write_bytes(content)
        return p

    def test_tailor_refuses_a_damaged_resume_cleanly(self):
        edits = self.tmp / "edits.json"
        edits.write_text("[]", encoding="utf-8")
        code, out = run("tailor_resume.py", self.fake_docx(), self.tmp / "out.docx", edits)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("bad.docx", out)
        self.assertFalse((self.tmp / "out.docx").exists())

    def test_tailor_refuses_damaged_edits_cleanly(self):
        import zipfile
        src = self.tmp / "resume.docx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("word/document.xml", "<w:document xmlns:w='w'/>")
        edits = self.tmp / "edits.json"
        edits.write_text('[["only", "three", "items"]]', encoding="utf-8")
        code, out = run("tailor_resume.py", src, self.tmp / "out.docx", edits)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("edits.json", out)

    def test_external_ingest_refuses_a_damaged_docx_cleanly(self):
        bad = self.data / "1-inbox/role-explorer/bad.docx"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not a zip file")
        before = sorted(p.name for p in (self.data / "6-system/jobs").glob("*.json"))
        code, out = run("ingest_external.py", bad, "--id", "ext-acme-pm", "--company", "Acme", "--title", "PM", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("bad.docx", out)
        self.assertEqual(sorted(p.name for p in (self.data / "6-system/jobs").glob("*.json")), before)


class MetricsTiming(SampleCase):
    def test_a_malformed_timing_event_is_skipped(self):
        def bad(m):
            m["rounds"][-1].setdefault("events", []).append({"stage": "review", "t": "not-a-time"})
        edit_json(self.data / "6-system/metrics.json", bad)
        code, out = run("metrics.py", "--data", self.data)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)


class BlocklistEntries(SampleCase):
    def test_a_blocklist_entry_without_a_name_is_named(self):
        edit_json(self.data / "5-criteria/spec.json",
                  lambda s: s.setdefault("company_blocklist", []).append({"status": "confirmed"}))
        for script, args in (("build_report.py", ("--round", "2")), ("rescreen.py", ())):
            with self.subTest(script=script):
                code, out = run(script, "--data", self.data, *args)
                self.assertNotEqual(code, 0)
                self.assertNotIn("Traceback", out)
                self.assertIn("company_blocklist", out)


if __name__ == "__main__":
    unittest.main()
