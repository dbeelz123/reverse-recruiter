"""Phone triage (added 2026-11-26): saves made on a phone straight from LinkedIn alerts, with no result cards behind
them. The listings seen and decided are unknown, so the saves are counted apart and left out of the known funnel and
every per-100 number (qualified targets and grade bands included)."""
import json

from helpers import SampleCase

import linkedin_images
import metrics
from paths import Paths


def edit_json(p, fn):
    d = json.loads(p.read_text(encoding="utf-8"))
    r = fn(d)
    p.write_text(json.dumps(d if r is None else r), encoding="utf-8")


class PhoneTriage(SampleCase):
    def P(self):
        return Paths(str(self.data))

    def add_phone_save(self, jid, company, title, tier="B", rnd=2):
        """A current, ranked job saved in round `rnd` by phone triage (listed in a phone run file)."""
        (self.data / "6-system/jobs" / f"{jid}.json").write_text(json.dumps(
            {"job_id": jid, "company": company, "title": title, "review": {"tier": tier}}), encoding="utf-8")

        def snap(m):
            for r in m["rounds"]:
                if r["round"] == rnd:
                    r["job_ids"] = sorted(set(r["job_ids"]) | {jid})
                    r["pdfs_new"] += 1
                    r["ranked_end"] += 1  # recorded with the phone save on the ranked list
        edit_json(self.data / "6-system/metrics.json", snap)
        run = self.data / "6-system/search-runs/phone-run-2026-11-26.json"
        d = json.loads(run.read_text(encoding="utf-8")) if run.exists() else {
            "round": rnd, "triage_type": "phone", "result_count": None, "saved_job_ids": [], "listings": []}
        d["saved_job_ids"].append(jid)
        run.write_text(json.dumps(d), encoding="utf-8")

    def test_a_phone_save_is_counted_apart_not_as_a_listing(self):
        before = metrics.funnel_from_runs(self.P())
        self.add_phone_save("9100000600", "Nowhere Card Co", "Senior Product Manager, Phone Save")
        after = metrics.funnel_from_runs(self.P())
        self.assertEqual(after[2]["processed"], before[2]["processed"])
        self.assertEqual(after[2]["direct"], before[2]["direct"])
        self.assertEqual(after[2]["phone"], 1)
        self.assertEqual(after[2]["phone_ids"], ["9100000600"])

    def test_totals_leave_phone_saves_out_of_every_stage(self):
        before = metrics.totals(self.P())
        self.assertEqual(before["phone_pdfs"], 0)
        self.add_phone_save("9100000601", "Nowhere Card Co", "Senior Product Manager, Phone Save")
        after = metrics.totals(self.P())
        for k in ("processed", "decided", "pdfs", "ranked"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual((after["phone_pdfs"], after["phone_ranked"]), (1, 1))

    def test_a_phone_save_matching_an_earlier_card_is_that_cards_listing(self):
        before = metrics.funnel_from_runs(self.P())
        # Lattice Haul's card is in round 2's run: the listing is known, so the save is not a phone-triage save.
        self.add_phone_save("9100000602", "Lattice Haul", "Senior Product Manager, Freight Payments")
        after = metrics.funnel_from_runs(self.P())
        self.assertEqual(after[2]["phone"], 0)
        self.assertEqual(after[2]["processed"], before[2]["processed"])

    def test_grade_bands_leave_phone_saves_out(self):
        before = linkedin_images.grade_counts(self.P())
        self.add_phone_save("9100000603", "Nowhere Card Co", "Senior Product Manager, Phone Save", tier="A")
        self.assertEqual(linkedin_images.grade_counts(self.P()), before)

    def test_the_round_table_shows_unknown_top_of_funnel(self):
        self.add_phone_save("9100000604", "Nowhere Card Co", "Senior Product Manager, Phone Save")
        t = metrics.table(self.P())
        self.assertIn("unknown (phone triage)", t)
        self.assertIn("Phone triage (listings unknown)", t)
        self.assertIn("Total, known funnel", t)

    def test_without_phone_runs_the_table_is_unchanged(self):
        t = metrics.table(self.P())
        self.assertNotIn("phone", t)
        self.assertIn("| **Total** |", t)


class HeldForCalibration(SampleCase):
    """A review with "held" (a rule suspended until a calibration decides it) stays off the ranked list."""

    def hold(self, jid="9100000009", reason="leadership"):
        def f(d):
            d["jobs"][jid]["held"] = reason
            d["jobs"][jid]["held_findings"] = ["Title is Director (fictional)"]
        edit_json(self.data / "6-system/reviews/round-02.json", f)

    def report(self):
        return sorted((self.data / "2-reports").glob("*-round-02-report.md"))[-1].read_text(encoding="utf-8")

    def test_a_held_job_is_listed_apart_and_not_ranked(self):
        import pipeline
        P = Paths(str(self.data))
        self.assertIn("9100000009", metrics.ranked_ids(P))
        targets = pipeline.build(P)["ranked"]
        self.hold()
        self.assertNotIn("9100000009", metrics.ranked_ids(P))
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        rep = self.report()
        ranked, _, rest = rep.partition("## Held for calibration")
        self.assertTrue(rest, "no held section")
        held_part = rest.split("\n## ")[0]
        self.assertIn("Title is Director (fictional)", held_part)
        table = ranked.split("## Ranked list")[1]
        self.assertNotIn("/9100000009", table)
        self.assertEqual(pipeline.build(P)["ranked"], targets - 1)  # not a qualified target in the outcome funnel



class PhoneRunInModes(SampleCase):
    def test_a_run_without_a_search_name_doesnt_break_the_backlog(self):
        import modes
        (self.data / "6-system/search-runs/phone-run-2026-11-26.json").write_text(json.dumps(
            {"round": 2, "triage_type": "phone", "result_count": None, "saved_job_ids": [], "listings": []}),
            encoding="utf-8")
        modes.backlog(Paths(str(self.data)))  # raised IndexError before 2026-11-27
