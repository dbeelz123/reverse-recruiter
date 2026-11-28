"""Fixes from the review of commit 9871fd7 (2026-11-28), done in batches: areas 1-3 (data integrity, ingest,
screening and removal), then areas 4-6 (scoring, funnel and public numbers, applications and interviews). Each test
reproduces the reported problem and checks the fixed behavior."""
import json
import sys
import unittest
from unittest import mock

from helpers import SampleCase, run

JOB = "9100000006"  # Lumen Cart - Senior Product Manager, Checkout and Delivery Options


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class MatchSavedKeepsAnotherJobsId(SampleCase):
    """#1: a run row that already carries a different job's ID isn't relinked to a saved job of the same company
    and title (a repost under a new ID, say); it is left as it is and listed."""

    def setUp(self):
        super().setUp()
        self.rec = read(self.data / f"6-system/jobs/{JOB}.json")
        self.run_file = self.data / "6-system/search-runs/s9-run-2026-11-20.json"

    def row(self, **extra):
        return dict({"id": "S9-001", "company": self.rec["company"], "title": self.rec["title"]}, **extra)

    def match(self, *rows):
        self.run_file.write_text(json.dumps({"search": "S9 test", "date": "2026-11-20", "round": 2,
                                             "listings": list(rows)}), encoding="utf-8")
        code, out = run("triaged.py", "match-saved", self.run_file, "--data", self.data)
        self.assertEqual(code, 0, out)
        return read(self.run_file)["listings"], out

    def test_a_different_id_is_left_alone_and_reported(self):
        for extra in ({"decision": "dq", "reason": "travel 50%"}, {}, {"decision": "keep", "status": "saved"}):
            with self.subTest(extra=extra):
                before = self.row(job_id="9100000900", **extra)
                rows, out = self.match(dict(before))
                self.assertEqual(rows[0], before)
                self.assertIn("S9-001", out)
                self.assertIn("9100000900", out)
                self.assertIn(JOB, out)
                self.assertIn("0 undecided rows now saved", out)
                self.assertIn("0 saved jobs DQ'd in this run", out)

    def test_a_row_without_an_id_is_still_linked(self):
        rows, out = self.match(self.row())
        self.assertEqual((rows[0]["job_id"], rows[0]["decision"]), (JOB, "keep"))
        self.assertIn("1 undecided rows now saved", out)

    def test_a_row_with_the_same_id_is_unchanged(self):
        before = self.row(job_id=JOB, decision="keep", reason="saved off-batch", status="saved (off-batch)")
        rows, out = self.match(dict(before))
        self.assertEqual(rows[0], before)
        self.assertNotIn("another job", out)


class ExtractLedgerAfterTheRepostCheck(SampleCase):
    """#2: a stop during the repost check leaves the PDFs unmarked, so the next run checks them again."""

    def test_an_interrupted_repost_check_is_run_again(self):
        import extract
        pdfs = self.data / "1-inbox/job-pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        (pdfs / "new.pdf").write_bytes(b"%PDF-1.4")
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": "9100000777", "removed": "2026-11-12", "reason": "hybrid too far"}])
        ledger_p = self.data / "6-system/ledger.json"
        ledger = ledger_p.read_text(encoding="utf-8")
        fake = ("9100000777", None, ("PM", "Acme"), ["Acme", "PM", "About the job", "text"])
        real_check = extract.repost_check

        def interrupted(*a, **k):
            raise KeyboardInterrupt
        with mock.patch.object(extract, "page_lines", lambda pdf: fake), \
                mock.patch.object(sys, "argv", ["extract.py", "--data", str(self.data)]):
            with mock.patch.object(extract, "repost_check", interrupted), self.assertRaises(KeyboardInterrupt):
                extract.main()
            self.assertEqual(ledger_p.read_text(encoding="utf-8"), ledger)
            with mock.patch.object(extract, "repost_check", real_check):
                extract.main()
        self.assertIn("new.pdf", ledger_p.read_text(encoding="utf-8"))
        rec = read(self.data / "6-system/jobs/9100000777.json")
        self.assertEqual(rec["previously_removed"], {"removed": "2026-11-12", "reason": "hybrid too far"})


class RescreenPatternTypes(SampleCase):
    """#3: a pattern in spec.json that isn't text stops with the file and the rule named."""

    def test_a_number_as_a_pattern(self):
        for field in ("title_regex", "rescreen_regex"):
            for bad in (7, ["a"], True):
                with self.subTest(field=field, bad=bad):
                    spec = self.data / "5-criteria/spec.json"
                    good = spec.read_text(encoding="utf-8")
                    edit_json(spec, lambda s: s["negatives"].append(
                        {"value": "Odd rule", field: bad, "status": "confirmed"}))
                    code, out = run("rescreen.py", "--data", self.data)
                    spec.write_text(good, encoding="utf-8")
                    self.assertNotEqual(code, 0, out)
                    self.assertNotIn("Traceback", out)
                    self.assertIn("spec.json", out)
                    self.assertIn("Odd rule", out)
                    self.assertIn(field, out)


# ---- second batch: areas 4-6 ---------------------------------------------------------------------------------------

APPLIED = "9100000001"  # Harborline Logistics: tier A, applied
KIT = "3-applications/northwind-freight-sr-pm-marketplace"


class PrimerQuestionCount(SampleCase):
    """#1 (areas 4-6, again in areas 9-10): a primer with fewer questions than the primer rules ask for (15) is
    incomplete. The check used to pass from 10 up."""

    def check(self, n):
        prep = self.data / KIT / "interview-prep.md"
        rows = "\n".join(f"| {i} | Question {i}? | story |" for i in range(1, n + 1))
        prep.write_text(f"# Prep\n\n## Likely interview questions\n\n| # | Question | Use |\n|---|---|---|\n{rows}\n",
                        encoding="utf-8")
        return run("primer.py", "--data", self.data, "check", "ext-northwind-freight-sr-pm")

    def test_fourteen_is_incomplete(self):
        for n, short in ((14, "1 short"), (12, "3 short"), (9, "6 short")):
            with self.subTest(n=n):
                code, out = self.check(n)
                self.assertNotEqual(code, 0, out)
                self.assertIn("PRIMER INCOMPLETE", out)
                self.assertIn("15 or more", out)
                self.assertIn(short, out)

    def test_fifteen_is_complete(self):
        code, out = self.check(15)
        self.assertEqual(code, 0, out)
        self.assertIn("PRIMER COMPLETE", out)
        self.assertNotIn("short", out)

    def test_the_sample_kit_meets_the_rule(self):
        out = self.ok("primer.py", "--data", self.data, "check", "ext-northwind-freight-sr-pm")
        self.assertIn("likely questions: 15", out)


class FunnelCountsAJobOnce(SampleCase):
    """#2 (areas 4-6): a job removed after an application and saved again is one job in the outcome funnel, at
    the furthest stage either record shows."""

    def funnel(self):
        out = self.ok("pipeline.py", "queue", "--data", self.data)
        return next(l for l in out.splitlines() if l.startswith("Funnel:"))

    def tombstone(self, pipeline):
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": APPLIED, "removed": "2026-11-12", "reason": "closed", "company": "Harborline Logistics",
            "title": "Senior Product Manager, Shipment Visibility", "pipeline": pipeline}])

    def test_current_record_and_tombstone_count_once(self):
        before = self.funnel()
        self.tombstone(read(self.data / f"6-system/jobs/{APPLIED}.json")["pipeline"])
        self.assertEqual(self.funnel(), before)

    def test_the_tombstones_application_still_counts_when_the_new_record_has_none(self):
        before = self.funnel()
        pl = read(self.data / f"6-system/jobs/{APPLIED}.json")["pipeline"]
        edit_json(self.data / f"6-system/jobs/{APPLIED}.json", lambda j: j.pop("pipeline") and None)
        self.tombstone(pl)
        self.assertEqual(self.funnel(), before)

    def test_a_removed_applied_job_that_is_not_current_still_counts(self):
        before = self.funnel()
        edit_json(self.data / "6-system/removed.json", lambda t: t + [{
            "job_id": "9100000888", "removed": "2026-11-12", "reason": "rejected",
            "pipeline": {"status": "rejected", "events": [{"date": "2026-11-10", "stage": "applied"}]}}])
        self.assertNotEqual(self.funnel(), before)


class PhoneRunIds(SampleCase):
    """#3 (areas 4-6): saved_job_ids must be a list of IDs; text there was read one character at a time."""

    def test_a_string_is_refused_with_the_file_named(self):
        f = self.data / "6-system/search-runs/phone-run-2026-11-20.json"
        for bad in ("9100000001", ["9100000001", 9100000002], {"9100000001": True}):
            with self.subTest(bad=bad):
                f.write_text(json.dumps({"triage_type": "phone", "round": 2, "date": "2026-11-20",
                                         "saved_job_ids": bad}), encoding="utf-8")
                code, out = run("metrics.py", "--data", self.data)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("phone-run-2026-11-20.json", out)
        f.write_text(json.dumps({"triage_type": "phone", "round": 2, "date": "2026-11-20",
                                 "saved_job_ids": ["9100000001"]}), encoding="utf-8")
        self.ok("metrics.py", "--data", self.data)


class RoundsOutOfOrder(SampleCase):
    """#4 (areas 4-6): the latest round is the highest-numbered one, whatever order metrics.json lists them in."""

    def test_reversed_rounds_give_the_same_totals(self):
        import metrics
        from paths import Paths
        P = Paths(str(self.data))
        before = metrics.totals(P)
        table = self.ok("metrics.py", "--data", self.data)
        edit_json(self.data / "6-system/metrics.json", lambda m: m["rounds"].reverse())
        self.assertEqual(metrics.totals(P), before)
        self.assertEqual(self.ok("metrics.py", "--data", self.data), table)
        self.assertEqual(before["round"], 2)


# ---- third batch: areas 7-8 ----------------------------------------------------------------------------------------

class ScanTargetMustExist(SampleCase):
    """#1 (areas 7-8): a scan of a path that isn't there is not a clean scan."""

    def test_a_missing_target_fails(self):
        terms = self.tmp / "terms.txt"
        terms.write_text("Jordan Avery\n", encoding="utf-8")
        good = self.tmp / "repo"
        good.mkdir()
        (good / "a.md").write_text("nothing personal", encoding="utf-8")
        for args in ((self.tmp / "engnie",), (good, self.tmp / "engnie")):
            with self.subTest(args=args):
                code, out = run("privacy_scan.py", *args, "--terms", terms, "--strict")
                self.assertEqual(code, 2, out)
                self.assertIn("engnie", out)
                self.assertNotIn("0 hits", out)
        self.assertEqual(run("privacy_scan.py", good, "--terms", terms, "--strict")[0], 0)


class TriagedCommandLine(SampleCase):
    """#2 (areas 7-8): a mistyped triaged.py command fails, with a message and no traceback."""

    def test_invalid_invocations_fail_cleanly(self):
        run_file = self.data / "6-system/search-runs/s1-run-2026-11-13.json"
        for args in (("sede",), (), ("reposts", "--data"), ("add",), ("keeps", run_file, "extra"),
                     ("reposts", "extra"), ("seed", "extra")):
            with self.subTest(args=args):
                extra = () if "--data" in args else ("--data", self.data)
                code, out = run("triaged.py", *args[:1], *extra, *args[1:]) if args else run("triaged.py", *extra)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertTrue(out.strip(), "no message")

    def test_valid_commands_and_help_still_work(self):
        run_file = self.data / "6-system/search-runs/s1-run-2026-11-13.json"
        self.ok("triaged.py", "keeps", run_file, "--data", self.data)
        self.ok("triaged.py", "--data", self.data, "reposts")
        self.assertIn("match-saved", self.ok("triaged.py", "--help"))


class RoundNumbers(SampleCase):
    """#3 (areas 7-8): a round is a whole number from 1 up; 0 was silently ignored and -1 was recorded."""

    def test_metrics_refuses_zero_and_negative_rounds(self):
        metrics = self.data / "6-system/metrics.json"
        before = metrics.read_text(encoding="utf-8")
        for args in (("--round", "0"), ("--round", "-1"), ("--round", "0", "--event", "triage")):
            with self.subTest(args=args):
                code, out = run("metrics.py", *args, "--data", self.data)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("round", out)
                self.assertNotIn("--event needs --round", out)
        self.assertEqual(metrics.read_text(encoding="utf-8"), before)

    def test_an_event_without_a_round_still_asks_for_one(self):
        code, out = run("metrics.py", "--event", "triage", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertIn("--event needs --round", out)

    def test_the_report_and_precision_refuse_them_too(self):
        for script in ("build_report.py", "precision.py"):
            with self.subTest(script=script):
                code, out = run(script, "--round", "0", "--data", self.data)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("Traceback", out)


class PremiumMatchScale(unittest.TestCase):
    """The match gate knows both of LinkedIn's scales: free (well / some / missing) and Premium (top / high /
    medium / low). A DQ on Premium's medium or low is a match-line DQ, like a free "some" or "missing"."""

    def test_both_scales(self):
        from modes import match_gated
        for value, gated in (("some", True), ("missing", True), ("medium", True), ("low", True), ("Medium", True),
                             ("well", False), ("top", False), ("high", False), ("not available", False), ("", False)):
            with self.subTest(value=value):
                self.assertIs(match_gated({"decision": "dq", "linkedin_match": value}), gated)
        self.assertFalse(match_gated({"decision": "keep", "linkedin_match": "low"}))


if __name__ == "__main__":
    unittest.main()
