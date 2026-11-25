"""Fixes from the third whole-project code review (2026-11-25, commit e6ec53e): each test reproduces the reported
problem and checks the fixed behavior."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import SampleCase, run


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class ConnectionNames(unittest.TestCase):
    """#1: names with lowercase particles or an accented first letter are read from a _people PDF."""

    def test_particles_and_accents(self):
        from extract import parse_people
        lines = ["Jamie van der Meer • 1st", "Director of Platform at Example Co",
                 "Élodie Martin • 1st", "Staff Engineer at Example Co",
                 "Ana de la Cruz, M.S. • 1st", "VP Product",
                 "Sam Ortiz • 2nd", "Not first degree"]
        names = sorted(p["name"] for p in parse_people(lines))
        self.assertEqual(names, ["Ana de la Cruz", "Jamie van der Meer", "Élodie Martin"])

    def test_plain_names_still_work_and_a_lowercase_start_is_not_a_name(self):
        from extract import parse_people
        names = [p["name"] for p in parse_people(["Jane Doe • 1st", "PM", "about the role • 1st", "x"])]
        self.assertEqual(names, ["Jane Doe"])


class PrivacyEncodings(SampleCase):
    """#2: UTF-16 text is decoded and scanned; other text with NUL bytes counts as unreadable (a hit)."""

    def scan(self, folder):
        terms = self.tmp / "terms.txt"
        terms.write_text("Zanzibar Widgets\n", encoding="utf-8")
        return run("privacy_scan.py", folder, "--terms", terms, "--strict")

    def test_utf16_text_is_scanned(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "notes.txt").write_bytes("worked at Zanzibar Widgets\n".encode("utf-16"))  # with a BOM
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("Zanzibar Widgets", out)

    def test_nul_bytes_without_a_bom_are_a_hit(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "notes.txt").write_bytes("worked at Zanzibar Widgets\n".encode("utf-16-le"))  # no BOM
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("notes.txt", out)

    def test_plain_text_still_passes(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "notes.txt").write_text("nothing private\n", encoding="utf-8")
        code, out = self.scan(folder)
        self.assertEqual(code, 0, out)


class PipelineLateRecord(SampleCase):
    """#9: recording a stage dated before a later stage already recorded doesn't move the status back."""
    JOB = "9100000006"

    def test_an_earlier_dated_stage_keeps_the_later_status(self):
        d = ("--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-10", *d)
        self.ok("pipeline.py", "record", self.JOB, "interview", "--date", "2026-11-20", *d)
        out = self.ok("pipeline.py", "record", self.JOB, "response", "--date", "2026-11-15", *d)
        pl = read(self.data / f"6-system/jobs/{self.JOB}.json")["pipeline"]
        self.assertEqual(pl["status"], "interview")
        self.assertIn("response", [e["stage"] for e in pl["events"]])
        self.assertIn("interview", out)

    def test_a_later_stage_still_moves_the_status(self):
        d = ("--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-10", *d)
        self.ok("pipeline.py", "record", self.JOB, "rejected", "--date", "2026-11-12", *d)
        self.assertEqual(read(self.data / f"6-system/jobs/{self.JOB}.json")["pipeline"]["status"], "rejected")


class DebriefDueDates(SampleCase):
    """#10: a repeated debrief keeps the thank-you due date; an unreadable stored date never crashes 'due'."""
    JOB = "9100000006"

    def debrief(self):
        f = self.tmp / "debrief.json"
        f.write_text(json.dumps({"how": "fine", "thank_you_to": ["the panel"]}), encoding="utf-8")
        self.ok("interviews.py", "--data", self.data, "debrief", self.JOB, "--round", "1", "--file", f)

    def iv(self):
        return read(self.data / f"6-system/jobs/{self.JOB}.json")["interviews"][0]

    def test_repeat_debrief_keeps_the_due_date(self):
        self.debrief()
        edit_json(self.data / f"6-system/jobs/{self.JOB}.json",
                  lambda j: j["interviews"][0]["thank_you"].update(due="2026-11-01"))
        self.debrief()
        self.assertEqual(self.iv()["thank_you"]["due"], "2026-11-01")

    def test_unreadable_due_date_does_not_crash(self):
        self.debrief()
        edit_json(self.data / f"6-system/jobs/{self.JOB}.json",
                  lambda j: j["interviews"][0]["thank_you"].update(due="next week"))
        code, out = run("interviews.py", "--data", self.data, "due", "--soon", "30")
        self.assertNotIn("Traceback", out)


class DamagedReviewAndRemovalFiles(SampleCase):
    """#11: an adjustment without a reason, and a removed.json that isn't a list, stop with the file named."""

    def test_adjustment_without_reason_stops_the_report(self):
        def bad(r):
            jid = next(iter(r["jobs"]))
            r["jobs"][jid]["adjustments"] = [{"points": 4}]
        edit_json(self.data / "6-system/reviews/round-02.json", bad)
        code, out = run("build_report.py", "--data", self.data, "--round", "2")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("reason", out)

    def test_removed_json_that_is_not_a_list_stops(self):
        (self.data / "6-system/removed.json").write_text('{"9100000099": {"reason": "x"}}', encoding="utf-8")
        for args in (("pipeline.py", "queue"), ("triaged.py", "seed")):
            with self.subTest(args=args):
                code, out = run(*args, "--data", self.data)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("removed.json", out)


class PartialRows(SampleCase):
    """#12: a half-filled row or missing headers stop with the row or header named; blank rows are still skipped."""

    def ingest(self, name, text):
        src = self.tmp / name
        src.write_text(text, encoding="utf-8")
        return run("ingest_results.py", src, self.tmp / "cards.json")

    def test_a_row_with_company_but_no_title_stops(self):
        code, out = self.ingest("rows.json", json.dumps([
            {"title": "PM", "company": "Acme", "location": "Remote"},
            {"title": "", "company": "Beta", "location": "Remote"}]))
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("row 2", out)
        self.assertFalse((self.tmp / "cards.json").exists())

    def test_csv_without_title_or_company_headers_stops(self):
        code, out = self.ingest("rows.csv", "name,employer,location\nPM,Acme,Remote\n")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("title", out)

    def test_blank_rows_are_still_skipped(self):
        code, out = self.ingest("rows.csv", "title,company,location\nPM,Acme,Remote\n,,\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(read(self.tmp / "cards.json")), 1)


class ProjectUpdateOrder(SampleCase):
    """#13: 'update' checks the description before rendering any image."""

    def test_missing_numbers_sentence_stops_before_rendering(self):
        import linkedin_project
        from paths import Paths
        P = Paths(str(self.data))
        P.linkedin_dir.mkdir(parents=True, exist_ok=True)
        (P.linkedin_dir / "linkedin-profile.md").write_text("no numbers sentence here\n", encoding="utf-8")
        with mock.patch.object(linkedin_project.linkedin_images, "main") as render:
            with self.assertRaises(SystemExit) as e:
                linkedin_project.update(P)
        render.assert_not_called()
        self.assertIn("numbers sentence", str(e.exception))


class EmptyScreenshot(unittest.TestCase):
    """#14: an empty screenshot is a failure, never moved into place."""

    def test_zero_byte_screenshot_fails(self):
        import linkedin_images
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out_png = tmp / "out" / "funnel.png"
            out_png.parent.mkdir()

            def fake_browser(cmd, **kw):
                (tmp / "funnel.png").write_bytes(b"")  # the browser leaves an empty file
            with mock.patch.object(linkedin_images.subprocess, "run", fake_browser), \
                    mock.patch.object(linkedin_images.time, "sleep", lambda s: None):
                with self.assertRaises(SystemExit):
                    linkedin_images.render("browser.exe", "<html></html>", out_png, tmp)
            self.assertFalse(out_png.exists())


if __name__ == "__main__":
    unittest.main()
