"""Fixes from the fifth code review: each test reproduces the reported problem and checks the fixed behavior."""
import datetime as dt
import json
import unittest

from helpers import SampleCase, run


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class LastEvent(unittest.TestCase):
    def test_an_undated_step_does_not_beat_a_dated_one(self):
        from pipeline import last_event
        pl = {"events": [{"date": "2026-11-18", "stage": "applied"}, {"date": "unknown", "stage": "response"}]}
        self.assertEqual(last_event(pl)["stage"], "applied")

    def test_latest_date_wins_and_same_date_goes_to_the_later_record(self):
        from pipeline import last_event
        pl = {"events": [{"date": "2026-11-18", "stage": "applied"}, {"date": "2026-11-02", "stage": "outreach"},
                         {"date": "2026-11-18", "stage": "response"}]}
        self.assertEqual(last_event(pl)["stage"], "response")

    def test_only_undated_steps_gives_the_last_recorded(self):
        from pipeline import last_event
        pl = {"events": [{"date": "unknown", "stage": "applied"}, {"date": "unknown", "stage": "response"}]}
        self.assertEqual(last_event(pl)["stage"], "response")


class ScheduledInterviewTimer(unittest.TestCase):
    def test_no_follow_up_while_an_undated_interview_is_still_scheduled(self):
        from interviews import due_items
        today = dt.date(2026, 11, 30)
        job = {"pipeline": {"status": "interview",
                            "events": [{"date": "2026-11-20", "stage": "interview", "note": "Round 1 scheduled"}]},
               "interviews": [{"round": 1, "status": "scheduled"}]}
        texts = [t for _, t in due_items(job, today)]
        self.assertFalse(any("no news" in t for t in texts), texts)

    def test_follow_up_still_runs_after_the_debrief(self):
        from interviews import due_items
        today = dt.date(2026, 11, 30)
        job = {"pipeline": {"status": "interview",
                            "events": [{"date": "2026-11-20", "stage": "interview", "note": "Round 1 scheduled"}]},
               "interviews": [{"round": 1, "status": "done", "date": "2026-11-21"}]}
        texts = [t for _, t in due_items(job, today)]
        self.assertTrue(any("no news" in t for t in texts), texts)


class TrackerMatch(unittest.TestCase):
    JOBS = {"a": {"job_id": "a", "company": "Acme Corp", "title": "Senior Product Manager, Platform A"},
            "b": {"job_id": "b", "company": "Acme Corp", "title": "Senior Product Manager, Platform B"}}

    def test_an_ambiguous_fuzzy_title_matches_nothing(self):
        from staleness import match_job
        self.assertIsNone(match_job(self.JOBS, "Senior Product Manager, Platform C", "Acme Corp"))

    def test_exact_and_unique_fuzzy_titles_still_match(self):
        from staleness import match_job
        self.assertEqual(match_job(self.JOBS, "Senior Product Manager, Platform B", "Acme Corp")["job_id"], "b")
        one = {"a": self.JOBS["a"]}
        self.assertEqual(match_job(one, "Senior Product Manager - Platform A", "Acme")["job_id"], "a")


class IngestFieldTypes(SampleCase):
    def test_wrong_field_types_stop_with_a_clear_message(self):
        src = self.tmp / "rows.json"
        src.write_text(json.dumps([{"title": "PM", "company": "Acme", "location": "Remote"},
                                   {"title": 123, "company": "Acme", "status": 123}]), encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("row 2", out)
        self.assertFalse((self.tmp / "cards.json").exists())

    def test_list_status_and_network_still_work(self):
        src = self.tmp / "rows.json"
        src.write_text(json.dumps([{"title": "PM", "company": "Acme", "location": "Remote",
                                    "status": ["Viewed"], "network": ["2 connections work here"]}]), encoding="utf-8")
        run_out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertEqual(run_out[0], 0, run_out[1])


class ReportFileTypes(SampleCase):
    def test_wrong_top_level_types_name_the_file(self):
        for rel in ("6-system/skills-gap.json", "6-system/calibration/round-02.json"):
            with self.subTest(rel=rel):
                p = self.data / rel
                original = p.read_text(encoding="utf-8")
                p.write_text("[]", encoding="utf-8")
                code, out = run("build_report.py", "--data", self.data, "--round", "2")
                p.write_text(original, encoding="utf-8")
                self.assertNotEqual(code, 0)
                self.assertNotIn("Traceback", out)
                self.assertIn(p.name, out)


class DataBeforeSubcommand(SampleCase):
    """--data given before the subcommand must be used, not silently replaced by the default data folder."""

    def test_modes_and_linkedin_project_honor_data_before_the_subcommand(self):
        for script, cmd in (("modes.py", "signals"), ("linkedin_project.py", "check")):
            with self.subTest(script=script):
                code_after, after = run(script, cmd, "--data", self.data)
                code_before, before = run(script, "--data", self.data, cmd)
                self.assertEqual((code_before, before), (code_after, after))
                self.assertNotIn("No recorded rounds", before)


if __name__ == "__main__":
    unittest.main()
