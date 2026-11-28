"""Fixes from the independent review of commits 2caae34..3c4857a (2026-11-28, four reviewers): the high and medium
findings, plus an empty --data. Each test reproduces the reported problem and checks the fixed behavior."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import ENGINE, REPO, SampleCase, run

AT = chr(64)  # addresses are built at run time, so this file passes the repo's own privacy scan
TERMS = "Jordan Avery\nQuillfeather\n"
BOT = f"Co-Authored-By: Helper Bot <noreply{AT}assistant.example.org>"
SCISSORS = ("# ------------------------ >8 ------------------------\n# Do not modify or remove the line above.\n"
            "# Everything below it will be ignored.\n")
TEMPLATE = ("# Please enter the commit message for your changes. Lines starting\n"
            "# with '#' will be ignored, and an empty message aborts the commit.\n#\n")
TODAY = dt.date.today()
JOB = "9100000002"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def edit_json(path, change):
    d = read(path)
    change(d)
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


# ---- commit messages -------------------------------------------------------------------------------------------------

class MessageScan(SampleCase):
    def scan(self, text, *flags):
        terms, msg = self.tmp / "terms.txt", self.tmp / "COMMIT_EDITMSG"
        terms.write_text(TERMS, encoding="utf-8")
        msg.write_bytes(text.encode("utf-8"))
        return run("privacy_scan.py", msg, "--terms", terms, "--strict", "--no-skip", "--message", *flags)

    def test_a_term_inside_a_no_reply_address_is_a_hit(self):
        """High: the address was removed before the scan, so an account name in it was never checked."""
        for trailer in (f"Co-Authored-By: JA <1234+jordan-avery{AT}users.noreply.github.com>",
                        f"Signed-off-by: Pat <noreply{AT}quillfeather.com>",
                        f"Co-Authored-By: P <jordan.avery{AT}users.noreply.example.org>"):
            for flags in ((), ("--final",)):
                with self.subTest(trailer=trailer, flags=flags):
                    code, out = self.scan(f"Fix the report\n\n{trailer}\n", *flags)
                    self.assertEqual(code, 1, out)
                    self.assertIn("private term", out)

    def test_a_no_reply_address_without_a_term_still_passes(self):
        for trailer in (BOT, f"Co-Authored-By: Octo <1234+octo-helper{AT}users.noreply.github.com>",
                        f"Co-authored-by: Bot <no-reply{AT}assistant.example.org>"):
            for flags in ((), ("--final",)):
                with self.subTest(trailer=trailer, flags=flags):
                    self.assertEqual(self.scan(f"Fix the report\n\n{trailer}\r\n", *flags)[0], 0)

    def test_noreply_must_be_the_mailbox_or_a_domain_label(self):
        for trailer in (f"Signed-off-by: Pat <pat.noreply{AT}realcorp.io>",        # only part of the mailbox name
                        f"Co-Authored-By: Pat <pat{AT}noreplymail.io>",            # only part of a domain label
                        f"Co-Authored-By: Pat <pat{AT}realcorp.io>"):
            with self.subTest(trailer=trailer):
                code, out = self.scan(f"Fix the report\n\n{trailer}\n")
                self.assertEqual(code, 1, out)
                self.assertIn("email address", out)

    def test_a_typed_scissors_line_hides_nothing(self):
        """Only git's own two-line marker is the scissors; and a finished message is never cut at all."""
        typed = "subject\n\n# ------------------------ >8 ------------------------\nJordan Avery reviewed this\n"
        self.assertEqual(self.scan(typed)[0], 1)
        real = f"subject\n\n{SCISSORS}Jordan Avery reviewed this\n"
        self.assertEqual(self.scan(real)[0], 0)             # being written: git removes all of this
        self.assertEqual(self.scan(real, "--final")[0], 1)  # read from a commit: it was published

    def test_gits_own_comment_lines_are_not_the_message(self):
        """An editor-made message carries git's instructions block, which names the branch and, for someone else's
        commit, its author. git removes it; the hook used to block on it."""
        block = TEMPLATE + f"# Author:    Dev One <dev{AT}corp.io>\n#\n# On branch quillfeather-notes\n# Changes to be committed:\n#\tmodified:   notes.md\n#\n"
        self.assertEqual(self.scan("Tidy the notes\n\n" + block)[0], 0)
        self.assertEqual(self.scan("Tidy the notes\n\n" + block + SCISSORS + "diff --git a/x b/x\n+Jordan Avery\n")[0], 0)
        self.assertEqual(self.scan("Tidy the notes for Jordan Avery\n\n" + block)[0], 1)   # the message itself counts
        self.assertEqual(self.scan("Tidy the notes\n\n" + block, "--final")[0], 1)          # published: all of it
        # The block only counts at the end, as git writes it: text after it means a person typed it.
        self.assertEqual(self.scan("Tidy\n\n" + TEMPLATE + "Jordan Avery reviewed this\n")[0], 1)

    def test_final_goes_with_message(self):
        terms, f = self.tmp / "terms.txt", self.tmp / "notes.md"
        terms.write_text(TERMS, encoding="utf-8")
        f.write_text("nothing personal", encoding="utf-8")
        code, out = run("privacy_scan.py", f, "--terms", terms, "--final")
        self.assertNotEqual(code, 0)
        self.assertIn("--message", out)


@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class Hooks(SampleCase):
    """Real commits, tags and pushes in a throwaway repository with the hooks switched on."""

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
                    ["config", "user.name", "Test Owner"], ["config", "user.email", f"owner{AT}example.com"],
                    ["config", "core.autocrlf", "false"], ["config", "commit.gpgsign", "false"],
                    ["config", "tag.gpgsign", "false"], ["config", "core.hooksPath", "scripts/hooks"],
                    ["remote", "add", "origin", str(self.remote)]):
            self.assertEqual(self.git(*cmd).returncode, 0, cmd)
        self.git("add", "engine", "scripts")
        self.assertEqual(self.git("commit", "-q", "-m", "engine and hooks").returncode, 0)
        self.assertEqual(self.push().returncode, 0)

    def git(self, *args, env=None):
        base = {k: v for k, v in os.environ.items() if k not in ("PRIVATE_TERMS", "REVERSE_RECRUITER_DATA")}
        base.update(env or {})
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=base)

    def write(self, name, text="Nothing personal here."):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text, encoding="utf-8")
        self.assertEqual(self.git("add", "-f", "--", name).returncode, 0)

    def push(self, *refs):
        return self.git("push", "-q", "origin", *(refs or ("main",)))

    def remote_refs(self):
        return subprocess.run(["git", "for-each-ref", "--format=%(refname)"], cwd=self.remote, capture_output=True,
                              text=True).stdout.split()

    def blocked(self, result, mention):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(mention, result.stdout + result.stderr)

    def test_a_term_in_a_co_author_address_blocks_the_commit_and_the_push(self):
        self.write("notes.md")
        trailer = f"Co-Authored-By: JA <1234+jordan-avery{AT}users.noreply.github.com>"
        self.blocked(self.git("commit", "-q", "-m", f"Add notes\n\n{trailer}"), "private term")
        self.assertEqual(self.git("commit", "-q", "--no-verify", "-m", f"Add notes\n\n{trailer}").returncode, 0)
        self.blocked(self.push(), "private term")
        self.assertEqual(self.remote_refs(), ["refs/heads/main"])

    def test_a_typed_scissors_line_does_not_get_a_message_through(self):
        self.write("notes.md")
        msg = "Add notes\n\n# ------------------------ >8 ------------------------\nJordan Avery reviewed this\n"
        self.blocked(self.git("commit", "-q", "-m", msg), "private term")
        real = f"Add notes\n\n{SCISSORS}Jordan Avery reviewed this\n"
        made = self.git("commit", "-q", "-m", real)   # git's own marker pasted whole: commit-msg can't tell ...
        if made.returncode == 0:
            self.assertIn("Jordan Avery", self.git("log", "-1", "--format=%B").stdout)
            self.blocked(self.push(), "private term")  # ... so the push check reads the finished message in full

    def test_an_editor_made_message_is_not_blocked_by_gits_comment_lines(self):
        """Amending in an editor on a branch named with a term, as another author: git's template names both."""
        self.git("checkout", "-q", "-b", "quillfeather-notes")
        self.write("notes.md")
        r = self.git("commit", "-q", "-m", "Add notes", "--author", f"Dev One <dev{AT}corp.example.org>")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.git("commit", "-q", "--amend", env={"GIT_EDITOR": "true"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_tag_message_is_checked(self):
        self.git("tag", "-a", "v1", "-m", "Release notes for Jordan Avery")
        self.blocked(self.push("v1"), "tag")
        self.git("tag", "-a", "v2", "-m", "Release notes")
        self.assertEqual(self.push("v2").returncode, 0)
        self.assertEqual(sorted(self.remote_refs()), ["refs/heads/main", "refs/tags/v2"])

    def test_a_ref_name_is_checked(self):
        self.blocked(self.push("HEAD:refs/heads/jordan-avery-fix"), "name of refs/heads/jordan-avery-fix")
        self.assertEqual(self.push("HEAD:refs/heads/a-fix").returncode, 0)

    def test_another_persons_name_as_author_is_checked_but_the_owners_is_not(self):
        self.write("notes.md")
        r = self.git("commit", "-q", "--no-verify", "-m", "Add notes", "--author", f"Jordan Avery <ja{AT}corp.example.org>")
        self.assertEqual(r.returncode, 0)
        self.blocked(self.push(), "author or committer")
        self.git("reset", "-q", "--hard", "origin/main")
        self.write("notes.md")
        r = self.git("commit", "-q", "-m", "Add notes", "--author", f"Dev One <dev{AT}corp.example.org>")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.push()  # someone else, no term in name or address: an address alone is not a hit here
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_tag_on_a_blob_is_refused(self):
        blob = self.git("hash-object", "-w", "engine/paths.py").stdout.strip()
        self.git("tag", "blobtag", blob)
        self.blocked(self.push("blobtag"), "not a commit")

    def test_a_push_by_address_checks_only_what_is_new(self):
        """A push that names an address, not a remote, has no remote-tracking branches of its own to go by; what
        any remote already holds is still published history, not rescanned."""
        self.git("fetch", "-q", "origin")
        self.write("notes.md")
        self.assertEqual(self.git("commit", "-q", "-m", "Add notes").returncode, 0)
        r = self.git("push", str(self.remote), "HEAD:refs/heads/by-address")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 commit(s) checked", r.stdout + r.stderr)

    def test_a_folder_named_with_a_leading_dash_can_be_committed_and_pushed(self):
        self.write("-notes/in.txt")
        r = self.git("commit", "-q", "-m", "Add notes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.push()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_hooks_find_python_by_either_name(self):
        text = (REPO / "scripts/hooks/lib.sh").read_text(encoding="utf-8")
        self.assertIn("for candidate in python python3", text)
        for name in ("pre-commit", "commit-msg", "pre-push"):
            hook = (REPO / "scripts/hooks" / name).read_text(encoding="utf-8")
            self.assertIn('"$py" engine/privacy_scan.py', hook, name)
            self.assertNotIn(" python engine/", hook, name)


# ---- qualified targets -----------------------------------------------------------------------------------------------

PHONE = "9100000650"


class QualifiedTargets(SampleCase):
    def P(self):
        from paths import Paths
        return Paths(str(self.data))

    def setUp(self):
        super().setUp()
        (self.data / f"6-system/jobs/{PHONE}.json").write_text(json.dumps(
            {"job_id": PHONE, "company": "Nowhere Card Co", "title": "Senior Product Manager, Phone Save",
             "review": {"tier": "B"}}), encoding="utf-8")
        (self.data / "6-system/search-runs/phone-run-2026-11-14.json").write_text(json.dumps(
            {"round": 2, "triage_type": "phone", "result_count": None, "saved_job_ids": [PHONE], "listings": []}),
            encoding="utf-8")
        self.ok("metrics.py", "--data", self.data, "--round", "2")

    def test_the_funnel_image_names_the_same_moment_as_the_table(self):
        import metrics
        svg = self.tmp / "funnel.svg"
        metrics.funnel_svg(self.P(), svg)
        text = svg.read_text(encoding="utf-8")
        self.assertIn("qualified targets at the end of round 2", text)
        self.assertNotIn("qualified targets now", text)

    def test_a_run_file_added_after_the_round_sets_the_stored_count_aside(self):
        """A second phone run names a ranked job already in the round. The stored count was taken without it, so
        the table no longer claims a number 'at the end of round 2' that was never counted that way."""
        import metrics
        before = metrics.totals(self.P())
        self.assertEqual((before["ranked_when"], before["phone_ranked"]), ("at the end of round 2", 1))
        (self.data / "6-system/search-runs/phone-run-late.json").write_text(json.dumps(
            {"round": 2, "triage_type": "phone", "result_count": None,
             "saved_job_ids": ["ext-northwind-freight-sr-pm"], "listings": []}), encoding="utf-8")
        after = metrics.totals(self.P())
        self.assertEqual(after["phone_pdfs"], 2)
        self.assertEqual(after["ranked_when"], "now")
        self.assertEqual(after["phone_ranked"], 2)               # both are on the ranked list today
        self.assertEqual(after["ranked"], before["ranked"] - 1)  # the known funnel loses the second one too
        self.assertIn("(now)", self.ok("metrics.py", "--data", self.data))
        self.ok("metrics.py", "--data", self.data, "--round", "2")  # recording again makes it one moment
        again = metrics.totals(self.P())
        self.assertEqual((again["ranked_when"], again["phone_ranked"]), ("at the end of round 2", 2))

    def test_a_stop_between_the_two_writes_leaves_no_stale_count(self):
        import metrics
        edit_json(self.data / f"6-system/jobs/{PHONE}.json", lambda j: j["review"].update(tier="X"))
        real = metrics.funnel_from_runs
        calls = []

        def stop(P):
            calls.append(1)
            raise SystemExit("stopped between the writes")
        with mock.patch.object(metrics, "funnel_from_runs", stop):
            with self.assertRaises(SystemExit):
                metrics.record(self.P(), 2)
        self.assertEqual(calls, [1])
        self.assertIs(metrics.funnel_from_runs, real)
        r = [x for x in read(self.data / "6-system/metrics.json")["rounds"] if x["round"] == 2][0]
        self.assertNotIn("phone_ranked_end", r)  # the earlier recording's count went with the old ranked_end
        t = metrics.totals(self.P())
        self.assertEqual((t["ranked_when"], t["phone_ranked"]), ("now", 0))
        self.assertEqual(t["ranked"], r["ranked_end"])


# ---- company names ---------------------------------------------------------------------------------------------------

class CompanyMatching(SampleCase):
    TITLE = "Senior Product Manager"

    def jobs(self, *companies):
        return {str(i): {"job_id": str(i), "company": c, "title": self.TITLE} for i, c in enumerate(companies)}

    def test_the_tracker_matches_whole_words_only(self):
        import staleness
        for line, project in (("ION Group", "Union Pacific"), ("Via Technologies", "Aviatrix"),
                              ("The Group Company", "Groupon"), ("Co", "Costco"), ("Monarch", "Arc Technologies")):
            with self.subTest(line=line, project=project):
                self.assertIsNone(staleness.match_job(self.jobs(project), self.TITLE, line))

    def test_the_tracker_still_matches_the_same_employer(self):
        import staleness
        for line, project in (("ION Group", "ION Group"), ("Acme", "Acme Robotics"), ("Acme Robotics", "Acme"),
                              ("The Lattice Haul Company", "Lattice Haul"), ("Ōura", "Oura Health"),
                              ("Acme - GH", "Acme Technologies")):
            with self.subTest(line=line, project=project):
                self.assertIsNotNone(staleness.match_job(self.jobs(project), self.TITLE, line))
        both = self.jobs("Union Pacific", "ION Group")
        self.assertEqual(staleness.match_job(both, self.TITLE, "ION Group")["company"], "ION Group")

    def test_a_paste_no_longer_closes_another_companys_job(self):
        edit_json(self.data / "6-system/jobs/9100000006.json",
                  lambda j: j.update(company="Union Pacific", title=self.TITLE))
        paste = self.tmp / f"tracked-{TODAY.isoformat()}.txt"
        paste.write_text(f"Saved · 1\n{self.TITLE}\nION Group · United States (Remote)\n"
                         f"No longer accepting applications\n", encoding="utf-8")
        out = self.ok("staleness.py", "--data", self.data, "tracker", paste)
        self.assertIn("marked 0 open, 0 closed", out)
        self.assertIn("not in the project: ION Group", out)
        self.assertNotEqual((read(self.data / "6-system/jobs/9100000006.json").get("open_check") or {}).get("result"),
                            "closed")

    def test_a_typed_word_finds_a_name_with_an_ampersand(self):
        from pipeline import resolve
        jobs = {"1": {"company": "AT&T", "title": "PM"}, "2": {"company": "Ōura Freight", "title": "PM"},
                "3": {"company": "Procter & Gamble", "title": "PM"}}
        for typed, jid in (("att", "1"), ("at&t", "1"), ("atandt", "1"), ("oura", "2"), ("procter", "3"),
                           ("procterandgamble", "3"), ("proctergamble", "3")):
            with self.subTest(typed=typed):
                self.assertEqual(resolve(jobs, {}, typed), jid)


# ---- the location rule and rule values -------------------------------------------------------------------------------

class LocationRule(SampleCase):
    def rule(self, change):
        edit_json(self.data / "5-criteria/spec.json", lambda d: change(d["work_arrangement"]["machine_rule"]))

    def test_a_malformed_center_is_named_before_anything_is_written(self):
        record = self.data / "6-system/jobs/9100000001.json"
        edit_json(record, lambda j: j.pop("review", None))
        before = record.read_text(encoding="utf-8")
        good = read(self.data / "5-criteria/spec.json")
        for label, change in (("text latitude", lambda r: r["hybrid_onsite_center"].update(lat="39.78")),
                              ("no longitude", lambda r: r["hybrid_onsite_center"].pop("lon")),
                              ("latitude out of range", lambda r: r["hybrid_onsite_center"].update(lat=3978)),
                              ("center as text", lambda r: r.update(hybrid_onsite_center="Springfield, IL")),
                              ("name as a number", lambda r: r["hybrid_onsite_center"].update(name=5))):
            with self.subTest(case=label):
                self.rule(change)
                for args in (("rescreen.py",), ("build_report.py", "--round", "2"), ("searches.py",)):
                    code, out = run(*args, "--data", self.data)
                    self.assertNotEqual(code, 0, out)
                    self.assertNotIn("Traceback", out)
                    self.assertIn("hybrid_onsite_center", out)
                    self.assertIn("spec.json", out)
                self.assertEqual(record.read_text(encoding="utf-8"), before)
                (self.data / "5-criteria/spec.json").write_text(json.dumps(good), encoding="utf-8")

    def test_a_rule_section_of_the_wrong_shape_is_named(self):
        good = read(self.data / "5-criteria/spec.json")
        for change in (lambda d: d.update(work_arrangement=["remote"]),
                       lambda d: d["work_arrangement"].update(machine_rule="50 miles")):
            edit_json(self.data / "5-criteria/spec.json", change)
            for args in (("rescreen.py",), ("build_report.py", "--round", "2"), ("searches.py",)):
                code, out = run(*args, "--data", self.data)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("work_arrangement", out)
            (self.data / "5-criteria/spec.json").write_text(json.dumps(good), encoding="utf-8")

    def test_no_center_means_remote_only(self):
        from paths import location_rule
        self.assertEqual(location_rule({}, "spec.json"), {"radius": 50, "center": None, "name": "", "geo": None})
        self.rule(lambda r: r.pop("hybrid_onsite_center"))
        self.ok("rescreen.py", "--data", self.data)
        self.ok("build_report.py", "--round", "2", "--data", self.data)

    def test_a_confirmed_rule_needs_its_text(self):
        good = read(self.data / "5-criteria/spec.json")
        for change in (lambda d: d["negatives"][0].pop("value"), lambda d: d["negatives"][0].update(value=5),
                       lambda d: d["dealbreakers"][0].update(value="  ")):
            edit_json(self.data / "5-criteria/spec.json", change)
            code, out = run("rescreen.py", "--data", self.data)
            self.assertNotEqual(code, 0, out)
            self.assertNotIn("Traceback", out)
            self.assertIn("'value'", out)
            (self.data / "5-criteria/spec.json").write_text(json.dumps(good), encoding="utf-8")

    def test_the_status_message_says_how_to_allow_another_status(self):
        edit_json(self.data / "5-criteria/spec.json", lambda d: d["negatives"][0].update(status="case by case"))
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertIn("status_legend", out)


class EmptyDataFlag(SampleCase):
    def test_an_empty_data_value_is_refused_not_replaced_by_the_setting(self):
        """`--data "$COPY"` with the variable unset used to fall back to the environment folder: a command meant
        for a copy would then run on the real data."""
        from paths import DataFileError, Paths
        with mock.patch.dict(os.environ, {"REVERSE_RECRUITER_DATA": str(self.data)}):
            for empty in ("", "   "):
                with self.assertRaises(DataFileError) as e:
                    Paths(empty)
                self.assertIn("--data", str(e.exception))
            self.assertEqual(Paths(None).data, self.data)
            self.assertEqual(Paths().data, self.data)
        env = {k: v for k, v in os.environ.items() if k != "PRIVATE_TERMS"}
        env.update(REVERSE_RECRUITER_DATA=str(self.data), PYTHONIOENCODING="utf-8")
        report = self.data / "2-reports/apply-queue.md"
        before = report.read_text(encoding="utf-8") if report.exists() else None
        r = subprocess.run([sys.executable, "-B", str(ENGINE / "pipeline.py"), "queue", "--data", ""], cwd=REPO,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(report.read_text(encoding="utf-8") if report.exists() else None, before)


# ---- interviews ------------------------------------------------------------------------------------------------------

class ThankYousAcrossSittings(SampleCase):
    HELD = (TODAY - dt.timedelta(days=6)).isoformat()
    AGAIN = (TODAY - dt.timedelta(days=1)).isoformat()

    def iv(self, cmd, *args):
        return self.ok("interviews.py", "--data", self.data, cmd, JOB, *args)

    def debrief(self, data, date):
        f = self.tmp / "debrief.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        return self.iv("debrief", "--round", "1", "--file", f, "--date", date)

    def round1(self):
        return [x for x in read(self.data / f"6-system/jobs/{JOB}.json")["interviews"] if str(x["round"]) == "1"][0]

    def due(self):
        return self.ok("interviews.py", "--data", self.data, "due")

    def setUp(self):
        super().setUp()
        self.iv("schedule", "--round", "1", "--date", self.HELD)
        self.debrief({"asked": ["Why this role?"], "thank_you_to": ["Dana"]}, self.HELD)
        self.assertIn("thank-you to Dana", self.due())
        self.iv("schedule", "--round", "1", "--date", self.AGAIN, "--reopen")

    def test_an_unsent_thank_you_stays_owed_after_the_round_is_reopened(self):
        self.assertIn("thank-you to Dana", self.due())

    def test_sent_marks_the_earlier_sitting_while_the_new_one_is_not_debriefed(self):
        out = self.iv("sent", "--round", "1", "--date", self.HELD)
        self.assertIn(self.HELD, out)
        r = self.round1()
        self.assertEqual(r["earlier"][0]["thank_you"]["sent"], self.HELD)
        self.assertNotIn("thank_you", r)
        self.assertNotIn("thank-you to Dana", self.due())
        # The new sitting's thank-you is then owed in its own right, not inherited as sent.
        self.debrief({"asked": ["A failure?"], "thank_you_to": ["Priya"]}, self.AGAIN)
        self.assertIsNone(self.round1()["thank_you"]["sent"])
        self.assertIn("thank-you to Priya", self.due())
        self.iv("sent", "--round", "1")
        self.assertEqual(self.round1()["thank_you"]["sent"], TODAY.isoformat())
        self.assertNotIn("thank-you to Priya", self.due())

    def test_both_can_be_owed_at_once(self):
        self.debrief({"asked": ["A failure?"], "thank_you_to": ["Priya"]}, self.AGAIN)
        due = self.due()
        self.assertIn("thank-you to Dana", due)
        self.assertIn("thank-you to Priya", due)

    def test_a_removed_jobs_debriefs_stay_in_lessons(self):
        self.debrief({"asked": ["A failure?"], "lessons": ["Slow down"]}, self.AGAIN)
        before = self.ok("interviews.py", "--data", self.data, "lessons")
        self.assertIn("Slow down", before)
        self.ok("remove_job.py", JOB, "--reason", "rejected after round 1", "--confirm-connections", "--data", self.data)
        tomb = [t for t in read(self.data / "6-system/removed.json") if t["job_id"] == JOB][0]
        self.assertEqual(len(tomb["interviews"]), 1)
        self.assertEqual(len(tomb["interviews"][0]["earlier"]), 1)
        after = self.ok("interviews.py", "--data", self.data, "lessons")
        self.assertIn("Slow down", after)
        self.assertIn("why this role?", after)
        self.assertEqual(before.splitlines()[0], after.splitlines()[0])  # the same number of debriefed rounds


if __name__ == "__main__":
    unittest.main()
