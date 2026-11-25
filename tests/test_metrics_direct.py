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
