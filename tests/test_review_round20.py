"""Fixes from the review of commit f729e09 (2026-11-28, areas 2 and 8: ingest, command lines): each test reproduces
the reported problem and checks the fixed behavior."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import ENGINE, REPO, SampleCase, run


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ExternalIngest(SampleCase):
    """#1: a description no text can be read from (an image-only PDF, a damaged PDF, an empty file) stops the
    ingest with the file named; no job record and no ledger entry is written."""

    def setUp(self):
        super().setUp()
        self.kit = self.data / "3-applications/acme-pm"
        self.kit.mkdir(parents=True)
        self.jobs = self.data / "6-system/jobs"
        self.before = (sorted(p.name for p in self.jobs.glob("*.json")),
                       (self.data / "6-system/ledger.json").read_text(encoding="utf-8"))

    def ingest(self, f):
        return run("ingest_external.py", f, "--id", "ext-acme-pm", "--company", "Acme", "--title", "PM",
                   "--data", self.data)

    def refused(self, f):
        code, out = self.ingest(f)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn(f.name, out)
        self.assertEqual((sorted(p.name for p in self.jobs.glob("*.json")),
                          (self.data / "6-system/ledger.json").read_text(encoding="utf-8")), self.before)
        return out

    def test_a_pdf_with_no_text_is_refused(self):
        import pymupdf
        f = self.kit / "scan.pdf"
        doc = pymupdf.open()
        doc.new_page()  # a page with nothing on it, as a scanned posting reads: pictures, no text
        doc.save(f)
        doc.close()
        self.assertIn("no text", self.refused(f).lower())

    def test_a_damaged_pdf_is_refused(self):
        f = self.kit / "broken.pdf"
        f.write_bytes(b"%PDF-1.7\nthis is not a pdf\n")
        self.refused(f)
        f.write_bytes(b"")
        self.refused(f)

    def test_an_empty_text_file_is_refused(self):
        for name, content in (("empty.txt", ""), ("blank.md", " \n\t\n")):
            with self.subTest(name=name):
                f = self.kit / name
                f.write_text(content, encoding="utf-8")
                self.refused(f)

    def test_a_refused_file_creates_no_jobs_folder(self):
        fresh = self.tmp / "fresh"
        (fresh / "3-applications/k").mkdir(parents=True)
        f = fresh / "3-applications/k/empty.txt"
        f.write_text("", encoding="utf-8")
        code, out = run("ingest_external.py", f, "--id", "ext-y", "--company", "A", "--title", "B", "--data", fresh)
        self.assertNotEqual(code, 0, out)
        self.assertFalse((fresh / "6-system").exists())

    def test_a_readable_pdf_is_still_ingested(self):
        import pymupdf
        f = self.kit / "posting.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Senior Product Manager. Own the roadmap.")
        doc.save(f)
        doc.close()
        code, out = self.ingest(f)
        self.assertEqual(code, 0, out)
        self.assertIn("Own the roadmap", read(self.jobs / "ext-acme-pm.json")["posting_text"])


class DataFlagOverBadSetting(SampleCase):
    """#2: an explicit --data wins over the environment setting even when the setting names a folder that isn't
    there. triaged.py read the setting when it was imported, before the command line, so it and every script that
    imports it (metrics.py, modes.py, extract.py, the LinkedIn scripts) stopped on the bad setting."""

    def run_with_setting(self, setting, script, *args):
        env = {k: v for k, v in os.environ.items() if k != "PRIVATE_TERMS"}
        env.update(REVERSE_RECRUITER_DATA=str(setting), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", str(ENGINE / script), *map(str, args)], cwd=REPO,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return r.returncode, r.stdout + r.stderr

    def test_data_flag_overrides_a_missing_setting_folder(self):
        gone = self.tmp / "gone"
        run_file = self.data / "6-system/search-runs/s1-run-2026-11-13.json"
        for script, args in (("triaged.py", ("--data", self.data, "keeps", run_file)),
                             ("triaged.py", ("reposts", "--data", self.data)),
                             ("metrics.py", ("--data", self.data)),
                             ("modes.py", ("--data", self.data, "signals")),
                             ("extract.py", ("--data", self.data)),
                             ("linkedin_project.py", ("check", "--data", self.data))):
            with self.subTest(script=script, args=args[:1]):
                code, out = self.run_with_setting(gone, script, *args)
                self.assertEqual(code, 0, out)
                self.assertNotIn("isn't a folder", out)
        self.assertFalse(gone.exists())
        self.assertTrue((self.data / "2-reports/repost-watch.md").exists())  # written in the folder --data named

    def test_without_the_flag_the_bad_setting_is_still_reported(self):
        gone = self.tmp / "gone"
        for script, args in (("triaged.py", ("reposts",)), ("metrics.py", ())):
            with self.subTest(script=script):
                code, out = self.run_with_setting(gone, script, *args)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("REVERSE_RECRUITER_DATA", out)
                self.assertIn("gone", out)

    def test_a_good_setting_still_serves_when_no_flag_is_given(self):
        code, out = self.run_with_setting(self.data, "triaged.py", "reposts")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.data / "2-reports/repost-watch.md").exists())

    def test_importing_the_module_never_stops_on_the_setting(self):
        code = ("import os, sys; os.environ['REVERSE_RECRUITER_DATA'] = sys.argv[1]; "
                "sys.path.insert(0, sys.argv[2]); import triaged; print(triaged.key('Acme Inc', 'Sr PM'))")
        r = subprocess.run([sys.executable, "-B", "-c", code, str(self.tmp / "gone"), str(ENGINE)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("acme|senior product manager", r.stdout)


if __name__ == "__main__":
    unittest.main()
