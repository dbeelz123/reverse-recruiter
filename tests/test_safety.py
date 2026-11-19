"""File-safety guards: nothing outside its own folder is ever deleted or overwritten."""
import json
import unittest

from helpers import SampleCase, run


class RemoveJob(SampleCase):
    def test_only_inbox_files_are_deleted_and_tombstone_written(self):
        precious = self.tmp / "precious.txt"
        precious.write_text("keep me", encoding="utf-8")
        inbox = self.data / "1-inbox/job-pdfs"
        (inbox / "real.pdf").write_text("pdf", encoding="utf-8")
        rec_p = self.data / "6-system/jobs/9100000006.json"
        rec = json.loads(rec_p.read_text(encoding="utf-8"))
        rec["source_files"] = ["1-inbox/job-pdfs/real.pdf", "../precious.txt"]
        rec_p.write_text(json.dumps(rec), encoding="utf-8")
        out = self.ok("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertTrue(precious.exists(), "a file outside the inbox was deleted")
        self.assertIn("LEFT ALONE", out)
        self.assertFalse((inbox / "real.pdf").exists())
        self.assertFalse(rec_p.exists())
        tombs = json.loads((self.data / "6-system/removed.json").read_text(encoding="utf-8"))
        self.assertTrue(any(t["job_id"] == "9100000006" for t in tombs))

    def test_path_like_job_id_refused(self):
        code, _ = run("remove_job.py", "../evil", "--reason", "x", "--data", self.data)
        self.assertNotEqual(code, 0)


class SampleGenerator(SampleCase):
    def test_refuses_a_folder_it_did_not_make(self):
        foreign = self.tmp / "notsample"
        foreign.mkdir()
        (foreign / "file.txt").write_text("keep", encoding="utf-8")
        code, out = run("scripts/make_sample_data.py", "--out", foreign)
        self.assertNotEqual(code, 0)
        self.assertEqual((foreign / "file.txt").read_text(encoding="utf-8"), "keep")

    def test_refuses_the_repo_root(self):
        from helpers import REPO
        code, _ = run("scripts/make_sample_data.py", "--out", REPO)
        self.assertNotEqual(code, 0)


class TailorResume(SampleCase):
    def test_never_overwrites_the_source(self):
        src = self.tmp / "resume.docx"
        src.write_text("original", encoding="utf-8")
        edits = self.tmp / "edits.json"
        edits.write_text("[]", encoding="utf-8")
        code, _ = run("tailor_resume.py", src, src, edits)
        self.assertNotEqual(code, 0)
        self.assertEqual(src.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
