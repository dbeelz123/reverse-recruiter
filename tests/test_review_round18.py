"""The four low findings first left open (whole-project review, 2026-11-27), fixed on the user's say-so: qualified
targets counted at one moment, one rule for company names, commit messages scanned, and every commit checked again
before a push (a cherry-pick, a rebase and a revert run no commit hook)."""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from helpers import ENGINE, REPO, SampleCase, run

TERMS = "Jordan Avery\nPinewick\n"
AT = chr(64)  # addresses are built at run time, so this file passes the repo's own privacy scan
TRAILER = f"Co-Authored-By: Helper Bot <noreply{AT}assistant.example.org>"
PHONE = "9100000650"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def edit_json(path, change):
    d = read(path)
    change(d)
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


# ---- qualified targets: one moment -----------------------------------------------------------------------------------

class QualifiedTargetsMoment(SampleCase):
    def P(self):
        from paths import Paths
        return Paths(str(self.data))

    def setUp(self):
        super().setUp()
        # A ranked job saved by phone triage in round 2, then the round is recorded with it on the list.
        (self.data / f"6-system/jobs/{PHONE}.json").write_text(json.dumps(
            {"job_id": PHONE, "company": "Nowhere Card Co", "title": "Senior Product Manager, Phone Save",
             "review": {"tier": "B"}}), encoding="utf-8")
        (self.data / "6-system/search-runs/phone-run-2026-11-14.json").write_text(json.dumps(
            {"round": 2, "triage_type": "phone", "result_count": None, "saved_job_ids": [PHONE], "listings": []}),
            encoding="utf-8")
        self.ok("metrics.py", "--data", self.data, "--round", "2")

    def test_the_round_keeps_its_phone_saves_on_the_list(self):
        r = [x for x in read(self.data / "6-system/metrics.json")["rounds"] if x["round"] == 2][0]
        self.assertEqual((r["phone_ranked_end"], r["rec_ranked_end"]), (1, 0))

    def test_a_removal_after_the_round_does_not_move_the_totals(self):
        import metrics
        before = metrics.totals(self.P())
        self.assertEqual(before["phone_ranked"], 1)
        # The phone save leaves the ranked list after the round was recorded; nothing is recorded again.
        edit_json(self.data / f"6-system/jobs/{PHONE}.json", lambda j: j["review"].update(tier="X"))
        after = metrics.totals(self.P())
        self.assertEqual(after["ranked"], before["ranked"])  # was one higher: the round's count less today's saves
        self.assertEqual(after["phone_ranked"], 1)
        self.assertEqual(after["ranked_when"], "at the end of round 2")

    def test_the_table_says_which_moment(self):
        out = self.ok("metrics.py", "--data", self.data)
        self.assertIn("(end of round 2)", out)
        self.assertNotIn("(now)", out)
        self.assertIn("were qualified targets at the end of round 2", out)

    def test_a_round_recorded_before_the_counts_were_kept_reads_as_before(self):
        import metrics

        def drop(m):
            for r in m["rounds"]:
                r.pop("phone_ranked_end", None)
                r.pop("rec_ranked_end", None)
        edit_json(self.data / "6-system/metrics.json", drop)
        t = metrics.totals(self.P())
        self.assertEqual((t["ranked_when"], t["phone_ranked"]), ("now", 1))
        self.assertIn("(now)", self.ok("metrics.py", "--data", self.data))


# ---- company names: one rule -----------------------------------------------------------------------------------------

class CompanyNames(SampleCase):
    def test_every_matcher_uses_the_one_rule(self):
        import paths
        import staleness
        import triaged
        for a, b in (("ŌURA", "Oura"), ("The Lattice Haul Company", "Lattice Haul"), ("Acme Holdings, Inc.", "Acme"),
                     ("Acme - GH", "Acme Technologies"), ("Brightwell & Co", "Brightwell and Co.")):
            with self.subTest(a=a, b=b):
                self.assertEqual(paths.match_key(a), paths.match_key(b))
                self.assertEqual(triaged.norm_company(a), triaged.norm_company(b))
                self.assertEqual(staleness.norm_co(a), staleness.norm_co(b))
        self.assertEqual(triaged.norm_company("Acme (through a staffing firm)"), paths.company_key("Acme"))

    def test_different_employers_stay_apart(self):
        import paths
        for a, b in (("The Home Depot", "The Trade Desk"), ("Group Nine Media", "Nine Media"), ("Acme", "Acme Robotics")):
            self.assertNotEqual(paths.match_key(a), paths.match_key(b), (a, b))

    def test_no_second_list_of_legal_words(self):
        for f in ("triaged.py", "staleness.py", "pipeline.py"):
            self.assertNotIn("inc|llc", (ENGINE / f).read_text(encoding="utf-8"), f)

    def test_a_card_matches_an_earlier_decision_across_spellings(self):
        edit_json(self.data / "6-system/triaged.json", lambda d: d["entries"].append({
            "company": "The Quarry Analytics Company", "title": "Senior Product Manager", "decision": "dq",
            "reason": "ad tech", "seen": [{"search": "S1", "date": "2026-11-09", "id": "S1-901"}], "source": "test"}))
        cards = self.tmp / "cards.json"
        cards.write_text(json.dumps([{"n": 1, "company": "Quárry Analytics", "title": "Senior Product Manager",
                                      "location": "United States (Remote)", "status": []}]), encoding="utf-8")
        self.ok("triaged.py", "check", cards, "--data", self.data)
        self.assertEqual(read(cards)[0]["triaged"]["action"], "skip")

    def test_a_job_is_found_by_a_name_typed_without_its_accent(self):
        edit_json(self.data / "6-system/jobs/9100000002.json", lambda j: j.update(company="Ōura Freight"))
        code, out = run("staleness.py", "--data", self.data, "gate", "oura")
        self.assertIn("Ōura Freight", out)
        self.assertIn(code, (0, 1), out)


# ---- commit messages and pushes --------------------------------------------------------------------------------------

class MessageScan(SampleCase):
    def scan(self, text):
        terms, msg = self.tmp / "terms.txt", self.tmp / "COMMIT_EDITMSG"
        terms.write_text(TERMS, encoding="utf-8")
        msg.write_text(text, encoding="utf-8")
        return run("privacy_scan.py", msg, "--terms", terms, "--strict", "--no-skip", "--message")

    def test_a_co_author_no_reply_address_is_allowed(self):
        self.assertEqual(self.scan(f"Fix the report\n\n{TRAILER}\n")[0], 0)

    def test_other_addresses_and_terms_are_hits(self):
        for text in ("Fix the report for Jordan Avery\n", f"Ask someone{AT}mail.somewhere.net about it\n",
                     f"Co-Authored-By: Jordan Avery <noreply{AT}assistant.example.org>\n",   # the name is still checked
                     f"Co-Authored-By: Helper Bot <helper{AT}assistant.somewhere.org>\n",    # not a no-reply address
                     f"See noreply{AT}assistant.somewhere.org\n\n{TRAILER}\n"):             # only inside the trailer
            with self.subTest(text=text):
                code, out = self.scan(text)
                self.assertEqual(code, 1, out)

    def test_the_diff_below_the_scissors_line_is_not_the_message(self):
        text = ("Fix the report\n# Please enter the commit message for your changes. Lines starting\n"
                "# with '#' will be ignored, and an empty message aborts the commit.\n#\n# On branch main\n"
                "# ------------------------ >8 ------------------------\n# Do not modify or remove the line above.\n"
                "# Everything below it will be ignored.\ndiff --git a/LICENSE b/LICENSE\n+Copyright Jordan Avery\n")
        self.assertEqual(self.scan(text)[0], 0)
        self.assertEqual(self.scan(text.replace("# ---", "---"))[0], 1)  # not the scissors line: all of it counts

    def test_without_the_flag_a_file_is_scanned_as_before(self):
        terms, f = self.tmp / "terms.txt", self.tmp / "notes.md"
        terms.write_text(TERMS, encoding="utf-8")
        f.write_text(TRAILER + "\n", encoding="utf-8")
        self.assertEqual(run("privacy_scan.py", f, "--terms", terms, "--strict")[0], 1)


@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class Hooks(SampleCase):
    """Real commits and pushes in a throwaway repository with the hooks switched on, as a clone is set up."""

    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        shutil.copytree(ENGINE, self.repo / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "scripts/hooks", self.repo / "scripts/hooks")
        for h in (self.repo / "scripts/hooks").iterdir():
            h.chmod(0o755)
        terms = self.tmp / "terms.txt"
        terms.write_text(TERMS, encoding="utf-8")
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], capture_output=True)
        for cmd in (["init", "-q", "-b", "main"], ["config", "reverse-recruiter.privateTerms", str(terms)],
                    ["config", "user.name", "Test"], ["config", "user.email", "test@example.com"],
                    ["config", "core.autocrlf", "false"], ["config", "core.hooksPath", "scripts/hooks"],
                    ["remote", "add", "origin", str(self.remote)]):
            self.assertEqual(self.git(*cmd).returncode, 0, cmd)
        self.commit("engine and hooks", add=["engine", "scripts"])
        self.assertEqual(self.push().returncode, 0)

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("PRIVATE_TERMS", "REVERSE_RECRUITER_DATA")}
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env)

    def write(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text, encoding="utf-8")
        self.assertEqual(self.git("add", "-f", name).returncode, 0)

    def commit(self, message, add=(), verify=True):
        for a in add:
            self.git("add", a)
        r = self.git("commit", "-q", "-m", message, *([] if verify else ["--no-verify"]))
        return r

    def push(self):
        return self.git("push", "-q", "origin", "main")

    def pushed(self):
        return subprocess.run(["git", "rev-parse", "main"], cwd=self.remote, capture_output=True, text=True).stdout.strip()

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    # commit-msg

    def test_a_private_term_in_the_message_blocks_the_commit(self):
        self.write("notes.md", "Nothing personal here.")
        before = self.head()
        r = self.commit("Notes after talking to Jordan Avery")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("commit message", r.stdout + r.stderr)
        self.assertEqual(self.head(), before)

    def test_a_co_author_trailer_does_not_block_the_commit(self):
        self.write("notes.md", "Nothing personal here.")
        r = self.commit(f"Add notes\n\n{TRAILER}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # pre-push

    def test_a_clean_commit_is_pushed(self):
        self.write("notes.md", "Nothing personal here.")
        self.assertEqual(self.commit(f"Add notes\n\n{TRAILER}").returncode, 0)
        r = self.push()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.pushed(), self.head())

    def test_a_commit_made_without_the_hooks_is_stopped_at_the_push(self):
        was = self.pushed()
        self.write("notes.md", "A note from Jordan Avery.")
        self.assertEqual(self.commit("Add notes", verify=False).returncode, 0)
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("private term", r.stdout + r.stderr)
        self.assertEqual(self.pushed(), was)

    def test_a_term_added_and_then_removed_is_still_stopped(self):
        was = self.pushed()
        self.write("notes.md", "A note from Jordan Avery.")
        self.commit("Add notes", verify=False)
        self.write("notes.md", "Nothing personal here.")
        self.assertEqual(self.commit("Tidy the notes").returncode, 0)  # this commit alone is clean
        self.assertNotEqual(self.push().returncode, 0)                 # the push publishes the one before it too
        self.assertEqual(self.pushed(), was)

    def test_a_message_written_without_the_hooks_is_stopped_at_the_push(self):
        was = self.pushed()
        self.write("notes.md", "Nothing personal here.")
        self.commit("Notes after talking to Jordan Avery", verify=False)
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("message", r.stdout + r.stderr)
        self.assertEqual(self.pushed(), was)

    def test_a_cherry_pick_is_stopped_at_the_push(self):
        """git runs no commit hook for a cherry-pick: the commit is made, and the push is where it is caught."""
        was = self.pushed()
        self.git("checkout", "-q", "-b", "side")
        self.write("notes.md", "A note from Jordan Avery.")
        self.commit("Add notes", verify=False)
        picked = self.head()
        self.git("checkout", "-q", "main")
        r = self.git("cherry-pick", picked)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.repo / "notes.md").exists())
        self.assertNotEqual(self.push().returncode, 0)
        self.assertEqual(self.pushed(), was)

    def test_personal_paths_and_documents_are_stopped_at_the_push(self):
        was = self.pushed()
        for name in ("my-data/x.txt", "personal/6-system/jobs/1.json", "resume.pdf"):
            with self.subTest(name=name):
                self.write(name, "{}")
                self.commit("Add a file", verify=False)
                self.assertNotEqual(self.push().returncode, 0)
                self.assertEqual(self.pushed(), was)
                self.git("reset", "-q", "--hard", "origin/main")

    def test_a_merge_runs_the_commit_check(self):
        self.git("checkout", "-q", "-b", "side")
        self.write("side.md", "A note from Jordan Avery.")
        self.commit("Add side notes", verify=False)
        self.git("checkout", "-q", "main")
        self.write("main.md", "Nothing personal here.")
        self.assertEqual(self.commit("Add main notes").returncode, 0)
        before = self.head()
        r = self.git("merge", "--no-ff", "-m", "Merge side", "side")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head(), before)

    def test_the_hooks_share_one_set_of_path_rules(self):
        for name in ("pre-commit", "pre-push"):
            text = (REPO / "scripts/hooks" / name).read_text(encoding="utf-8")
            self.assertIn("personal_paths", text)
            self.assertIn("document_paths", text)
            self.assertNotIn("1-inbox", text)  # the rules themselves are in lib.sh only


class HookDocs(unittest.TestCase):
    def test_setup_and_readme_name_every_hook(self):
        for f in ("docs/setup.md", "README.md"):
            text = (REPO / f).read_text(encoding="utf-8")
            for hook in ("commit-msg", "pre-push"):
                self.assertIn(hook, text, f)


if __name__ == "__main__":
    unittest.main()
