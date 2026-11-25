"""The triage-mode signals (volume, the goal, rules per 100) count search-result cards only. The funnel's
'Job listings processed' also counts saved postings that never showed up as a card; a backlog sweep of direct saves
must not count as triage volume, or it would bring on the question about switching to Keep-up."""
import json

from helpers import SampleCase

import metrics
import modes
from paths import Paths


def edit_json(p, fn):
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    p.write_text(json.dumps(d), encoding="utf-8")


class ModesCountSearchCards(SampleCase):
    def add_direct_saves(self, n, rnd=2):
        ids = [f"91000006{i:02d}" for i in range(n)]
        edit_json(self.data / "6-system/removed.json",
                  lambda t: t.extend({"job_id": j, "company": "Nowhere Card Co", "title": f"Direct Save {j}",
                                      "removed": "2026-11-13", "reason": "test"} for j in ids))

        def snap(m):
            for r in m["rounds"]:
                if r["round"] >= rnd:
                    r["job_ids"] = sorted(set(r["job_ids"]) | set(ids))
        edit_json(self.data / "6-system/metrics.json", snap)

    def test_direct_saves_do_not_count_as_volume_or_thin_out_rules_per_100(self):
        P = Paths(str(self.data))
        before = modes.rows(P)
        listings = metrics.totals(P)["processed"]
        self.add_direct_saves(50)
        self.assertEqual(metrics.totals(P)["processed"], listings + 50)  # the funnel counts them
        after = modes.rows(P)
        self.assertEqual([r["processed"] for r in after], [r["processed"] for r in before])
        self.assertEqual([r["rules_per_100"] for r in after], [r["rules_per_100"] for r in before])
        was, now = modes.verdict(P, before), modes.verdict(P, after)
        self.assertEqual((now["total"], now["recent"], now["volume"]), (was["total"], was["recent"], was["volume"]))

    def test_direct_saves_alone_do_not_meet_the_volume_check(self):
        P = Paths(str(self.data))
        today = __import__("datetime").date.today().isoformat()
        edit_json(self.data / "6-system/metrics.json", lambda m: [r.update(date=today) for r in m["rounds"]])
        edit_json(self.data / "5-criteria/searches.json", lambda d: d.setdefault("mode", {}).pop("goal", None))
        self.add_direct_saves(modes.VOLUME_LISTINGS)
        v = modes.verdict(P, modes.rows(P))
        self.assertGreater(metrics.totals(P)["processed"], modes.VOLUME_LISTINGS)
        self.assertLess(v["recent"], modes.VOLUME_LISTINGS)
        self.assertFalse(v["volume"])

    def test_the_goal_is_reached_by_search_cards_only(self):
        P = Paths(str(self.data))
        cards = sum(r["cards"] for r in metrics.funnel_from_runs(P).values())
        self.assertLess(cards, metrics.totals(P)["processed"])  # the sample has direct saves
        edit_json(self.data / "5-criteria/searches.json",
                  lambda d: d.setdefault("mode", {}).update(goal=metrics.totals(P)["processed"]))
        rs = modes.rows(P)
        self.assertEqual(sum(r["processed"] for r in rs), cards)
        self.assertNotIn("Goal reached", "\n".join(modes.progress_md(P)))
        self.assertIn("search cards", "\n".join(modes.signals_md(P)))


if __name__ == "__main__":
    import unittest
    unittest.main()
