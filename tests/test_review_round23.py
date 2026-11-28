"""From the review of commit 98dfe2e (2026-11-28, areas 9 and 10: tests; docs against code): one job followed
through every script from a pasted search card to its tombstone, and the round steps checked to say how stage
timings are collected."""
import contextlib
import datetime as dt
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO, SampleCase, run

TODAY = dt.date.today().isoformat()
CO, TITLE, JID = "Harbor Loop", "Senior Product Manager, Dock Scheduling", "9100000321"
PDF = f"1-inbox/job-pdfs/{TITLE} _ {CO} _ LinkedIn.pdf"
PASTE = f"{TITLE}\n{CO}\nUnited States (Remote)\n$150K/yr - $180K/yr\nPosted 2 days ago\n"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class SavedJobLifecycle(SampleCase):
    """#2: the hand-offs between scripts, for one job: pasted card -> triage card -> run row -> saved PDF -> job
    record -> link back to the run row -> review -> funnel -> ranked report -> apply queue -> removal -> tombstone ->
    the same card skipped at the next triage -> the same PDF flagged if saved again. Each script has its own tests;
    this one fails when one script stops producing what the next one reads."""

    def cards(self):
        paste, cards = self.data / "1-inbox/search-results/s9-paste.txt", self.tmp / "cards.json"
        paste.parent.mkdir(parents=True, exist_ok=True)
        paste.write_text(PASTE, encoding="utf-8")
        self.ok("ingest_results.py", paste, cards)
        out = self.ok("triaged.py", "check", cards, "--data", self.data)
        return read(cards), out

    def extract(self):
        """extract.py on the saved PDF, with the PDF's text supplied (sample data holds no real postings)."""
        import extract
        (self.data / PDF).parent.mkdir(parents=True, exist_ok=True)
        (self.data / PDF).write_bytes(b"%PDF-1.4")
        page = (JID, None, (TITLE, CO), [CO, TITLE, "United States (Remote)", "About the job",
                                         "Own dock scheduling for carriers and shippers."])
        out = io.StringIO()
        with mock.patch.object(extract, "page_lines", lambda pdf: page), \
                mock.patch.object(sys, "argv", ["extract.py", "--data", str(self.data)]), \
                contextlib.redirect_stdout(out):
            extract.main()
        return out.getvalue()

    def totals(self):
        import metrics
        from paths import Paths
        return metrics.totals(Paths(str(self.data)))

    def test_one_job_from_search_card_to_tombstone(self):
        d = ("--data", self.data)
        before = self.totals()

        # 1. Pasted search results -> one triage card, new to the project.
        cards, out = self.cards()
        self.assertEqual([(c["title"], c["company"], c["workplace"]) for c in cards], [(TITLE, CO, "Remote")])
        self.assertIsNone(cards[0]["triaged"])
        self.assertIn("1 new", out)

        # 2. The user keeps it: a run row for round 3, added to the decided listings.
        run_file = self.data / f"6-system/search-runs/s9-run-{TODAY}.json"
        run_file.write_text(json.dumps({
            "round": 3, "search": "S9", "date": TODAY, "result_count": 1, "listings": [{
                "id": "S9-001", "title": TITLE, "company": CO, "location": cards[0]["location"],
                "workplace": cards[0]["workplace"], "status": "candidate", "batch": 1, "find": cards[0]["find"],
                "likely": "likely keep", "decision": "keep", "decided": TODAY, "reason": ""}]}), encoding="utf-8")
        self.ok("triaged.py", "add", run_file, *d)
        keeps = self.ok("triaged.py", "keeps", run_file, *d)
        self.assertIn(f"{CO}: {TITLE}", keeps)

        # 3. The saved PDF -> a job record, tied to the PDF in the ledger.
        out = self.extract()
        self.assertIn(JID, out)
        record = self.data / f"6-system/jobs/{JID}.json"
        job = read(record)
        self.assertEqual((job["title"], job["company"], job["source_files"]), (TITLE, CO, [PDF]))
        self.assertEqual(read(self.data / "6-system/ledger.json")[PDF]["job_id"], JID)

        # 4. The save is linked back to its run row by company and title.
        self.ok("triaged.py", "match-saved", run_file, *d)
        self.assertEqual(read(run_file)["listings"][0]["job_id"], JID)

        # 5. The review, then the funnel: one more listing, one more decision, one more saved job, one more target.
        (self.data / "6-system/reviews/round-03.json").write_text(json.dumps({"round": 3, "date": TODAY, "jobs": {JID: {
            "fit": 72, "summary": "Dock scheduling for carriers; close to the candidate's logistics work.",
            "positives": ["Carrier-facing product"], "caveats": [], "gaps": [], "adjustments":
            [{"reason": "core domain", "points": 6}], "network_bonus": 0, "dealbreakers": [], "eligibility": [],
            "tier": "B", "search": "S9"}}}), encoding="utf-8")
        self.ok("metrics.py", "--round", "3", *d)
        after = self.totals()
        self.assertEqual(after["round"], 3)
        for stage in ("processed", "decided", "pdfs", "ranked"):
            self.assertEqual(after[stage], before[stage] + 1, stage)
        self.ok("rescreen.py", *d)

        # 6. The report ranks it with the score the review and its adjustment add up to.
        self.ok("build_report.py", "--round", "3", *d)
        report = self.data / f"2-reports/{TODAY}-round-03-report.md"
        self.assertIn(f"#### {CO} - {TITLE} (78)", report.read_text(encoding="utf-8"))
        self.assertEqual((read(record)["review"]["total"], read(record)["review"]["tier"]), (78, "B"))
        self.assertFalse((self.data / "2-reports/2026-11-14-round-02-report.md").exists())  # archived

        # 7. The apply queue lists it; the gate asks for an open check first.
        self.ok("pipeline.py", "queue", *d)
        self.assertIn(f"{CO}: {TITLE}", (self.data / "2-reports/apply-queue.md").read_text(encoding="utf-8"))
        code, out = run("staleness.py", *d, "gate", JID)
        self.assertEqual(code, 1, out)
        self.assertIn("CHECK FIRST", out)

        # 8. Removal: record, PDF, ledger entry and review entry go; the tombstone keeps the reason.
        out = self.ok("remove_job.py", JID, "--reason", "posting closed", *d)
        self.assertFalse(record.exists())
        self.assertFalse((self.data / PDF).exists())
        self.assertNotIn(PDF, read(self.data / "6-system/ledger.json"))
        self.assertNotIn(JID, read(self.data / "6-system/reviews/round-03.json")["jobs"])
        tomb = [t for t in read(self.data / "6-system/removed.json") if t["job_id"] == JID]
        self.assertEqual([(t["company"], t["title"], t["reason"]) for t in tomb], [(CO, TITLE, "posting closed")])

        # 9. The funnel still counts the job as saved and read; the rebuilt report no longer ranks it.
        self.assertEqual(self.totals()["pdfs"], after["pdfs"])
        self.ok("build_report.py", "--round", "3", *d)
        self.assertNotIn(f"#### {CO} - {TITLE}", report.read_text(encoding="utf-8"))

        # 10. The same card at the next triage is skipped, with the removal as the reason.
        cards, _ = self.cards()
        self.assertEqual(cards[0]["triaged"]["action"], "skip")
        self.assertIn("posting closed", cards[0]["triaged"]["reason"])

        # 11. Saved again by mistake: extract reads it and flags the earlier removal.
        out = self.extract()
        self.assertIn("PREVIOUSLY REMOVED", out)
        self.assertIn("posting closed", out)


class TimingDocs(unittest.TestCase):
    """#1: the round steps say how stage timings are collected; `metrics.py --round N` alone records no stage times
    beyond what file times give."""

    def test_how_it_works_documents_timing_events(self):
        import metrics
        text = (REPO / "docs/how-it-works.md").read_text(encoding="utf-8")
        self.assertIn("metrics.py --round N --event <stage>", text)
        for stage in metrics.STAGES:
            self.assertIn(f"`{stage}`", text, stage)
        self.assertIn(str(metrics.BREAK_MIN), text.split("--event <stage>")[1][:900])


if __name__ == "__main__":
    unittest.main()
