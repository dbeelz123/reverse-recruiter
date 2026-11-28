"""Fixes for the low findings of the whole-project review (2026-11-27, section 4 "Low findings (hardening)" and its
"Doc drift" list): each test reproduces the reported problem and checks the fixed behavior."""
import inspect
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import ENGINE, REPO, SampleCase, run

JOB = "9100000009"  # reviewed in round 2: fit 80, one adjustment (+6)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def edit_json(path, change):
    d = read(path)
    change(d)
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


class Base(SampleCase):
    def fails(self, script, *args, mention=None):
        code, out = run(script, *args)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        if mention:
            self.assertIn(mention, out)
        return out


# ---- the report ------------------------------------------------------------------------------------------------------

class ReportScores(Base):
    def review(self, **fields):
        edit_json(self.data / "6-system/reviews/round-02.json", lambda d: d["jobs"][JOB].update(fields))

    def built(self):
        out = self.ok("build_report.py", "--data", self.data, "--round", "2")
        return out, read(self.data / f"6-system/jobs/{JOB}.json")["review"]

    def test_half_points_round_up_and_the_tier_follows_the_printed_score(self):
        """A half point always rounds up, so the bands' edges behave alike: 64.5 prints as 65 and is a B, as 79.5
        prints as 80 and is an A. (Rounding to the even number made 64.5 a 64 and a C.)"""
        for fit, total, tier in ((64.5, 65, "B"), (79.5, 80, "A"), (49.5, 50, "C"), (64.4, 64, "C")):
            with self.subTest(fit=fit):
                self.review(fit=fit, adjustments=[], network_bonus=0, tier="D")
                _, r = self.built()
                self.assertEqual((r["total"], r["tier"]), (total, tier))

    def test_a_dealbreaker_on_a_ranked_job_is_named(self):
        self.review(dealbreakers=["clearance required"], tier="B")
        out, r = self.built()
        self.assertIn("WARNING", out)
        self.assertIn(JOB, out)
        self.assertIn("dealbreaker", out)
        self.assertNotEqual(r["tier"], "X")  # the report warns; the tier stays the reviewer's call

    def test_no_warning_without_a_conflict(self):
        out, _ = self.built()
        self.assertNotIn("dealbreaker but", out)

    def test_the_review_date_must_be_a_date(self):
        record = self.data / f"6-system/jobs/{JOB}.json"
        before = record.read_text(encoding="utf-8")
        for bad in ("../2026-11-14", "2026/11/14", "14 November", "2026-11-31", 20261114):
            with self.subTest(date=bad):
                edit_json(self.data / "6-system/reviews/round-02.json", lambda d: d.update(date=bad))
                self.fails("build_report.py", "--data", self.data, "--round", "2", mention="round-02.json")
                self.assertEqual(record.read_text(encoding="utf-8"), before)  # stopped before any record changed
                self.assertEqual([p.name for p in self.data.glob("*report.md")], [])

    def test_lead_links_quote_the_title_and_company(self):
        """The report's Find links are the same directed search the triage cards use (ingest_results.find_link)."""
        self.built()
        text = (self.data / "2-reports/2026-11-14-round-02-report.md").read_text(encoding="utf-8")
        links = [part.split(")")[0] for part in text.split("[Find](")[1:]]
        self.assertTrue(links)
        for link in links:
            self.assertIn("keywords=%22", link)
            self.assertIn("geoId=", link)


class Places(Base):
    def test_a_malformed_city_table_is_named(self):
        places = self.data / "5-criteria/places.json"
        good = read(places)
        for bad in ([], {"cities": "Springfield"}, {"cities": [{"city": "Springfield", "state": "IL", "lon": -89.6}]},
                    {"cities": [{"city": "Springfield", "state": "IL", "lat": "39.8", "lon": -89.6}]},
                    {"cities": ["Springfield, IL"]}):
            with self.subTest(bad=bad):
                places.write_text(json.dumps(bad), encoding="utf-8")
                self.fails("build_report.py", "--data", self.data, "--round", "2", mention="places.json")
        places.write_text(json.dumps(good), encoding="utf-8")
        self.ok("build_report.py", "--data", self.data, "--round", "2")


# ---- the data folder -------------------------------------------------------------------------------------------------

class DataFolder(Base):
    def test_a_mistyped_data_folder_is_refused_and_not_created(self):
        missing = self.tmp / "my-dtaa"
        for args in (("triaged.py", "reposts"), ("extract.py",), ("sweep.py", "--ids", "9100000001"),
                     ("pipeline.py", "queue"), ("privacy_scan.py", "--strict")):
            with self.subTest(script=args[0]):
                self.fails(*args, "--data", missing, mention="my-dtaa")
                self.assertFalse(missing.exists())

    def test_the_apply_queue_is_written_in_a_folder_with_no_reports_yet(self):
        empty = self.tmp / "new-data"
        empty.mkdir()
        self.ok("pipeline.py", "queue", "--data", empty)
        self.assertTrue((empty / "2-reports/apply-queue.md").exists())

    def test_a_target_that_cannot_be_replaced_stops_cleanly(self):
        from paths import DataFileError, write_json
        target = self.tmp / "ledger.json"
        target.mkdir()  # stands in for a file another program holds open: os.replace fails either way
        with self.assertRaises(DataFileError) as e:
            write_json(target, {"a": 1})
        self.assertIn("ledger.json", str(e.exception))
        self.assertFalse((self.tmp / "ledger.json.tmp").exists())


# ---- triage ----------------------------------------------------------------------------------------------------------

class WholeCompanyEntries(Base):
    """A whole-company entry ('*', written when a card was DQ'd for the blocklist) no longer skips that company's
    cards by itself: once no blocklist entry matches the company, the card is flagged for the user."""

    def setUp(self):
        super().setUp()
        edit_json(self.data / "6-system/triaged.json", lambda d: d["entries"].append({
            "company": "Quarry Analytics", "title": "*", "decision": "dq", "reason": "blocklist: analytics vendor",
            "seen": [{"search": "S1", "date": "2026-11-09", "id": "S1-900"}], "source": "test"}))
        self.cards = self.tmp / "cards.json"
        self.cards.write_text(json.dumps([{"n": 1, "company": "Quarry Analytics", "title": "Senior Product Manager",
                                           "location": "United States (Remote)", "status": []}]), encoding="utf-8")

    def check(self):
        out = self.ok("triaged.py", "check", self.cards, "--data", self.data)
        return out, read(self.cards)[0]["triaged"]

    def test_a_company_taken_off_the_blocklist_is_flagged_not_skipped(self):
        out, t = self.check()
        self.assertEqual(t["action"], "flag (blocklisted before)")
        self.assertIn("Quarry Analytics", out)
        self.assertIn("alias", out)

    def test_a_company_still_on_the_blocklist_is_shown_for_confirmation(self):
        edit_json(self.data / "5-criteria/spec.json", lambda d: d["company_blocklist"].append(
            {"value": "Quarry Analytics", "reason": "analytics vendor", "status": "confirmed"}))
        _, t = self.check()
        self.assertEqual(t["action"], "blocklist (confirm)")


class ModeSettings(Base):
    def test_ask_again_days_needs_asked(self):
        searches = self.data / "5-criteria/searches.json"
        before = searches.read_text(encoding="utf-8")
        self.fails("modes.py", "set", "--ask-again-days", "30", "--data", self.data, mention="--asked")
        self.assertEqual(searches.read_text(encoding="utf-8"), before)

    def test_asked_with_days_is_stored(self):
        self.ok("modes.py", "set", "--asked", "--ask-again-days", "30", "--data", self.data)
        self.assertIn("ask_again", read(self.data / "5-criteria/searches.json")["mode"])


# ---- images and prep PDFs --------------------------------------------------------------------------------------------

class Images(unittest.TestCase):
    T = {"processed": 1200, "decided": 300, "pdfs": 400, "ranked": 72}

    def test_no_graded_jobs_means_no_bands(self):
        import linkedin_images as li
        f, g = li.per100(self.T, {"A": 0, "B": 0, "C": 0, "D": 0})
        self.assertEqual(f["ranked"], 6)
        self.assertEqual(g, {"A": 0, "B": 0, "C": 0, "D": 0})  # was one invented job in every band

    def test_nothing_processed_gives_zeros(self):
        import linkedin_images as li
        f, g = li.per100({"processed": 0, "decided": 0, "pdfs": 3, "ranked": 2}, {"A": 1, "B": 1, "C": 0, "D": 0})
        self.assertEqual(set(f.values()), {0})
        self.assertEqual(sum(g.values()), 0)

    def test_the_split_still_adds_up(self):
        import linkedin_images as li
        f, g = li.per100(self.T, {"A": 7, "B": 22, "C": 36, "D": 5})
        self.assertEqual(sum(g.values()), f["ranked"])

    def test_a_browser_on_the_path_is_found(self):
        """The images use the same browser search as the prep PDFs (macOS apps and PATH names, not Windows only)."""
        import linkedin_images as li
        import prep_pdf
        with mock.patch.object(li, "BROWSERS", []), mock.patch.object(prep_pdf, "BROWSERS", []), \
                mock.patch("shutil.which", lambda name: "/usr/bin/chromium" if name == "chromium" else None):
            self.assertEqual(li.find_browser(), "/usr/bin/chromium")


class PrepPdf(Base):
    def test_anonymize_never_writes_over_an_input(self):
        src, rules = self.tmp / "prep.md", self.tmp / "rules.txt"
        src.write_text("Acme is hiring.\n", encoding="utf-8")
        rules.write_text("Acme ==> the Client\n", encoding="utf-8")
        for out in (src, rules):
            with self.subTest(out=out.name):
                self.fails("prep_pdf.py", "anonymize", "--rules", rules, "--in", src, "--out", out, mention="--out")
        self.assertEqual(src.read_text(encoding="utf-8"), "Acme is hiring.\n")
        self.assertEqual(rules.read_text(encoding="utf-8"), "Acme ==> the Client\n")
        self.ok("prep_pdf.py", "anonymize", "--rules", rules, "--in", src, "--out", self.tmp / "clean.md")
        self.assertEqual((self.tmp / "clean.md").read_text(encoding="utf-8"), "the Client is hiring.\n")

    def test_a_row_with_extra_cells_keeps_them(self):
        import prep_pdf
        rows = ["| Topic | Point | Proof |", "|---|---|---|", "| Scale | 40 teams | Q3 plan | read A | B first |"]
        html = prep_pdf.table(rows)
        for cell in ("Scale", "40 teams", "Q3 plan", "read A", "B first"):
            self.assertIn(cell, html)

    def test_a_failed_print_reports_the_browser_exit_code(self):
        import prep_pdf
        if os.name == "nt":
            fake = self.tmp / "browser.cmd"
            fake.write_text("@echo off\r\necho no display 1>&2\r\nexit /b 3\r\n", encoding="utf-8")
        else:
            fake = self.tmp / "browser.sh"
            fake.write_text("#!/bin/sh\necho no display >&2\nexit 3\n", encoding="utf-8")
            fake.chmod(0o755)
        with self.assertRaises(SystemExit) as e:
            prep_pdf.print_pdf(str(fake), "<p>x</p>", self.tmp / "out.pdf", timeout=1)
        self.assertIn("exit code 3", str(e.exception))
        self.assertIn("no display", str(e.exception))


# ---- staleness -------------------------------------------------------------------------------------------------------

class Gate(Base):
    def test_exit_codes_tell_check_first_from_no_such_job(self):
        code, out = run("staleness.py", "--data", self.data, "gate", "9100000002")
        self.assertEqual(code, 1, out)
        self.assertIn("CHECK FIRST", out)
        code, out = run("staleness.py", "--data", self.data, "gate", "no-such-company-zz")
        self.assertEqual(code, 2, out)
        self.assertIn("No job matches", out)
        self.assertNotIn("Traceback", out)
        self.ok("staleness.py", "--data", self.data, "confirm", "9100000002", "open")
        code, out = run("staleness.py", "--data", self.data, "gate", "9100000002")
        self.assertEqual(code, 0, out)
        self.assertIn("FRESH", out)


# ---- one definition, no dead code ------------------------------------------------------------------------------------

class Housekeeping(unittest.TestCase):
    def test_the_closed_out_statuses_are_defined_once(self):
        import interviews
        import paths
        import pipeline
        import staleness
        self.assertEqual(paths.TERMINAL, ("passed", "rejected", "withdrawn", "closed"))
        for module in (pipeline, staleness, interviews):
            self.assertIs(module.TERMINAL, paths.TERMINAL, module.__name__)
        for f in ("pipeline.py", "staleness.py", "interviews.py"):
            self.assertNotIn("TERMINAL =", (ENGINE / f).read_text(encoding="utf-8"), f)

    def test_dead_code_is_gone(self):
        import extract
        import metrics
        import pipeline
        import staleness
        self.assertFalse(hasattr(metrics, "phone_saves"))
        self.assertEqual(list(inspect.signature(staleness.gate).parameters), ["job", "today"])
        self.assertEqual(list(inspect.signature(pipeline.resolve).parameters), ["jobs", "kitmap", "key"])
        self.assertEqual(list(inspect.signature(extract.repost_check).parameters), ["P", "new_ids", "dup_files"])
        source = (ENGINE / "extract.py").read_text(encoding="utf-8")
        self.assertNotIn("import json", source)
        self.assertNotIn("json.", source.replace(".json", ""))


# ---- the hook --------------------------------------------------------------------------------------------------------

@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class Hook(SampleCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        shutil.copytree(ENGINE, self.repo / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "scripts/hooks", self.repo / "scripts/hooks")
        terms = self.tmp / "terms.txt"
        terms.write_text("Jordan Avery\n", encoding="utf-8")
        for cmd in (["init", "-q"], ["config", "reverse-recruiter.privateTerms", str(terms)],
                    ["config", "user.name", "Test"], ["config", "user.email", "test@example.com"]):
            self.git(*cmd)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)

    def hook(self, name="pre-commit"):
        return subprocess.run(["sh", f"scripts/hooks/{name}"], cwd=self.repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def stage(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text, encoding="utf-8")
        self.assertEqual(self.git("add", "-f", name).returncode, 0)

    def test_a_file_with_an_accented_name_can_be_committed(self):
        self.stage("docs/café-notes.md", "Nothing personal here.")
        result = self.hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_file_with_an_accented_name_is_still_scanned(self):
        self.stage("docs/café-notes.md", "A note from Jordan Avery.")
        result = self.hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private term", result.stdout)

    def test_a_merge_runs_the_same_check(self):
        """git runs pre-merge-commit, not pre-commit, for a merge commit: it hands over to the same check."""
        self.assertTrue((self.repo / "scripts/hooks/pre-merge-commit").is_file())
        self.stage("notes.md", "Nothing personal here.")
        self.assertEqual(self.hook("pre-merge-commit").returncode, 0)
        self.stage("notes.md", "A note from Jordan Avery.")
        result = self.hook("pre-merge-commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private term", result.stdout)


# ---- docs that drifted -----------------------------------------------------------------------------------------------

class Docs(unittest.TestCase):
    def doc(self, name):
        return __import__(name).__doc__

    def test_usage_lines_list_every_option(self):
        self.assertIn("--confirm-connections", self.doc("remove_job"))
        self.assertNotIn("rejected-jobs", self.doc("remove_job"))
        self.assertIn("--reopen", self.doc("pipeline"))
        self.assertIn("--reopen", self.doc("interviews"))
        for cmd in ("signals", "tag", "due", "progress", "setup", "set", "digest"):
            self.assertIn(f"modes.py {cmd}", self.doc("modes"), cmd)
        self.assertIn("exit 2", self.doc("staleness"))

    def test_the_data_folder_default_is_described_in_full(self):
        self.assertIn("REVERSE_RECRUITER_DATA", self.doc("triaged"))

    def test_the_image_names_match_the_files(self):
        self.assertIn("job-search-funnel-per100-round-NN.png", self.doc("linkedin_images"))
        self.assertIn("job-search-grade-bands-per100-round-NN.png", self.doc("linkedin_images"))

    def test_the_browser_is_listed_for_prep_pdfs_too(self):
        for f in ("requirements.txt", "docs/setup.md"):
            self.assertIn("prep_pdf.py", (REPO / f).read_text(encoding="utf-8"), f)

    def test_the_layout_names_the_folders_the_hook_guards(self):
        for text in (self.doc("paths"), (REPO / "docs/how-it-works.md").read_text(encoding="utf-8"),
                     (REPO / "docs/setup.md").read_text(encoding="utf-8")):
            self.assertIn("8-mentor-advice", text)
            self.assertIn("9-learning", text)


if __name__ == "__main__":
    unittest.main()
