"""Fixes from the review of commit 9871fd7 (2026-11-28, areas 1-3: data integrity, ingest, screening and removal):
each test reproduces the reported problem and checks the fixed behavior."""
import json
import sys
import unittest
from unittest import mock

from helpers import SampleCase, run

JOB = "9100000006"  # Lumen Cart - Senior Product Manager, Checkout and Delivery Options


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class MatchSavedKeepsAnotherJobsId(SampleCase):
    """#1: a run row that already carries a different job's ID isn't relinked to a saved job of the same company
    and title (a repost under a new ID, say); it is left as it is and listed."""

    def setUp(self):
        super().setUp()
        self.rec = read(self.data / f"6-system/jobs/{JOB}.json")
        self.run_file = self.data / "6-system/search-runs/s9-run-2026-11-20.json"

    def row(self, **extra):
        return dict({"id": "S9-001", "company": self.rec["company"], "title": self.rec["title"]}, **extra)

    def match(self, *rows):
        self.run_file.write_text(json.dumps({"search": "S9 test", "date": "2026-11-20", "round": 2,
                                             "listings": list(rows)}), encoding="utf-8")
        code, out = run("triaged.py", "match-saved", self.run_file, "--data", self.data)
        self.assertEqual(code, 0, out)
        return read(self.run_file)["listings"], out

    def test_a_different_id_is_left_alone_and_reported(self):
        for extra in ({"decision": "dq", "reason": "travel 50%"}, {}, {"decision": "keep", "status": "saved"}):
            with self.subTest(extra=extra):
                before = self.row(job_id="9100000900", **extra)
                rows, out = self.match(dict(before))
                self.assertEqual(rows[0], before)
                self.assertIn("S9-001", out)
                self.assertIn("9100000900", out)
                self.assertIn(JOB, out)
                self.assertIn("0 undecided rows now saved", out)
                self.assertIn("0 saved jobs DQ'd in this run", out)

    def test_a_row_without_an_id_is_still_linked(self):
        rows, out = self.match(self.row())
        self.assertEqual((rows[0]["job_id"], rows[0]["decision"]), (JOB, "keep"))
        self.assertIn("1 undecided rows now saved", out)

    def test_a_row_with_the_same_id_is_unchanged(self):
        before = self.row(job_id=JOB, decision="keep", reason="saved off-batch", status="saved (off-batch)")
        rows, out = self.match(dict(before))
        self.assertEqual(rows[0], before)
        self.assertNotIn("another job", out)


class ExtractLedgerAfterTheRepostCheck(SampleCase):
    """#2: a stop during the repost check leaves the PDFs unmarked, so the next run checks them again."""

    def test_an_interrupted_repost_check_is_run_again(self):
        import extract
        pdfs = self.data / "1-inbox/job-pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        (pdfs / "new.pdf").write_bytes(b"%PDF-1.4")
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": "9100000777", "removed": "2026-11-12", "reason": "hybrid too far"}])
        ledger_p = self.data / "6-system/ledger.json"
        ledger = ledger_p.read_text(encoding="utf-8")
        fake = ("9100000777", None, ("PM", "Acme"), ["Acme", "PM", "About the job", "text"])
        real_check = extract.repost_check

        def interrupted(*a, **k):
            raise KeyboardInterrupt
        with mock.patch.object(extract, "page_lines", lambda pdf: fake), \
                mock.patch.object(sys, "argv", ["extract.py", "--data", str(self.data)]):
            with mock.patch.object(extract, "repost_check", interrupted), self.assertRaises(KeyboardInterrupt):
                extract.main()
            self.assertEqual(ledger_p.read_text(encoding="utf-8"), ledger)
            with mock.patch.object(extract, "repost_check", real_check):
                extract.main()
        self.assertIn("new.pdf", ledger_p.read_text(encoding="utf-8"))
        rec = read(self.data / "6-system/jobs/9100000777.json")
        self.assertEqual(rec["previously_removed"], {"removed": "2026-11-12", "reason": "hybrid too far"})


class RescreenPatternTypes(SampleCase):
    """#3: a pattern in spec.json that isn't text stops with the file and the rule named."""

    def test_a_number_as_a_pattern(self):
        for field in ("title_regex", "rescreen_regex"):
            for bad in (7, ["a"], True):
                with self.subTest(field=field, bad=bad):
                    spec = self.data / "5-criteria/spec.json"
                    good = spec.read_text(encoding="utf-8")
                    edit_json(spec, lambda s: s["negatives"].append(
                        {"value": "Odd rule", field: bad, "status": "confirmed"}))
                    code, out = run("rescreen.py", "--data", self.data)
                    spec.write_text(good, encoding="utf-8")
                    self.assertNotEqual(code, 0, out)
                    self.assertNotIn("Traceback", out)
                    self.assertIn("spec.json", out)
                    self.assertIn("Odd rule", out)
                    self.assertIn(field, out)


if __name__ == "__main__":
    unittest.main()
