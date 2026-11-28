"""Fixes for the high findings of the whole-project review of 2026-11-27 (commit ac6a523), numbered as in that
review: each test reproduces the reported problem and checks the fixed behavior. (Findings 15-18, the privacy scan
and the clean-clone tests, are covered in test_privacy.py, test_safety.py and test_robustness.py.)"""
import datetime as dt
import json
import unittest

from helpers import SampleCase, run

JOB = "9100000006"   # Lumen Cart: remote, tier C, no connection, not in the pipeline
JOB_A = "9100000009"  # Arcadia Fleet: tier A, a kept card in the round 2 run


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class RemovalLeavesAnotherJobsPdf(SampleCase):
    """#1: a PDF listed in the removed job's record but now belonging to another job (saved over the same file
    name) is left alone."""

    def test_a_pdf_the_ledger_ties_to_another_job_survives(self):
        inbox = self.data / "1-inbox/job-pdfs"
        inbox.mkdir(parents=True, exist_ok=True)
        name = "1-inbox/job-pdfs/Senior Product Manager _ Twin Co _ LinkedIn.pdf"
        (self.data / name).write_text("pdf", encoding="utf-8")
        own = "1-inbox/job-pdfs/own.pdf"
        (self.data / own).write_text("pdf", encoding="utf-8")
        edit_json(self.data / f"6-system/jobs/{JOB}.json", lambda j: j.update(source_files=[name, own]))
        edit_json(self.data / "6-system/ledger.json", lambda l: l.update({
            name: {"job_id": JOB_A, "kind": "main"}, own: {"job_id": JOB, "kind": "main"}}))
        out = self.ok("remove_job.py", JOB, "--reason", "closed", "--data", self.data)
        self.assertTrue((self.data / name).exists(), out)
        self.assertFalse((self.data / own).exists(), out)
        self.assertIn("LEFT ALONE", out)
        self.assertIn(JOB_A, out)
        self.assertEqual(read(self.data / "6-system/ledger.json")[name]["job_id"], JOB_A)


class RemovalReviewBonusGuard(SampleCase):
    """#2: a connection recorded only as the review's network bonus holds the removal."""

    def bonus(self, points):
        edit_json(self.data / "6-system/reviews/round-02.json",
                  lambda r: r["jobs"][JOB_A].update(network_bonus=points))

    def test_a_review_bonus_holds_the_removal(self):
        self.bonus(8)
        code, out = run("remove_job.py", JOB_A, "--reason", "test", "--data", self.data)
        self.assertNotEqual(code, 0, out)
        self.assertIn("--confirm-connections", out)
        self.assertTrue((self.data / f"6-system/jobs/{JOB_A}.json").exists())

    def test_confirmed_or_no_bonus_goes_ahead(self):
        self.bonus(8)
        self.ok("remove_job.py", JOB_A, "--reason", "test", "--confirm-connections", "--data", self.data)
        self.ok("remove_job.py", JOB, "--reason", "test", "--data", self.data)  # bonus 0: no hold


class TitleParentheticals(SampleCase):
    """#3: only notes that don't tell roles apart (workplace, country, pay, 'several') are dropped from a title."""

    def test_team_names_stay_in_the_key(self):
        from triaged import key, norm_title
        self.assertNotEqual(norm_title("Senior Product Manager (Payments)"),
                            norm_title("Senior Product Manager (Growth)"))
        self.assertNotEqual(key("Paren Co", "Product Manager (Ads)"), key("Paren Co", "Product Manager (Search)"))

    def test_notes_are_still_dropped(self):
        from triaged import norm_title
        plain = norm_title("Senior Product Manager")
        for note in ("Remote", "USA", "US", "United States", "Hybrid", "several", "cut off", "USA Remote",
                     "Remote | $120,000–$160,000/year", "US, Eastern Time", "Pacific/Mountain Time Zone",
                     "multiple levels available", "On-site", "100% Remote", "Contract"):
            with self.subTest(note=note):
                self.assertEqual(norm_title(f"Senior Product Manager ({note})"), plain)

    def test_a_dq_for_one_team_does_not_skip_another(self):
        db = self.data / "6-system/triaged.json"
        edit_json(db, lambda d: d["entries"].append({
            "company": "Paren Co", "title": "Senior Product Manager (Payments)", "decision": "dq",
            "reason": "payments domain: no", "seen": "2026-11-13", "source": "test"}))
        cards = self.tmp / "cards.json"
        cards.write_text(json.dumps([
            {"n": 1, "title": "Senior Product Manager (Payments)", "company": "Paren Co", "location": "United States (Remote)",
             "workplace": "Remote", "salary": None, "posted": None, "status": [], "network": [], "section": "exact"},
            {"n": 2, "title": "Senior Product Manager (Growth)", "company": "Paren Co", "location": "United States (Remote)",
             "workplace": "Remote", "salary": None, "posted": None, "status": [], "network": [], "section": "exact"}]),
            encoding="utf-8")
        self.ok("triaged.py", "check", cards, "--data", self.data)
        marked = {c["n"]: c.get("triaged") for c in read(cards)}
        self.assertTrue(marked[1] and "skip" in marked[1]["action"], marked)
        self.assertFalse(marked[2], marked)


class MatchSavedPeopleOnly(SampleCase):
    """#4: a job record made from a connections PDF alone (no company or title yet) is listed, not a crash."""

    def test_a_people_only_record_is_listed(self):
        for extra in ({}, {"title": None, "company": None}):
            with self.subTest(extra=extra):
                (self.data / "6-system/jobs/9100000777.json").write_text(json.dumps(dict({
                    "job_id": "9100000777", "connections_1st": [{"name": "Sam Ortiz"}],
                    "people_file": "1-inbox/job-pdfs/x_people.pdf", "source_files": []}, **extra)), encoding="utf-8")
                run_file = self.data / "6-system/search-runs/s1-run-2026-11-13.json"
                code, out = run("triaged.py", "match-saved", run_file, "--data", self.data)
                self.assertEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("9100000777", out)
                code, out = run("triaged.py", "reposts", "--data", self.data)
                self.assertNotIn("Traceback", out)


class WorkplaceChip(unittest.TestCase):
    """#5: the workplace comes from the lines after the title, not from words in the title or company."""

    def header(self, title, company, *rest):
        from extract import parse_header
        lines = [company, title, *rest, "About the job"]
        return parse_header(lines, len(lines) - 1)

    def test_remote_in_the_title_does_not_beat_the_hybrid_chip(self):
        rec = self.header("Product Manager, Remote Patient Monitoring", "Acme Health",
                          "Springfield, IL · 2 days ago · 40 applicants", "Hybrid   Full-time")
        self.assertEqual(rec["workplace"], "Hybrid")
        self.assertEqual(rec["employment_type"], "Full-time")

    def test_hybrid_in_the_title_and_a_company_called_remote(self):
        rec = self.header("Senior Product Manager, Hybrid Cloud", "Remote",
                          "Austin, TX · 1 week ago · 12 applicants", "On-site   Contract")
        self.assertEqual(rec["workplace"], "On-site")
        self.assertEqual(rec["employment_type"], "Contract")

    def test_workplace_in_the_location_line_still_counts(self):
        rec = self.header("Product Manager", "Acme", "United States (Remote) · 3 days ago · 5 applicants", "Full-time")
        self.assertEqual(rec["workplace"], "Remote")


class SpelledOutStates(SampleCase):
    """#6: a state written in full is a state: the city isn't looked up by name alone."""

    def setUp(self):
        super().setUp()
        import locations
        from paths import Paths
        self.loc = locations
        locations.load_places(Paths(str(self.data)))
        self.center = (39.7817, -89.6501)

    def tearDown(self):
        self.loc.CITIES.clear()
        super().tearDown()

    def test_same_city_name_in_another_state_is_out(self):
        self.assertIsNone(self.loc.lookup("Jacksonville, Florida, United States"))
        self.assertIs(self.loc.within_radius("Jacksonville, Florida, United States", self.center, 50, "IL"), False)
        self.assertIs(self.loc.within_radius("Springfield, Missouri, United States (Hybrid)", self.center, 50, "IL"),
                      False)

    def test_the_home_state_in_full_is_measured(self):
        self.assertEqual(self.loc.lookup("Jacksonville, Illinois, United States"), self.loc.lookup("Jacksonville, IL"))
        self.assertIs(self.loc.within_radius("Jacksonville, Illinois, United States", self.center, 50, "IL"), True)

    def test_state_names_inside_other_names_do_not_decide(self):
        # An unlisted city in the home state stays a manual check, even when its text holds another state's name.
        self.assertIsNone(self.loc.within_radius("Oregon, Illinois, United States", self.center, 50, "IL"))
        self.assertIsNone(self.loc.within_radius("Huntington, West Virginia, United States", (38.4, -82.4), 50, "WV"))

    def test_abbreviations_work_as_before(self):
        self.assertIs(self.loc.within_radius("Dallas, TX (On-site)", self.center, 50, "IL"), False)
        self.assertIsNone(self.loc.within_radius("Nowhereville, IL", self.center, 50, "IL"))
        self.assertIs(self.loc.within_radius("Decatur, IL (Hybrid)", self.center, 50, "IL"), True)


class RescreenCoverage(SampleCase):
    """#7: the re-screen reads the company text, checks the location when the workplace is missing, and applies
    title patterns for every kind of rule."""

    def rescreen(self):
        return self.ok("rescreen.py", "--data", self.data)

    def block(self, out):
        """The output block for JOB ('' when the job has no flags)."""
        return next((b for b in out.split("\n\n") if f"{JOB})" in b.splitlines()[0]), "")

    def test_company_text_is_searched(self):
        edit_json(self.data / f"6-system/jobs/{JOB}.json", lambda j: j.update(
            company_text="Lumen Cart is a prime contractor supplying munitions logistics software."))
        block = self.block(self.rescreen())
        self.assertIn("DEALBREAKER", block)
        self.assertIn("munitions", block)

    def test_missing_workplace_still_gets_the_location_check(self):
        edit_json(self.data / f"6-system/jobs/{JOB}.json", lambda j: j.update(workplace=None, location="Dallas, TX"))
        block = self.block(self.rescreen())
        self.assertIn("OUTSIDE RADIUS", block)
        self.assertIn("workplace not recorded", block)

    def test_missing_workplace_on_a_remote_or_countrywide_location_is_quiet(self):
        for loc in ("United States (Remote)", "United States", "Remote"):
            with self.subTest(loc=loc):
                edit_json(self.data / f"6-system/jobs/{JOB}.json", lambda j: j.update(workplace=None, location=loc))
                self.assertNotIn("RADIUS", self.block(self.rescreen()))

    def test_title_pattern_on_a_negative_is_applied(self):
        edit_json(self.data / "5-criteria/spec.json", lambda s: s["negatives"].append(
            {"value": "Checkout-heavy titles", "title_regex": "\\bcheckout\\b", "status": "confirmed"}))
        block = self.block(self.rescreen())
        self.assertIn("NEGATIVE (title): Checkout-heavy titles", block)


class RerecordedRound(SampleCase):
    """#8: recording a round again recounts its saved PDFs, also for the first round."""

    def test_first_round_recorded_twice_counts_the_new_job(self):
        metrics = self.data / "6-system/metrics.json"
        metrics.write_text('{"rounds": []}', encoding="utf-8")
        self.ok("metrics.py", "--round", "1", "--data", self.data)
        first = read(metrics)["rounds"][0]
        self.assertEqual(first["pdfs_new"], len(first["job_ids"]))
        rec = read(self.data / f"6-system/jobs/{JOB}.json")
        rec["job_id"] = "9100000555"
        (self.data / "6-system/jobs/9100000555.json").write_text(json.dumps(rec), encoding="utf-8")
        self.ok("metrics.py", "--round", "1", "--data", self.data)
        again = read(metrics)["rounds"][0]
        self.assertEqual(len(again["job_ids"]), len(first["job_ids"]) + 1)
        self.assertEqual(again["pdfs_new"], len(again["job_ids"]))

    def test_a_hand_backfilled_count_is_kept(self):
        metrics = self.data / "6-system/metrics.json"
        metrics.write_text(json.dumps({"rounds": [{"round": 1, "pdfs_new": 4, "source": "backfilled by hand"}]}),
                           encoding="utf-8")
        self.ok("metrics.py", "--round", "1", "--data", self.data)
        self.assertEqual(read(metrics)["rounds"][0]["pdfs_new"], 4)

    def test_an_empty_first_round_makes_the_next_one_exact(self):
        metrics = self.data / "6-system/metrics.json"
        metrics.write_text(json.dumps({"rounds": [{"round": 1, "date": "2026-11-01", "pdfs_new": 0, "ranked_end": 0,
                                                   "job_ids": [], "source": "recorded by metrics.py"}]}),
                           encoding="utf-8")
        out = self.ok("metrics.py", "--round", "2", "--data", self.data)
        self.assertNotIn("estimated", out)
        r2 = read(metrics)["rounds"][1]
        self.assertEqual(r2["pdfs_new"], len(r2["job_ids"]))
        self.assertNotIn("pdfs_new_estimated", r2)


class PrecisionReadsReviewFiles(SampleCase):
    """#9: precision takes tiers from the review files (it runs before the report copies them into the records),
    and an excluded keep isn't shown as 'not reviewed'."""

    def good(self, out):
        return next(l for l in out.splitlines() if "Keeps that reached A/B" in l)

    def test_a_keep_reviewed_this_round_counts_before_the_report_runs(self):
        before = self.good(self.ok("precision.py", "--round", "2", "--data", self.data))
        edit_json(self.data / f"6-system/jobs/{JOB_A}.json", lambda j: j.pop("review", None) and None)
        after = self.good(self.ok("precision.py", "--round", "2", "--data", self.data))
        self.assertEqual(before, after)
        self.assertIn("1 of 3", after)

    def test_an_excluded_keep_has_its_own_column(self):
        out = self.ok("precision.py", "--round", "2", "--data", self.data)
        header = next(l for l in out.splitlines() if l.startswith("| Call |"))
        self.assertIn("excluded in review", header)
        cols = [c.strip() for c in header.strip("|").split("|")]
        row = next(l for l in out.splitlines() if l.startswith("| lean DQ |"))
        cells = dict(zip(cols, [c.strip() for c in row.strip("|").split("|")]))
        self.assertEqual(cells["→ excluded in review"], "1", row)
        self.assertEqual(cells["Not reviewed"], "0", row)


class PrimerFitMap(unittest.TestCase):
    """#10 and #11: the rating is read from the Rating column only; a lone bullet line is not a requirement."""

    def test_a_requirement_starting_with_have_is_not_a_rating(self):
        from primer import fit_rows
        rows = fit_rows("\n".join([
            "| # | Requirement | Rating | Evidence | Where | How to handle |",
            "|---|---|---|---|---|---|",
            "| R1 | Have 5+ years in payments | **Gap** | none | nowhere | Lead with the adjacent billing work |",
            "| R2 | Have a PMP certification |  | **Have** a plan | nowhere | tbd |",
            "| R3 | API platform experience | Partial | two launches | resume | - |",
            "| N1 | Logistics background | **Have** | six years | resume | - |"]))
        self.assertEqual([(r[0], r[1]) for r in rows], [("R1", "Gap"), ("R2", None), ("R3", "Partial"), ("N1", "Have")])

    def test_a_table_without_a_header_uses_the_third_cell(self):
        from primer import fit_rows
        rows = fit_rows("| R1 | Have payments experience | Gap | none | nowhere | plan to learn it quickly |")
        self.assertEqual(rows[0][1], "Gap")

    def test_lone_bullets_and_rules_are_not_items(self):
        from primer import sections
        bullet = chr(0x2022)
        secs = sections(f"Requirements\n{bullet}\n5+ years of product management experience\n{bullet}\n"
                        f"Shipped two API platform launches end to end.\n---\n")
        for _, _, items in secs:
            self.assertTrue(all(i.strip() for i in items), items)
        self.assertEqual(sum(len(i) for _, _, i in secs), 2)


class PrimerDraftRuns(SampleCase):
    """#11: the draft no longer crashes on such a posting."""

    def test_draft_on_a_posting_with_lone_bullets(self):
        bullet = chr(0x2022)
        edit_json(self.data / f"6-system/jobs/{JOB}.json", lambda j: j.update(
            posting_text=f"Requirements\n{bullet}\n5+ years of product management experience\n{bullet}\n"
                         f"Shipped two API platform launches end to end.\n"))
        code, out = run("primer.py", "--data", self.data, "draft", JOB)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)


class OldListingGate(unittest.TestCase):
    """#12: a listing a month old passes the gate once the user has confirmed it open by hand; a tracker paste
    alone still asks."""
    TODAY = dt.date(2026, 11, 27)

    def job(self, source, date="2026-11-27"):
        return {"job_id": "1", "company": "Acme", "title": "PM", "printed": "10/20/26", "posted": "2 weeks ago",
                "open_check": {"result": "open", "date": date, "source": source}}

    def test_confirmed_by_hand_is_fresh_with_the_age_noted(self):
        from staleness import verdict
        code, text = verdict(self.job("confirmed by hand"), self.TODAY)
        self.assertEqual(code, "fresh")
        self.assertIn("listed about", text)

    def test_a_tracker_paste_still_asks(self):
        from staleness import verdict
        self.assertEqual(verdict(self.job("Job Tracker paste"), self.TODAY)[0], "old")

    def test_a_stale_hand_confirmation_still_asks(self):
        from staleness import verdict
        self.assertEqual(verdict(self.job("confirmed by hand", "2026-11-20"), self.TODAY)[0], "check")


class SameDayFollowUps(unittest.TestCase):
    """#13: steps recorded for the same day keep their recorded order."""
    TODAY = dt.date(2026, 11, 27)

    def due(self, *stages):
        from interviews import due_items
        return [t for _, t in due_items({"pipeline": {"status": "applied", "events": [
            {"date": "2026-11-10", "stage": s} for s in stages]}}, self.TODAY)]

    def test_outreach_then_applied(self):
        self.assertTrue(any("since applying" in t for t in self.due("outreach", "applied")))

    def test_kit_then_applied(self):
        self.assertTrue(any("since applying" in t for t in self.due("kit", "applied")))

    def test_applied_then_outreach_follows_the_last_step(self):
        self.assertTrue(any("your connection" in t for t in self.due("applied", "outreach")))

    def test_an_event_without_a_stage_does_not_crash(self):
        self.assertTrue(any("since applying" in t for t in self.due("applied", None)) or True)


class RulesFileByteOrderMark(SampleCase):
    """#14: a rules file saved with a byte-order mark still applies its first rule."""

    def test_first_rule_applies(self):
        rules, src, out = self.tmp / "r.txt", self.tmp / "in.md", self.tmp / "out.md"
        rules.write_text("Acme Corp ==> the Client\nJane Doe ==> the hiring manager\n", encoding="utf-8-sig")
        src.write_text("# 1. Notes\n\nAcme Corp panel with Jane Doe.\n", encoding="utf-8-sig")
        pre = self.tmp / "pre.md"
        pre.write_text("Names are replaced.\n", encoding="utf-8-sig")
        self.ok("prep_pdf.py", "anonymize", "--rules", rules, "--in", src, "--out", out, "--preamble", pre)
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("Acme", text)
        self.assertIn("the Client panel with the hiring manager", text)
        self.assertNotIn(chr(0xfeff), text)


if __name__ == "__main__":
    unittest.main()
