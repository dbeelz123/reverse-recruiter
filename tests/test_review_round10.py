"""Fixes from the second whole-project code review (2026-11-25, commit 28988b8): each test reproduces the reported
problem and checks the fixed behavior."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ENGINE, REPO, SAMPLE, SampleCase, run


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class InsideNeedsFolderInsideData(SampleCase):
    """#1: the allowed folder itself must be inside the data folder (a linked inbox can't widen the boundary)."""

    def test_a_folder_outside_the_data_folder_is_never_inside(self):
        from paths import Paths
        P = Paths(str(self.data))
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        self.assertFalse(P.inside(outside / "posting.pdf", outside))
        self.assertTrue(P.inside(P.job_pdfs / "posting.pdf", P.job_pdfs))

    @unittest.skipUnless(os.name == "nt", "directory junctions are a Windows feature")
    def test_removal_never_deletes_through_a_junctioned_inbox(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (outside / "posting.pdf").write_bytes(b"%PDF-1.4 outside")
        inbox = self.data / "1-inbox/job-pdfs"
        if inbox.exists():
            shutil.rmtree(inbox)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(inbox), str(outside)], capture_output=True, text=True)
        if r.returncode:
            self.skipTest(f"can't create a junction here: {r.stdout}{r.stderr}")
        edit_json(self.data / "6-system/jobs/9100000006.json",
                  lambda j: j.update(source_files=["1-inbox/job-pdfs/posting.pdf"]))
        run("remove_job.py", "9100000006", "--reason", "test", "--data", self.data)
        self.assertTrue((outside / "posting.pdf").exists())
        os.rmdir(inbox)  # removes the junction only


class RescreenRadius(SampleCase):
    """#2: re-screening checks hybrid and on-site jobs against the current center and radius."""

    def set_radius(self, miles):
        edit_json(self.data / "5-criteria/spec.json",
                  lambda s: s["work_arrangement"]["machine_rule"].update(radius_miles=miles))

    def test_a_hybrid_job_outside_a_smaller_radius_is_flagged(self):
        self.set_radius(20)  # Decatur, IL is about 36 miles from the sample center
        out = self.ok("rescreen.py", "--data", self.data)
        self.assertRegex(out, r"OUTSIDE RADIUS[^\n]*Decatur")

    def test_no_flag_inside_the_radius(self):
        out = self.ok("rescreen.py", "--data", self.data)
        self.assertNotIn("OUTSIDE RADIUS", out)

    def test_an_unplaceable_hybrid_location_asks_for_a_check(self):
        edit_json(self.data / "6-system/jobs/9100000003.json", lambda j: j.update(location="Nowhereville, IL (Hybrid)"))
        out = self.ok("rescreen.py", "--data", self.data)
        self.assertRegex(out, r"DISTANCE UNKNOWN[^\n]*Nowhereville")


class PrivacyImages(SampleCase):
    """#3 and #15: images fail unless reviewed and listed; more home-folder path forms are caught."""

    def scan(self, folder, *extra):
        terms = self.tmp / "terms.txt"
        terms.write_text("Zanzibar Widgets\n", encoding="utf-8")
        return run("privacy_scan.py", folder, "--terms", terms, "--strict", *extra)

    def test_an_unlisted_image_is_a_hit(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(20))
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("chart.png", out)

    def test_a_listed_image_passes(self):
        folder = self.tmp / "repo"
        (folder / "docs").mkdir(parents=True)
        (folder / "docs/chart.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(20))
        (folder / ".privacy-allow").write_text("docs/chart.png | image checked by eye\n", encoding="utf-8")
        code, out = self.scan(folder)
        self.assertEqual(code, 0, out)

    def test_forward_slash_and_escaped_windows_paths_are_hits(self):
        folder = self.tmp / "repo"
        folder.mkdir()
        (folder / "a.md").write_text("see C:/Us" + "ers/alice/notes\n", encoding="utf-8")  # split: not a hit here
        bs2 = chr(92) * 2  # built at runtime so this file doesn't trip the repo's own privacy scan
        (folder / "b.json").write_text('{"p": "C:' + bs2 + 'Us' + 'ers' + bs2 + 'alice' + bs2 + 'notes"}\n',
                                       encoding="utf-8")
        code, out = self.scan(folder)
        self.assertEqual(code, 1, out)
        self.assertIn("a.md", out)
        self.assertIn("b.json", out)


@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class HookCopyFailure(SampleCase):
    """#4: a staged file that can't be copied for the scan stops the commit."""

    def test_a_failed_staged_copy_blocks_the_commit(self):
        repo = self.tmp / "repo"
        shutil.copytree(ENGINE, repo / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "scripts/hooks", repo / "scripts/hooks")
        terms = self.tmp / "terms.txt"
        terms.write_text("Jordan Avery\n", encoding="utf-8")
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
        for cmd in (["init", "-q"], ["config", "reverse-recruiter.privateTerms", str(terms)],
                    ["config", "user.name", "Test"], ["config", "user.email", "test@example.com"]):
            git(*cmd)
        (repo / "notes.md").write_text("Jordan Avery\n", encoding="utf-8")
        git("add", "notes.md")
        # A git that fails on "show" (as a read error would), passing everything else to the real git.
        fake = self.tmp / "bin"
        fake.mkdir()
        real = shutil.which("git").replace("\\", "/")
        (fake / "git").write_text(f'#!/bin/sh\nif [ "$1" = "show" ]; then exit 1; fi\nexec "{real}" "$@"\n',
                                  encoding="utf-8", newline="\n")
        os.chmod(fake / "git", 0o755)
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["sh", "-c", f'PATH="$(cygpath -u "{fake}" 2>/dev/null || echo "{fake}"):$PATH" '
                                        f'sh scripts/hooks/pre-commit'], cwd=repo, capture_output=True, text=True,
                           env=env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("could not copy", r.stdout + r.stderr)


class MatchSavedAmbiguous(SampleCase):
    """#5: two saved jobs with the same company and title never overwrite each other's link."""

    def test_same_key_jobs_leave_rows_unlinked_and_reported(self):
        for jid in ("9100000801", "9100000802"):
            (self.data / f"6-system/jobs/{jid}.json").write_text(json.dumps(
                {"job_id": jid, "company": "Zephyr Labs", "title": "Senior Product Manager, Platform",
                 "connections_1st": []}), encoding="utf-8")
        runf = self.tmp / "run.json"
        runf.write_text(json.dumps({"round": 3, "listings": [
            {"id": "S9-1", "company": "Zephyr Labs", "title": "Senior Product Manager, Platform"},
            {"id": "S9-2", "company": "Zephyr Labs", "title": "Senior Product Manager, Platform"}]}), encoding="utf-8")
        out = self.ok("triaged.py", "match-saved", runf, "--data", self.data)
        rows = read(runf)["listings"]
        self.assertFalse(any(r.get("job_id") for r in rows), rows)
        self.assertIn("ambiguous", out.lower())
        self.assertIn("9100000801", out)
        self.assertIn("9100000802", out)

    def test_a_row_already_carrying_one_of_the_ids_keeps_it(self):
        for jid in ("9100000801", "9100000802"):
            (self.data / f"6-system/jobs/{jid}.json").write_text(json.dumps(
                {"job_id": jid, "company": "Zephyr Labs", "title": "Senior Product Manager, Platform",
                 "connections_1st": []}), encoding="utf-8")
        runf = self.tmp / "run.json"
        runf.write_text(json.dumps({"round": 3, "listings": [
            {"id": "S9-1", "company": "Zephyr Labs", "title": "Senior Product Manager, Platform",
             "job_id": "9100000802"}]}), encoding="utf-8")
        self.ok("triaged.py", "match-saved", runf, "--data", self.data)
        self.assertEqual(read(runf)["listings"][0]["job_id"], "9100000802")


class NullFitTier(SampleCase):
    """#7: a null fit is allowed only with tier X (excluded) or ? (incomplete)."""

    def set_first(self, **fields):
        p = self.data / "6-system/reviews/round-02.json"
        r = read(p)
        jid = next(iter(r["jobs"]))
        r["jobs"][jid].update(fields)
        p.write_text(json.dumps(r), encoding="utf-8")
        return jid

    def test_null_fit_with_a_ranked_tier_stops(self):
        for tier in "ABCD":
            with self.subTest(tier=tier):
                jid = self.set_first(fit=None, tier=tier)
                for script, args in (("build_report.py", ("--round", "2")), ("rescreen.py", ())):
                    code, out = run(script, "--data", self.data, *args)
                    self.assertNotEqual(code, 0, f"{script} accepted null fit with tier {tier}:\n{out}")
                    self.assertNotIn("Traceback", out)
                    self.assertIn(jid, out)

    def test_null_fit_with_x_or_unknown_passes(self):
        for tier in "X?":
            with self.subTest(tier=tier):
                self.set_first(fit=None, tier=tier)
                self.ok("build_report.py", "--data", self.data, "--round", "2")


class OrphanReviews(SampleCase):
    """#8: a review whose job record is missing is named, not silently dropped."""

    def test_orphan_review_is_named(self):
        edit_json(self.data / "6-system/reviews/round-02.json", lambda r: r["jobs"].update(
            {"9100000777": {"fit": 70, "tier": "B", "adjustments": [], "network_bonus": 0, "summary": "x"}}))
        out = self.ok("build_report.py", "--data", self.data, "--round", "2")
        self.assertRegex(out, r"9100000777[^\n]*no job record|no job record[^\n]*9100000777")


class PipelineReopen(SampleCase):
    """#10: a stage after passed/rejected/withdrawn/closed needs --reopen."""
    JOB = "9100000006"

    def test_a_terminal_job_needs_reopen(self):
        self.ok("pipeline.py", "record", self.JOB, "rejected", "--date", "2026-11-12", "--data", self.data)
        code, out = run("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-13", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("--reopen", out)
        self.assertEqual(read(self.data / f"6-system/jobs/{self.JOB}.json")["pipeline"]["status"], "rejected")
        self.ok("pipeline.py", "record", self.JOB, "applied", "--date", "2026-11-13", "--reopen", "--data", self.data)
        self.assertEqual(read(self.data / f"6-system/jobs/{self.JOB}.json")["pipeline"]["status"], "applied")

    def test_outreach_and_hold_notes_need_no_reopen(self):
        self.ok("pipeline.py", "record", self.JOB, "closed", "--date", "2026-11-12", "--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "outreach", "--date", "2026-11-13", "--note", "said thanks",
                "--data", self.data)

    def test_one_terminal_status_can_follow_another(self):
        self.ok("pipeline.py", "record", self.JOB, "rejected", "--date", "2026-11-12", "--data", self.data)
        self.ok("pipeline.py", "record", self.JOB, "closed", "--date", "2026-11-13", "--data", self.data)


class RescheduleDoneRound(SampleCase):
    """#11: scheduling a round that's already debriefed needs --reopen; it never quietly resets to scheduled."""
    JOB = "9100000006"

    def test_a_debriefed_round_is_not_reset(self):
        d = ("--data", self.data)
        self.ok("interviews.py", *d, "schedule", self.JOB, "--round", "1", "--date", "2026-11-12")
        f = self.tmp / "debrief.json"
        f.write_text(json.dumps({"how": "fine"}), encoding="utf-8")
        self.ok("interviews.py", *d, "debrief", self.JOB, "--round", "1", "--file", f)
        code, out = run("interviews.py", *d, "schedule", self.JOB, "--round", "1", "--date", "2026-11-20")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("--reopen", out)
        iv = read(self.data / f"6-system/jobs/{self.JOB}.json")["interviews"][0]
        self.assertEqual(iv["status"], "done")
        self.assertEqual(iv["date"], "2026-11-12")

    def test_rescheduling_a_round_not_held_yet_still_works(self):
        d = ("--data", self.data)
        self.ok("interviews.py", *d, "schedule", self.JOB, "--round", "1", "--date", "2026-11-12")
        self.ok("interviews.py", *d, "schedule", self.JOB, "--round", "1", "--date", "2026-11-14")
        iv = read(self.data / f"6-system/jobs/{self.JOB}.json")["interviews"][0]
        self.assertEqual(iv["date"], "2026-11-14")


class GradeOverrideTotal(unittest.TestCase):
    """#12: a chosen grade split that doesn't add up to the funnel's qualified targets gets a warning."""

    def test_mismatch_warns_match_is_quiet(self):
        from linkedin_images import grades_note
        note = grades_note({"A": 3, "B": 4, "C": 2, "D": 1}, 9)
        self.assertIsNotNone(note)
        self.assertIn("10", note)
        self.assertIn("9", note)
        self.assertIsNone(grades_note({"A": 2, "B": 4, "C": 2, "D": 1}, 9))


class FutureRounds(unittest.TestCase):
    """#13: a round dated in the future never counts as recent."""

    def test_window(self):
        from modes import in_window
        today = dt.date(2026, 11, 25)
        self.assertTrue(in_window("2026-11-25", today))
        self.assertTrue(in_window("2026-11-11", today))
        self.assertFalse(in_window("2026-11-10", today))
        self.assertFalse(in_window("2026-12-02", today))
        self.assertFalse(in_window("unknown", today))


class SampleReportCurrent(SampleCase):
    """#16: the committed sample report's funnel matches what the engine builds from the sample data."""

    def funnel(self, text):
        m = re.search(r"## Search funnel.*?(?=\n### |\n## )", text, re.S)
        self.assertIsNotNone(m)
        return m.group(0)

    def test_sample_funnel_matches_a_rebuild(self):
        committed = (SAMPLE / "2-reports/2026-11-14-round-02-report.md").read_text(encoding="utf-8")
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        rebuilt = (self.data / "2-reports/2026-11-14-round-02-report.md").read_text(encoding="utf-8")
        self.assertEqual(self.funnel(committed), self.funnel(rebuilt))


class DocReferences(unittest.TestCase):
    """#17: every docs/ file named in the engine exists in the repo."""

    def test_engine_doc_references_exist(self):
        missing = set()
        for f in list(ENGINE.glob("*.py")) + list(ENGINE.glob("prompts/*.md")):
            for ref in re.findall(r"\bdocs/[\w.-]+\.md", f.read_text(encoding="utf-8")):
                if not (REPO / ref).exists():
                    missing.add(f"{f.name}: {ref}")
        self.assertFalse(missing, sorted(missing))


if __name__ == "__main__":
    unittest.main()
