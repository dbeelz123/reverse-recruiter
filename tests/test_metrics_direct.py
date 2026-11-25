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

    def backfill_round_1(self, direct_1, direct_2):
        """Round 1 keeps no job IDs (backfilled); both rounds record how many of their saves were direct."""
        def backfill(m):
            for r, direct in zip(m["rounds"], (direct_1, direct_2)):
                r["pdfs_from_triage"] = r["pdfs_new"] - direct
            m["rounds"][0].pop("job_ids")
        edit_json(self.data / "6-system/metrics.json", backfill)

    def test_too_few_early_saves_are_shared_by_recorded_direct_counts(self):
        # Four early direct saves are left after deduplication, but the rounds recorded 6 and 2: share them 3 and 1
        # instead of handing all four to the earliest round.
        self.add_job("9100000520", "Nowhere Card Co", "Staff Product Manager, Early One", 2)
        self.add_job("9100000521", "Nowhere Card Co", "Staff Product Manager, Early Two", 2)
        self.backfill_round_1(6, 2)
        f = self.funnel()
        self.assertEqual((f[1]["direct"], f[2]["direct"]), (3, 1))
        self.assertEqual(f[1]["processed"], f[1]["cards"] + 3)

    def test_enough_early_saves_give_each_backfilled_round_its_recorded_count(self):
        self.add_job("9100000522", "Nowhere Card Co", "Staff Product Manager, Early One", 2)
        self.add_job("9100000523", "Nowhere Card Co", "Staff Product Manager, Early Two", 2)
        self.backfill_round_1(1, 1)
        f = self.funnel()
        self.assertEqual((f[1]["direct"], f[2]["direct"]), (1, 3))  # the rest stays with the first snapshot round

    def test_sharing_early_saves_keeps_the_total(self):
        # Recorded direct counts: round 1 = 5, round 3 = 2, round 4 (the first snapshot round) = 3; round 2 has no
        # split. Expected hand-outs to rounds 1 and 3 for n = 0..11 (largest remainders, earlier round on a tie);
        # round 4 keeps the rest.
        rounds = [{"round": 1, "pdfs_new": 5, "pdfs_from_triage": 0}, {"round": 2, "pdfs_new": 4},
                  {"round": 3, "pdfs_new": 3, "pdfs_from_triage": 1},
                  {"round": 4, "pdfs_new": 9, "pdfs_from_triage": 6}]
        want = {0: (0, 0), 1: (1, 0), 2: (1, 0), 3: (1, 1), 4: (2, 1), 5: (3, 1), 6: (3, 1), 7: (4, 1), 8: (4, 2),
                9: (4, 2), 10: (5, 2), 11: (5, 2)}
        for n, (r1, r3) in want.items():
            with self.subTest(n=n):
                share = metrics.share_early(n, rounds, 4)
                self.assertEqual((share.get(1, 0), share.get(3, 0)), (r1, r3))
                self.assertEqual(set(share) - {1, 3}, set())  # none for round 2 (no split) or round 4 (keeps its own)
        # An equal split with one save over: the earlier round takes it.
        tie = [{"round": 1, "pdfs_new": 2, "pdfs_from_triage": 0}, {"round": 2, "pdfs_new": 2, "pdfs_from_triage": 0},
               {"round": 3, "pdfs_new": 0, "pdfs_from_triage": 0}]
        self.assertEqual(metrics.share_early(3, tie, 3), {1: 2, 2: 1})

    def metrics_rounds(self):
        return json.loads((self.data / "6-system/metrics.json").read_text(encoding="utf-8"))["rounds"]

    def test_recording_an_earlier_round_again_changes_nothing_when_the_later_round_has_no_snapshot(self):
        edit_json(self.data / "6-system/metrics.json", lambda m: m["rounds"][1].pop("job_ids") and None)
        before, funnel = self.metrics_rounds(), self.funnel()
        self.assertIn("left as it is", self.ok("metrics.py", "--data", self.data, "--round", "1"))
        self.assertEqual(self.metrics_rounds(), before)
        self.assertEqual(self.funnel(), funnel)

    def test_a_round_recorded_late_counts_no_old_job_as_new(self):
        # Round 2's snapshot lost IDs that round 1 kept, and round 4 is recorded; then round 3 is recorded late.
        # Checked with the rounds listed in order and out of order (a hand-edited file).
        original = (self.data / "6-system/metrics.json").read_text(encoding="utf-8")
        for order in ("in order", "out of order"):
            with self.subTest(order):
                (self.data / "6-system/metrics.json").write_text(original, encoding="utf-8")

                def setup(m):
                    r1, r2 = m["rounds"]
                    full = r2["job_ids"]
                    r2["job_ids"] = full[:5]
                    r4 = {"round": 4, "date": "2026-11-20", "pdfs_new": 0, "ranked_end": 8, "job_ids": full}
                    m["rounds"] = [r1, r2, r4] if order == "in order" else [r4, r2, r1]
                edit_json(self.data / "6-system/metrics.json", setup)
                counted = lambda: {r: v for r, v in self.funnel().items() if v["processed"]}  # round 3 adds nothing
                before = counted()
                self.ok("metrics.py", "--data", self.data, "--round", "3")
                r3 = next(r for r in self.metrics_rounds() if r["round"] == 3)
                self.assertEqual(r3["pdfs_new"], 0)
                self.assertEqual([e for e in r3.get("events", []) if e["stage"] == "export"], [])
                self.assertEqual(counted(), before)

    def test_saves_before_any_recorded_round_wait_for_round_1(self):
        edit_json(self.data / "6-system/metrics.json", lambda m: m.update(rounds=[]))
        f = self.funnel()
        self.assertNotIn(0, f)
        self.assertEqual(f[1]["cards"], 44)  # round 1's cards are counted before the waiting saves
        metrics.add_event(Paths(str(self.data)), 2, "capture")  # round 2 in progress, still nothing recorded
        self.assertNotIn(0, self.funnel())

    def test_an_empty_snapshot_is_a_recorded_round_with_no_saves_yet(self):
        self.assertEqual(metrics.snapshot({"job_ids": []}), set())
        self.assertIsNone(metrics.snapshot({"job_ids": [1, 2]}))
        self.assertIsNone(metrics.snapshot({"job_ids": "junk"}))

    def test_two_card_rows_with_one_job_id_count_once(self):
        # The same saved posting on two rows under different titles (one cut short): one listing.
        self.add_job("9100000530", "Lattice Haul", "Senior Product Manager, Freight Payments", 2)
        before = self.funnel()

        def second_row(d):
            card = next(x for x in d["listings"] if x["company"] == "Lattice Haul")
            card["job_id"] = "9100000530"
            row = dict(card)
            row.update(id="S1-900", title="Senior Product Manager", job_id="9100000530", decision=None)
            d["listings"].append(row)
        edit_json(self.data / "6-system/search-runs/s1-run-2026-11-13.json", second_row)
        self.assertEqual(self.funnel()[2]["processed"], before[2]["processed"])

    def test_a_job_id_on_a_duplicate_row_does_not_hide_a_direct_save(self):
        # A skipped row (a same-day duplicate) carries the ID; no valid card stands for the posting: the save counts.
        def dup_row(d):
            d["listings"].append({"id": "S1-901", "company": "Nowhere Card Co", "status": "duplicate",
                                  "title": "Lead Product Manager, Skipped", "decision": None, "job_id": "9100000531"})
        edit_json(self.data / "6-system/search-runs/s1-run-2026-11-13.json", dup_row)
        before = self.funnel()
        self.add_job("9100000531", "Nowhere Card Co", "Lead Product Manager, Skipped", 2)
        self.assertEqual(self.funnel()[2]["direct"], before[2]["direct"] + 1)

    def test_recording_an_earlier_round_again_changes_nothing(self):
        metrics_file = self.data / "6-system/metrics.json"
        before, funnel = json.loads(metrics_file.read_text(encoding="utf-8")), self.funnel()
        out = self.ok("metrics.py", "--data", self.data, "--round", "1")
        self.assertIn("left as it is", out)
        self.assertEqual(json.loads(metrics_file.read_text(encoding="utf-8")), before)
        self.assertEqual(self.funnel(), funnel)

    def test_a_round_first_recorded_after_a_later_one_takes_no_saves_from_it(self):
        edit_json(self.data / "6-system/metrics.json",
                  lambda m: m.update(rounds=[{"round": 1, "ranked_end": None}, m["rounds"][1]]))
        before = self.funnel()
        self.ok("metrics.py", "--data", self.data, "--round", "1")
        self.assertEqual(self.funnel(), before)

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
