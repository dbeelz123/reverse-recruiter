"""Fixes from the review of commit 722797c (2026-11-28, areas 6 and 7: applications and interviews; privacy): each
test reproduces the reported problem and checks the fixed behavior."""
import datetime as dt
import json
import shutil
import unittest
from pathlib import Path

from helpers import SampleCase, run

JOB = "9100000002"
TODAY = dt.date.today()
HELD = (TODAY - dt.timedelta(days=6)).isoformat()   # the first sitting of round 1
AGAIN = (TODAY - dt.timedelta(days=1)).isoformat()  # the same round, held again


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ReopenedRound(SampleCase):
    """#1: a debriefed round scheduled again with --reopen starts clean. The first sitting's debrief and thank-you
    are kept, apart, so nothing the user said is lost and nothing of it passes for the new sitting's."""

    def setUp(self):
        super().setUp()
        self.job = self.data / f"6-system/jobs/{JOB}.json"
        self.iv("schedule", "--round", "1", "--date", HELD, "--with", "Dana (recruiter)")
        self.debrief({"how": "Went well", "asked": ["Why this role?"], "lessons": ["Lead with the launch story"],
                      "thank_you_to": ["Dana"]}, HELD)
        self.iv("sent", "--round", "1", "--date", HELD)

    def iv(self, cmd, *args):
        return self.ok("interviews.py", "--data", self.data, cmd, JOB, *args)

    def debrief(self, data, date):
        f = self.tmp / "debrief.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        return self.iv("debrief", "--round", "1", "--file", f, "--date", date)

    def round1(self):
        return [x for x in read(self.job)["interviews"] if str(x["round"]) == "1"][0]

    def test_the_reopened_round_starts_clean_and_keeps_the_first_sitting(self):
        out = self.iv("schedule", "--round", "1", "--date", AGAIN, "--reopen")
        r = self.round1()
        self.assertEqual((r["status"], r["date"]), ("scheduled", AGAIN))
        self.assertNotIn("debrief", r)
        self.assertNotIn("thank_you", r)
        self.assertEqual(len(r["earlier"]), 1)
        first = r["earlier"][0]
        self.assertEqual(first["date"], HELD)
        self.assertEqual(first["debrief"]["asked"], ["Why this role?"])
        self.assertEqual(first["thank_you"]["sent"], HELD)
        self.assertIn("earlier", out)

    def test_the_second_debrief_does_not_mix_with_the_first(self):
        self.iv("schedule", "--round", "1", "--date", AGAIN, "--reopen")
        self.debrief({"how": "Harder", "asked": ["Walk me through a failure"], "thank_you_to": ["Priya"]}, AGAIN)
        r = self.round1()
        self.assertEqual(r["debrief"]["asked"], ["Walk me through a failure"])  # was both sittings' questions
        self.assertNotIn("lessons", r["debrief"])
        # The new sitting's thank-you is owed: it used to inherit the first one's "sent" and due date.
        self.assertIsNone(r["thank_you"]["sent"])
        self.assertEqual(r["thank_you"]["to"], ["Priya"])
        self.assertEqual(r["thank_you"]["due"], TODAY.isoformat())
        due = self.ok("interviews.py", "--data", self.data, "due")
        self.assertIn("thank-you to Priya", due)

    def test_lessons_still_show_the_first_sitting(self):
        self.iv("schedule", "--round", "1", "--date", AGAIN, "--reopen")
        out = self.ok("interviews.py", "--data", self.data, "lessons")
        self.assertIn("Lead with the launch story", out)
        self.assertIn("why this role?", out)
        self.assertIn(HELD, out)
        self.debrief({"asked": ["Why this role?"], "lessons": ["Slow down"]}, AGAIN)
        out = self.ok("interviews.py", "--data", self.data, "lessons")
        self.assertIn("Slow down", out)
        self.assertIn("Lead with the launch story", out)
        self.assertIn("2x why this role?", out)  # asked at both sittings

    def test_a_round_that_was_only_scheduled_is_just_rescheduled(self):
        self.iv("schedule", "--round", "2", "--date", AGAIN)
        self.iv("schedule", "--round", "2", "--date", TODAY.isoformat(), "--reopen")
        r = [x for x in read(self.job)["interviews"] if str(x["round"]) == "2"][0]
        self.assertNotIn("earlier", r)
        self.assertEqual(r["date"], TODAY.isoformat())


class PrepPdfInputs(SampleCase):
    """#2: a preamble the manifest names, or a file given to `anonymize`, that isn't there is named in a message."""

    def fails(self, *args, mention):
        code, out = run("prep_pdf.py", *args)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn(mention, out)
        return out

    def test_missing_anonymize_inputs_are_named(self):
        src, rules, pre = self.tmp / "prep.md", self.tmp / "rules.txt", self.tmp / "pre.md"
        src.write_text("Acme is hiring.\n", encoding="utf-8")
        rules.write_text("Acme ==> the Client\n", encoding="utf-8")
        out = self.tmp / "clean.md"
        self.fails("anonymize", "--rules", rules, "--in", self.tmp / "gone.md", "--out", out, mention="gone.md")
        self.fails("anonymize", "--rules", self.tmp / "gone.txt", "--in", src, "--out", out, mention="gone.txt")
        o = self.fails("anonymize", "--rules", rules, "--in", src, "--out", out, "--preamble", pre, mention="pre.md")
        self.assertIn("--preamble", o)
        self.assertFalse(out.exists())
        self.fails("anonymize", "--rules", rules, "--in", self.tmp, "--out", out, mention="--in")  # a folder

    def test_a_missing_preamble_in_the_manifest_is_named(self):
        import prep_pdf
        kit = self.tmp / "kit"
        kit.mkdir()
        (kit / "notes.md").write_text("# Notes\nAcme is hiring.\n", encoding="utf-8")
        (kit / "anonymize-rules.txt").write_text("Acme ==> the Client\n", encoding="utf-8")
        m = {"packets": [{"source": "notes.md", "name": "01 Notes"}],
             "cleaned": {"include": ["01 Notes"], "preamble": "missing-preamble.md"}}
        with self.assertRaises(SystemExit) as e:
            prep_pdf.cleaned_markdown(kit, m)
        self.assertIn("missing-preamble.md", str(e.exception))
        self.assertIn("preamble", str(e.exception))
        (kit / "missing-preamble.md").write_text("Shared with names removed.\n", encoding="utf-8")
        md, _ = prep_pdf.cleaned_markdown(kit, m)
        self.assertTrue(md.startswith("Shared with names removed."))
        self.assertIn("the Client is hiring", md)


class RootHome(SampleCase):
    """#3: the Linux administrator's home folder (the "root" folder at the top of the disk) is a home-folder path
    too."""

    def scan(self, text):
        d = self.tmp / "scan"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        (d / "notes.md").write_text(text, encoding="utf-8")
        terms = self.tmp / "terms.txt"
        terms.write_text("Pinewick\n", encoding="utf-8")
        return run("privacy_scan.py", d, "--terms", terms)

    def test_root_home_paths_are_caught(self):
        base = "/" + "root" + "/"  # built at run time, so this file passes the repo's own scan
        for text in (f"saved to {base}alice/project.txt", f'{{"path": "{base}.config/app"}}', f"cd {base}work"):
            with self.subTest(text=text):
                code, out = self.scan(text)
                self.assertEqual(code, 1, out)
                self.assertIn("home-folder path", out)

    def test_other_uses_of_the_word_are_not_hits(self):
        for text in ("the repository root/ folder", "see https://docs.example.com/root/guide for more",
                     "paths are relative to <data>/root", "square root / cube root", "engine/root/x.py"):
            with self.subTest(text=text):
                code, out = self.scan(text)
                self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
