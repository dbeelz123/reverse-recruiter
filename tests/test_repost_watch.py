"""Repost watch (engine/triaged.py): card terms on each sighting, DQ'd listings back with new terms, and the
repost-watch report (evergreen listings, gone-and-back listings, companies that relist)."""
import json
import unittest

from helpers import SampleCase
import triaged


def entry(company, title, seen, decision="dq", reason="no match"):
    return {"company": company, "title": title, "decision": decision, "reason": reason, "seen": seen, "source": "test"}


class ChangedTerms(unittest.TestCase):
    def test_new_salary_is_a_change(self):
        e = entry("Acme", "Senior Product Manager", [{"date": "2026-11-01", "salary": "$120K/yr - $140K/yr"}])
        got = triaged.changed_terms({"salary": "$150K/yr - $180K/yr"}, e)
        self.assertEqual(got["salary"]["was"], "$120K/yr - $140K/yr")

    def test_same_terms_formatted_differently_is_not(self):
        e = entry("Acme", "Senior Product Manager", [{"date": "2026-11-01", "salary": "$150,000.00 - $180,000.00"}])
        self.assertEqual(triaged.changed_terms({"salary": "$150,000 - $180,000"}, e), {})

    def test_location_seen_on_any_earlier_sighting_is_not(self):
        # One posting listed in several cities shows a different location on each card.
        e = entry("Acme", "Senior Product Manager", [{"date": "2026-11-01", "location": "Austin, TX"},
                                                     {"date": "2026-11-01", "location": "Denver, CO"}])
        self.assertEqual(triaged.changed_terms({"location": "Austin, TX"}, e), {})
        self.assertIn("location", triaged.changed_terms({"location": "United States (Remote)"}, e))

    def test_missing_side_is_not_a_change(self):
        e = entry("Acme", "Senior Product Manager", [{"date": "2026-11-01"}])
        self.assertEqual(triaged.changed_terms({"salary": "$150K/yr"}, e), {})
        e = entry("Acme", "Senior Product Manager", [{"date": "2026-11-01", "salary": "$150K/yr"}])
        self.assertEqual(triaged.changed_terms({"salary": None}, e), {})


class MalformedSightings(unittest.TestCase):
    # Copilot review 2026-11-24: hand-edited triaged.json entries with odd 'seen' values must not crash.
    def test_changed_terms_skips_non_dict_sightings(self):
        e = {"seen": ["bad", None, 3, {"salary": "$100K/yr"}]}
        self.assertEqual(triaged.changed_terms({"salary": "$150K/yr"}, e)["salary"]["was"], "$100K/yr")
        self.assertEqual(triaged.changed_terms({"salary": "$150K/yr"}, {"seen": None}), {})

    def test_watch_skips_bad_sightings_and_dates(self):
        rows = triaged.watch([
            {"company": "Acme", "title": "PM", "decision": "dq", "seen": [None, "x", {"date": "not a date"},
                                                                         {"date": "2026-11-01", "search": "S1"}]},
            {"company": "Globex", "title": "PM", "decision": "dq", "seen": None}])
        self.assertEqual([(r["entry"]["company"], r["days"]) for r in rows], [("Acme", 1)])


class AfterRemoval(unittest.TestCase):
    def test_reports_the_latest_removal_before_the_sighting(self):
        # Copilot review 2026-11-24 (round 2): two removals, then seen again -> cite the later removal.
        rows = triaged.watch([{"company": "Acme", "title": "PM", "decision": "dq", "seen": [
            {"search": "saved", "date": "2026-11-10"}, {"search": "saved", "date": "2026-11-20"},
            {"search": "S1", "date": "2026-11-25"}]}])
        self.assertEqual(str(rows[0]["after_removal"]), "2026-11-20")

    def test_removal_after_the_last_sighting_is_not_a_return(self):
        rows = triaged.watch([{"company": "Acme", "title": "PM", "decision": "dq", "seen": [
            {"search": "S1", "date": "2026-11-05"}, {"search": "saved", "date": "2026-11-10"}]}])
        self.assertIsNone(rows[0]["after_removal"])


class Sightings(unittest.TestCase):
    def test_run_listing_terms_go_on_the_sighting(self):
        run = {"search": "S1", "date": "2026-11-24", "listings": [
            {"id": "S1-001", "company": "Acme", "title": "Senior PM", "decision": "dq", "reason": "x",
             "salary": "$150K/yr", "location": "United States (Remote)", "posted": "Reposted 2 days ago"}]}
        seen = list(triaged.listing_entries(run, "test"))[0]["seen"][0]
        self.assertEqual((seen["salary"], seen["location"], seen["posted"]),
                         ("$150K/yr", "United States (Remote)", "Reposted 2 days ago"))


class CheckAndReport(SampleCase):
    def write_db(self, entries):
        path = self.data / "6-system/triaged.json"
        path.write_text(json.dumps({"updated": "2026-11-24", "note": "test", "entries": entries}), encoding="utf-8")

    def check(self, cards):
        path = self.tmp / "cards.json"
        path.write_text(json.dumps(cards), encoding="utf-8")
        out = self.ok("triaged.py", "--data", self.data, "check", path)
        return json.loads(path.read_text(encoding="utf-8")), out

    def test_dq_back_with_new_terms_is_flagged_not_skipped(self):
        self.write_db([entry("Acme", "Senior Product Manager",
                             [{"date": "2026-11-01", "salary": "$110K/yr - $130K/yr", "location": "Austin, TX"}])])
        cards, out = self.check([
            {"company": "Acme", "title": "Senior Product Manager", "salary": "$160K/yr - $190K/yr",
             "location": "Austin, TX", "status": []},
            {"company": "Acme", "title": "Senior Product Manager", "salary": "$110K/yr - $130K/yr",
             "location": "Austin, TX", "status": []}])
        self.assertEqual(cards[0]["triaged"]["action"], "flag (terms changed)")
        self.assertEqual(set(cards[0]["triaged"]["changed"]), {"salary"})
        self.assertEqual(cards[1]["triaged"]["action"], "skip")
        self.assertIn("terms changed: Acme - Senior Product Manager", out)

    def test_job_removed_since_the_last_seed_is_recognized(self):
        self.write_db([])  # removed.json holds a tombstone triaged.json doesn't
        cards, _ = self.check([{"company": "Velocity Rideshare Freight", "title": "Product Manager, Field Ops",
                                "status": []}])
        self.assertEqual(cards[0]["triaged"]["action"], "skip")
        self.assertIn("removed:", cards[0]["triaged"]["reason"])

    def test_check_survives_entries_without_sightings(self):
        self.write_db([{"company": "Acme", "title": "Senior Product Manager", "decision": "dq", "reason": "x",
                        "seen": []},
                       {"company": "Globex", "title": "Principal Product Manager", "decision": "dq", "reason": "y"}])
        cards, _ = self.check([{"company": "Acme", "title": "Senior Product Manager", "status": []},
                               {"company": "Globex", "title": "Principal Product Manager", "status": []}])
        self.assertEqual([c["triaged"]["action"] for c in cards], ["skip", "skip"])
        self.assertIsNone(cards[0]["triaged"]["seen"])

    def test_same_day_removal_overrules_a_keep(self):
        # Deliberate: a removal on the day of a keep came after it (a job kept in triage, then removed in the round).
        self.write_db([entry("Velocity Rideshare Freight", "Product Manager, Field Ops",
                             [{"search": "S1 v2", "date": "2026-11-10"}], decision="keep", reason="kept")])
        cards, _ = self.check([{"company": "Velocity Rideshare Freight", "title": "Product Manager, Field Ops",
                                "status": []}])
        self.assertEqual(cards[0]["triaged"]["action"], "skip")

    def test_older_removal_does_not_overrule_a_newer_keep(self):
        # A saved posting closed and was removed on 11-10; a relisting was kept on 11-20.
        self.write_db([entry("Velocity Rideshare Freight", "Product Manager, Field Ops",
                             [{"search": "S1 v2", "date": "2026-11-20"}], decision="keep", reason="relisted, kept")])
        cards, _ = self.check([{"company": "Velocity Rideshare Freight", "title": "Product Manager, Field Ops",
                                "status": []}])
        self.assertEqual(cards[0]["triaged"]["action"], "flag")
        self.assertEqual(cards[0]["triaged"]["decision"], "keep")

    def test_report_lists_jobs_seen_again_after_removal(self):
        self.write_db([entry("Velocity Rideshare Freight", "Product Manager, Field Ops",
                             [{"search": "S1 v2", "date": "2026-11-20"}], decision="keep", reason="relisted")])
        self.ok("triaged.py", "--data", self.data, "reposts")
        md = (self.data / "2-reports/repost-watch.md").read_text(encoding="utf-8")
        self.assertIn("- Velocity Rideshare Freight: Product Manager, Field Ops (keep): removed 2026-11-10, "
                      "seen again 2026-11-20", md)

    def test_report_finds_evergreen_and_gone_and_back(self):
        self.write_db([
            entry("Acme", "Senior Product Manager", [{"date": "2026-10-01", "posted": "Reposted 1 week ago"},
                                                     {"date": "2026-10-15"}, {"date": "2026-11-05"}]),
            # S2 ran on 11-06 without Globex: gone, then back on 11-12.
            entry("Globex", "Principal Product Manager", [{"search": "S2 v1", "date": "2026-11-01"},
                                                          {"search": "S2 v2", "date": "2026-11-12"}]),
            entry("Hooli", "Senior Product Manager", [{"search": "S2 v1", "date": "2026-11-06"}]),
            # S5 didn't run between 11-01 and 11-12: a gap in searching, not a relisting.
            entry("Initech", "Product Manager", [{"search": "S5", "date": "2026-11-01"},
                                                 {"search": "S5", "date": "2026-11-12"}]),
        ])
        out = self.ok("triaged.py", "--data", self.data, "reposts")
        self.assertIn("1 evergreen", out)
        self.assertIn("1 gone and back", out)
        md = (self.data / "2-reports/repost-watch.md").read_text(encoding="utf-8")
        self.assertIn("| Acme: Senior Product Manager | dq | 3 | 35d |", md)
        self.assertIn("- Globex: Principal Product Manager (dq)", md)
        self.assertNotIn("Initech", md.split("## Gone and back")[1].split("## Salary")[0])
        self.assertNotIn("Too early to judge", md)


if __name__ == "__main__":
    unittest.main()
