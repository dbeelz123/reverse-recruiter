"""Fixes from the fourth whole-project code review (2026-11-27, commit 86beb7f): each test reproduces the reported
problem and checks the fixed behavior."""
import json
import sys
import unittest
from unittest import mock

from helpers import SampleCase, run


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class RemovalTeaserGuard(SampleCase):
    """#2: a posting whose teaser points to a 1st-degree connection, with no connection recorded for the job, is
    not removed without confirmation. Alumni and 2nd/3rd-degree teasers don't hold a removal."""
    JOB = "9100000006"

    def teaser(self, *lines):
        edit_json(self.data / f"6-system/jobs/{self.JOB}.json",
                  lambda j: j.update(network_teaser=list(lines), connections_1st=[]))

    def remove(self, *extra):
        return run("remove_job.py", self.JOB, "--reason", "test", "--data", self.data, *extra)

    def test_an_in_your_network_teaser_holds_the_removal(self):
        self.teaser("Jane and others in your network")
        before = read(self.data / "6-system/removed.json")
        code, out = self.remove()
        self.assertNotEqual(code, 0, out)
        self.assertIn("Jane and others in your network", out)
        self.assertTrue((self.data / f"6-system/jobs/{self.JOB}.json").exists())
        self.assertEqual(read(self.data / "6-system/removed.json"), before)

    def test_a_first_degree_marker_holds_the_removal(self):
        self.teaser("Jane Doe    • 1st", "Director of Platform at Example Co")
        code, out = self.remove()
        self.assertNotEqual(code, 0, out)
        self.assertIn("Jane Doe", out)

    def test_alumni_and_other_degrees_do_not_hold_it(self):
        self.teaser("Sam Ortiz    • 3rd", "Engineer at Example Co", "School alumni from Example University")
        code, out = self.remove()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.data / f"6-system/jobs/{self.JOB}.json").exists())

    def test_confirmed_removal_goes_ahead(self):
        self.teaser("Jane and others in your network")
        code, out = self.remove("--confirm-connections")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.data / f"6-system/jobs/{self.JOB}.json").exists())


class ExternalIds(SampleCase):
    """#3: an external ID is letters, digits, hyphens and underscores only, so it can't name a path."""

    def ingest(self, jid):
        desc = self.data / "3-applications/x/d.txt"
        desc.parent.mkdir(parents=True, exist_ok=True)
        desc.write_text("About the role", encoding="utf-8")
        return run("ingest_external.py", desc, "--id", jid, "--company", "A", "--title", "B", "--data", self.data)

    def test_separators_and_dots_are_refused(self):
        (self.data / "6-system/jobs/ext-").mkdir()
        for jid in ("ext-a/b", "ext-\\..\\..\\..\\outside", "ext-/../../../outside", "ext-a.b", "ext-"):
            with self.subTest(jid=jid):
                code, out = self.ingest(jid)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("ext-", out)
        self.assertFalse((self.tmp / "outside.json").exists())
        self.assertFalse((self.data / "outside.json").exists())

    def test_a_plain_id_still_works(self):
        code, out = self.ingest("ext-acme_clinical-ai-pm2")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.data / "6-system/jobs/ext-acme_clinical-ai-pm2.json").exists())

    def test_a_record_that_is_not_an_object_stops_with_the_file_named(self):
        (self.data / "6-system/jobs/ext-odd.json").write_text("[]", encoding="utf-8")
        code, out = self.ingest("ext-odd")
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("ext-odd.json", out)


class ManifestShape(unittest.TestCase):
    """#5: a manifest that is valid JSON but not an object stops with the file named."""

    def test_a_list_manifest_is_refused(self):
        import tempfile
        from pathlib import Path
        import prep_pdf
        with tempfile.TemporaryDirectory() as td:
            kit = Path(td)
            for text in ("[]", '"packets"', "3"):
                (kit / prep_pdf.MANIFEST).write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(SystemExit) as e:
                    prep_pdf.load_manifest(kit)
                self.assertIn(prep_pdf.MANIFEST, str(e.exception))


class PipelineSameDay(SampleCase):
    """#6: an earlier stage recorded for the same day as a later one joins the history; the status stays."""
    JOB = "9100000006"

    def status(self):
        return read(self.data / f"6-system/jobs/{self.JOB}.json")["pipeline"]

    def test_same_day_earlier_stage_keeps_the_status(self):
        d = ("--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "interview", "--date", "2026-11-20", *d)
        out = self.ok("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-20", *d)
        pl = self.status()
        self.assertEqual(pl["status"], "interview")
        self.assertEqual([e["stage"] for e in pl["events"]][-2:], ["interview", "applied"])
        self.assertIn("status stays", out)

    def test_same_day_later_stage_still_moves_it(self):
        d = ("--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-20", *d)
        self.ok("pipeline.py", "record", self.JOB, "response", "--date", "2026-11-20", *d)
        self.assertEqual(self.status()["status"], "response")

    def test_same_day_outcome_still_closes_it(self):
        d = ("--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "interview", "--date", "2026-11-20", *d)
        self.ok("pipeline.py", "record", self.JOB, "rejected", "--date", "2026-11-20", *d)
        self.assertEqual(self.status()["status"], "rejected")


class ExtractRecordShape(SampleCase):
    """#7: an existing job record that isn't an object stops the extract with the file named."""

    def test_a_list_record_stops_cleanly(self):
        import extract
        pdfs = self.data / "1-inbox/job-pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        (pdfs / "job.pdf").write_bytes(b"%PDF-1.4")
        (self.data / "6-system/jobs/9100000777.json").write_text("[]", encoding="utf-8")
        ledger = (self.data / "6-system/ledger.json").read_text(encoding="utf-8")
        fake = ("9100000777", None, ("PM", "Acme"), ["About the job", "text"])
        with mock.patch.object(extract, "page_lines", lambda pdf: fake), \
                mock.patch.object(sys, "argv", ["extract.py", "--data", str(self.data)]):
            with self.assertRaises(SystemExit) as e:
                extract.main()
        self.assertIn("9100000777.json", str(e.exception))
        self.assertEqual((self.data / "6-system/ledger.json").read_text(encoding="utf-8"), ledger)


class CsvExtraFields(SampleCase):
    """#8: a CSV row with more fields than the header stops with the row named."""

    def test_an_overlong_row_stops(self):
        src = self.tmp / "rows.csv"
        src.write_text("title,company,location\nPM,Acme,Remote\nTPM,Beta,Remote,extra\n", encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("row 2", out)
        self.assertFalse((self.tmp / "cards.json").exists())


class ImagePairStaysWhole(SampleCase):
    """#10: when the second image fails to render, the previous pair stays in place untouched."""

    def test_a_failed_second_render_keeps_the_previous_pair(self):
        import linkedin_images as li

        def good(text):
            def render(browser, html, out_png, tmp):
                out_png.write_text(text, encoding="utf-8")
            return render

        def second_fails(browser, html, out_png, tmp):
            if "grade" in out_png.name:
                raise SystemExit("The browser did not write the image")
            out_png.write_text("new", encoding="utf-8")
        args = ["--data", str(self.data)]
        with mock.patch.object(li, "BROWSERS", [sys.executable]):
            with mock.patch.object(li, "render", good("old")):
                files = li.main(args)["files"]
            with mock.patch.object(li, "render", second_fails), self.assertRaises(SystemExit):
                li.main(args)
            self.assertEqual(len(files), 2)
            for f in files:
                self.assertEqual((self.data / f).read_text(encoding="utf-8"), "old", f)
            folder = (self.data / files[0]).parent
            self.assertEqual(sorted(p.name for p in folder.glob("*.png")), sorted(f.split("/")[-1] for f in files))
            self.assertFalse(list((folder / "archive").glob("*")) if (folder / "archive").exists() else [])
            # A full re-render still replaces both and archives the previous pair.
            with mock.patch.object(li, "render", good("new")):
                li.main(args)
            for f in files:
                self.assertEqual((self.data / f).read_text(encoding="utf-8"), "new", f)
            self.assertEqual(len(list((folder / "archive").glob("*.png"))), 2)


if __name__ == "__main__":
    unittest.main()
