"""Fixes from the sixth code review: each test reproduces the reported problem and checks the fixed behavior."""
import json
import os
import unittest
import zipfile

from helpers import SampleCase, run


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class PrivacyScanBinaries(SampleCase):
    def scan(self, folder):
        terms = self.tmp / "terms.txt"
        terms.write_text("Zanzibar Widgets\n", encoding="utf-8")
        return run("privacy_scan.py", folder, "--terms", terms, "--strict")

    def test_an_archive_is_a_hit(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        with zipfile.ZipFile(folder / "export.zip", "w") as z:
            z.writestr("notes.txt", "worked at Zanzibar Widgets")
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("export.zip", out)

    def test_text_with_an_unlisted_extension_is_scanned(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "notes.log").write_text("worked at Zanzibar Widgets\n", encoding="utf-8")
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("Zanzibar Widgets", out)

    def test_an_image_passes_only_once_checked_and_listed(self):
        # Changed 2026-11-25 (second whole-project review): an image used to pass with a warning; now it fails
        # until it's checked by eye and listed in .privacy-allow.
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(20))
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("chart.png", out)
        self.assertIn("by eye", out)
        (folder / ".privacy-allow").write_text("chart.png | image checked by eye\n", encoding="utf-8")
        code, out = self.scan(folder)
        self.assertEqual(code, 0, out)


class RescreenReviewChecks(SampleCase):
    def test_a_damaged_review_file_is_named(self):
        p = self.data / "6-system/reviews/round-02.json"
        p.write_text("[]", encoding="utf-8")
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("round-02.json", out)

    def test_an_adjustment_without_points_is_named(self):
        p = self.data / "6-system/reviews/round-02.json"
        def bad(r):
            jid = next(iter(r["jobs"]))
            r["jobs"][jid]["adjustments"] = [{"reason": "no points"}]
        edit_json(p, bad)
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("adjustments", out)


class IngestLocation(SampleCase):
    def test_a_row_without_location_stops(self):
        src = self.tmp / "rows.json"
        src.write_text(json.dumps([{"title": "PM", "company": "Acme"}]), encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("row 1", out)
        self.assertIn("location", out)
        self.assertFalse((self.tmp / "cards.json").exists())

    def test_a_csv_without_the_location_column_stops(self):
        src = self.tmp / "rows.csv"
        src.write_text("title,company\nPM,Acme\n", encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("location", out)


class RemovalSafety(SampleCase):
    def test_a_damaged_ledger_stops_before_anything_changes(self):
        (self.data / "6-system/ledger.json").write_text("[]", encoding="utf-8")
        before = (self.data / "6-system/removed.json").read_text(encoding="utf-8")
        code, out = run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("ledger.json", out)
        self.assertEqual((self.data / "6-system/removed.json").read_text(encoding="utf-8"), before)
        self.assertTrue((self.data / "6-system/jobs/9100000006.json").exists())

    @unittest.skipUnless(os.name == "nt", "an open file blocks deletion only on Windows")
    def test_a_pdf_open_in_a_viewer_stops_cleanly_and_a_rerun_finishes(self):
        rec = json.loads((self.data / "6-system/jobs/9100000006.json").read_text(encoding="utf-8"))
        pdf = self.data / "1-inbox/job-pdfs/locked.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 test")
        rec["source_files"] = ["1-inbox/job-pdfs/locked.pdf"]
        (self.data / "6-system/jobs/9100000006.json").write_text(json.dumps(rec), encoding="utf-8")
        with open(pdf, "rb"):
            code, out = run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("locked.pdf", out)
        self.assertTrue((self.data / "6-system/jobs/9100000006.json").exists())  # kept, so a rerun finds the PDF
        code, out = run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertEqual(code, 0, out)
        self.assertFalse(pdf.exists())
        self.assertFalse((self.data / "6-system/jobs/9100000006.json").exists())

    def test_removal_works_on_a_minimal_data_folder(self):
        d = self.tmp / "minimal"
        (d / "6-system/jobs").mkdir(parents=True)
        (d / "6-system/jobs/9100000777.json").write_text(json.dumps(
            {"job_id": "9100000777", "company": "Test Co", "title": "PM"}), encoding="utf-8")
        code, out = run("remove_job.py", "9100000777", "--reason", "test", "--data", d)
        self.assertEqual(code, 0, out)
        self.assertFalse((d / "6-system/jobs/9100000777.json").exists())


class SampleGeneratorOwnership(SampleCase):
    def test_a_copied_readme_is_not_proof_of_ownership(self):
        from helpers import SAMPLE
        foreign = self.tmp / "my-copy"
        foreign.mkdir()
        (foreign / "README.md").write_text((SAMPLE / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
        (foreign / "my-notes.txt").write_text("keep", encoding="utf-8")
        code, out = run("scripts/make_sample_data.py", "--out", foreign)
        self.assertNotEqual(code, 0)
        self.assertEqual((foreign / "my-notes.txt").read_text(encoding="utf-8"), "keep")

    def test_a_copied_and_edited_sample_folder_is_not_replaced(self):
        out_dir = self.data  # a full copy of sample-data, manifest included
        spec = out_dir / "5-criteria/spec.json"
        spec.write_text(spec.read_text(encoding="utf-8").replace("{", "{\"edited\": true,", 1), encoding="utf-8")
        code, out = run("scripts/make_sample_data.py", "--out", out_dir)
        self.assertNotEqual(code, 0)
        self.assertIn("spec.json", out)
        self.assertIn("\"edited\": true", spec.read_text(encoding="utf-8"))

    def test_an_unchanged_sample_folder_is_replaced(self):
        code, out = run("scripts/make_sample_data.py", "--out", self.data)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.data / ".sample-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
