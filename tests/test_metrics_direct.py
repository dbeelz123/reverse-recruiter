"""'Job listings processed' counts every unique listing: search-result cards plus saved postings that never showed up
as a card (alert or direct saves, backlog sweeps). Without the second part, a round of direct saves added deep-fit
reviews with no listings behind them, and every per-100 number jumped."""
import json

import helpers
from helpers import SampleCase

import metrics
from paths import Paths


def edit_json(p, fn):
    d = json.loads(p.read_text(encoding="utf-8"))
    r = fn(d)
    p.write_text(json.dumps(d if r is None else r), encoding="utf-8")


class DirectSaves(SampleCase):
    def funnel(self):
        return metrics.funnel_from_runs(Paths(str(self.data)))

    def add_job(self, jid, company, title, rnd):
        """A saved posting (removed later, so it needs no review) first recorded in round `rnd`'s job-ID snapshot."""
        edit_json(self.data / "6-system/removed.json",
                  lambda t: t.append({"job_id": jid, "company": company, "title": title, "removed": "2026-11-13",
                                      "reason": "test"}))

        def snap(m):
            for r in m["rounds"]:
                if r["round"] >= rnd:
                    r["job_ids"] = sorted(set(r["job_ids"]) | {jid})
        edit_json(self.data / "6-system/metrics.json", snap)

    def test_a_direct_save_counts_as_a_listing_in_its_round(self):
        before = self.funnel()
        self.add_job("9100000500", "Nowhere Card Co", "Senior Product Manager, Direct Save", 2)
        after = self.funnel()
        self.assertEqual(after[2]["processed"], before[2]["processed"] + 1)
        self.assertEqual(after[2]["direct"], before[2]["direct"] + 1)
        self.assertEqual(after[1]["processed"], before[1]["processed"])

    def test_a_save_of_a_search_card_is_not_counted_twice(self):
        before = self.funnel()
        # Lattice Haul's card is in round 2's run; saving that posting adds no new listing.
        self.add_job("9100000501", "Lattice Haul", "Senior Product Manager, Freight Payments", 2)
        self.assertEqual(self.funnel()[2]["processed"], before[2]["processed"])

    def test_a_second_posting_with_a_cards_title_counts(self):
        self.add_job("9100000502", "Lattice Haul", "Senior Product Manager, Freight Payments", 2)
        before = self.funnel()
        self.add_job("9100000503", "Lattice Haul", "Senior Product Manager, Freight Payments", 2)
        self.assertEqual(self.funnel()[2]["processed"], before[2]["processed"] + 1)

    def test_a_later_card_for_an_earlier_direct_save_is_not_counted_again(self):
        # Saved directly in round 1, then its card shows up in round 2's search run.
        before = self.funnel()
        self.add_job("9100000504", "Lattice Haul", "Senior Product Manager, Freight Payments", 1)
        after = self.funnel()
        self.assertEqual(after[1]["processed"], before[1]["processed"] + 1)
        self.assertEqual(after[2]["processed"], before[2]["processed"] - 1)

    def test_totals_and_the_table_include_direct_saves(self):
        P = Paths(str(self.data))
        before = metrics.totals(P)["processed"]
        self.add_job("9100000505", "Nowhere Card Co", "Principal Product Manager, Direct Save", 2)
        self.assertEqual(metrics.totals(P)["processed"], before + 1)
        self.assertIn("search cards + direct saves", metrics.table(P))

    def test_saves_before_the_first_snapshot_use_the_backfilled_direct_count(self):
        # Backfilled rounds keep no job IDs: their direct saves are counted from pdfs_new - pdfs_from_triage, and
        # whatever is left lands in the first round that has a snapshot.
        def backfill(m):
            r1 = next(r for r in m["rounds"] if r["round"] == 1)
            r1.pop("job_ids")
            r1["pdfs_from_triage"] = r1["pdfs_new"] - 1          # one direct save in round 1
        edit_json(self.data / "6-system/metrics.json", backfill)
        self.add_job("9100000506", "Nowhere Card Co", "Staff Product Manager, Early Save", 2)
        self.add_job("9100000507", "Nowhere Card Co", "Staff Product Manager, Second Early Save", 2)
        f = self.funnel()
        total_direct = sum(r["direct"] for r in f.values())
        self.assertEqual(f[1]["direct"], 1)
        self.assertEqual(f[2]["direct"], total_direct - 1)

    def link_card(self, company, jid, rnd_file="s1-run-2026-11-13.json"):
        """Write a saved posting's job ID onto that company's card row, as triaged.py match-saved does."""
        def link(d):
            next(x for x in d["listings"] if x["company"] == company)["job_id"] = jid
        edit_json(self.data / "6-system/search-runs" / rnd_file, link)

    def test_a_card_linked_by_job_id_is_not_counted_again_under_a_longer_title(self):
        # The card's title was cut short; the saved posting's PDF title carries more words. Same job ID: one listing.
        before = self.funnel()
        self.link_card("Lattice Haul", "9100000510")
        self.add_job("9100000510", "Lattice Haul", "Senior Product Manager, Freight Payments, Enterprise", 2)
        after = self.funnel()
        self.assertEqual(after[2]["processed"], before[2]["processed"])
        self.assertEqual(after[2]["direct"], before[2]["direct"])

    def test_a_direct_save_whose_linked_card_comes_later_under_another_title_counts_once(self):
        before = self.funnel()
        self.link_card("Lattice Haul", "9100000511")
        self.add_job("9100000511", "Lattice Haul", "Senior Product Manager, Freight Payments, Enterprise", 1)
        after = self.funnel()
        self.assertEqual(after[1]["processed"], before[1]["processed"] + 1)
        self.assertEqual(after[2]["processed"], before[2]["processed"] - 1)

    def test_a_linked_second_posting_with_a_claimed_title_still_counts(self):
        # One posting saved directly in round 1; a second posting with the same title is the round 2 card.
        self.add_job("9100000512", "Lattice Haul", "Senior Product Manager, Freight Payments", 1)
        before = self.funnel()
        self.link_card("Lattice Haul", "9100000513")
        self.add_job("9100000513", "Lattice Haul", "Senior Product Manager, Freight Payments", 2)
        self.assertEqual(self.funnel()[2]["processed"], before[2]["processed"] + 1)

    def test_saves_stay_in_the_totals_when_the_last_round_has_no_usable_snapshot(self):
        P = Paths(str(self.data))
        want = metrics.totals(P)["processed"]
        original = (self.data / "6-system/metrics.json").read_text(encoding="utf-8")
        damage = {"junk": lambda m: m["rounds"][-1].update(job_ids="junk"),
                  "missing": lambda m: m["rounds"][-1].pop("job_ids") and None,
                  "one number": lambda m: m["rounds"][-1]["job_ids"].append(123),
                  "all numbers": lambda m: m["rounds"][-1].update(job_ids=[1, 2, 3])}
        for name, fn in damage.items():
            with self.subTest(name):
                (self.data / "6-system/metrics.json").write_text(original, encoding="utf-8")
                edit_json(self.data / "6-system/metrics.json", fn)
                self.assertEqual(metrics.totals(P)["processed"], want)
                self.assertLessEqual(max(metrics.funnel_from_runs(P)), 2)  # nothing pushed into an unrecorded round

    def test_a_save_after_the_last_recorded_round_waits_for_the_next_round(self):
        P = Paths(str(self.data))
        want = metrics.totals(P)["processed"]
        edit_json(self.data / "6-system/removed.json",
                  lambda t: t.append({"job_id": "9100000514", "company": "Nowhere Card Co", "title": "Pending Save"}))
        self.assertEqual(metrics.totals(P)["processed"], want)
        self.assertEqual(self.funnel()[3]["direct"], 1)
        metrics.add_event(P, 3, "capture")  # round 3 now has an entry, still not recorded
        self.assertEqual(self.funnel()[3]["direct"], 1)

    def test_bad_snapshots_and_nameless_tombstones_do_not_crash(self):
        edit_json(self.data / "6-system/removed.json", lambda t: t.append({"job_id": "9100000508"}))
        edit_json(self.data / "6-system/metrics.json",
                  lambda m: m["rounds"][0].update(job_ids="junk"))
        code, out = helpers.run("metrics.py", "--data", self.data)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    import unittest
    unittest.main()
