"""Fixes for the medium findings of the whole-project review of 2026-11-27 (commit ac6a523), numbered as in that
review (19-56): each test reproduces the reported problem and checks the fixed behavior. Hook cases of finding 55
are in test_privacy.py."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from helpers import ENGINE, SampleCase, run

JOB = "9100000006"    # Lumen Cart: remote, tier C, no connection, not in the pipeline
JOB_A = "9100000009"  # Arcadia Fleet: tier A
APPLIED = "9100000001"  # Harborline Logistics: tier A, applied
TODAY = dt.date.today().isoformat()
BS = chr(92)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edit_json(path, change):
    data = read(path)
    data = change(data) or data
    path.write_text(json.dumps(data), encoding="utf-8")


class Base(SampleCase):
    def job(self, jid=JOB):
        return self.data / f"6-system/jobs/{jid}.json"

    def report(self):
        self.ok("build_report.py", "--data", self.data, "--round", "2")
        return next((self.data / "2-reports").glob("*round-02-report.md")).read_text(encoding="utf-8")

    def fails(self, *args, mention=None):
        code, out = run(*args)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        if mention:
            self.assertIn(mention, out)
        return out


# ---- 19-22 ---------------------------------------------------------------------------------------------------------

class ConsoleEncoding(Base):
    """#19: a character outside the Windows code page in printed data doesn't stop a script."""

    def test_rescreen_prints_an_arrow_on_a_legacy_console(self):
        edit_json(self.job(), lambda j: j.update(posting_text="Ship munitions " + chr(0x2192) + " " + chr(0x2705) + " logistics."))
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "REVERSE_RECRUITER_DATA")}
        env.update(PYTHONUTF8="0", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", str(ENGINE / "rescreen.py"), "--data", str(self.data)],
                           capture_output=True, env=env)
        out = r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("current jobs checked", out)


class CompanyGroups(Base):
    """#20: roles are grouped by the whole company name, not its first word."""

    def test_key(self):
        from paths import company_key
        self.assertNotEqual(company_key("The Home Depot"), company_key("The Trade Desk"))
        self.assertNotEqual(company_key("American Airlines"), company_key("American Express"))
        self.assertEqual(company_key("Acme"), company_key("Acme, Inc."))
        self.assertEqual(company_key("Acme Corp"), company_key("ACME Corporation"))
        self.assertEqual(company_key("Northwind Freight (through Summit Staffing)"), company_key("Northwind Freight"))
        self.assertEqual(company_key("The Group"), "group")  # never reduced to nothing

    def test_companies_sharing_a_first_word_are_not_one_group(self):
        for jid, name in ((APPLIED, "First Harbor Logistics"), ("9100000002", "First Solar Freight"),
                          (JOB_A, "First American Supply")):
            edit_json(self.job(jid), lambda j: j.update(company=name))
        self.assertNotIn("Companies with several roles", self.report())
        self.ok("pipeline.py", "queue", "--data", self.data)
        self.assertNotIn("Reserve:", (self.data / "2-reports/apply-queue.md").read_text(encoding="utf-8"))

    def test_three_roles_at_one_company_still_group(self):
        for jid, name in ((APPLIED, "Harbor Co"), ("9100000002", "Harbor Co, Inc."), (JOB_A, "The Harbor Co")):
            edit_json(self.job(jid), lambda j: j.update(company=name))
        self.assertIn("Companies with several roles", self.report())


class LinkEscaping(unittest.TestCase):
    """#21: an ampersand in a link's address is escaped once."""

    def test_query_string(self):
        import prep_pdf
        html = prep_pdf.inline("[search](https://jobs.example.com/search/?keywords=pm&location=IN)")
        self.assertIn('href="https://jobs.example.com/search/?keywords=pm&amp;location=IN"', html)


class Scan(Base):
    def setUp(self):
        super().setUp()
        self.terms = self.tmp / "terms.txt"
        self.terms.write_text("Jordan Avery\nPinewick\n", encoding="utf-8")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def scan(self, *extra, folder=None):
        return run("privacy_scan.py", folder or self.repo, "--terms", self.terms, *extra)

    def line(self, text, name="a.md"):
        (self.repo / name).write_text(text, encoding="utf-8")
        code, out = self.scan()
        (self.repo / name).unlink()
        return code, out


class ScanPatterns(Scan):
    """#22: home-folder paths, profile links and addresses in their common spellings."""

    def test_spellings_that_are_hits(self):
        u, h = "Us" + "ers", "ho" + "me"  # built at runtime so this file doesn't trip the repo's own scan
        for text in ("c:" + BS + u.lower() + BS + "jsmith" + BS + "x", "C:" + BS + u.lower() + BS + "jsmith",
                     "cd /c/" + u + "/jsmith", "cd /" + h + "/jsmith", "C:" + BS * 4 + u + BS * 4 + "jsmith",
                     BS * 2 + "host" + BS + "C$" + BS + u + BS + "jsmith" + BS + "x",
                     "https://www.LinkedIn.com" + "/in/" + "jsmith", "write to x" + "@" + "example.com.evil.org"):
            with self.subTest(text=text):
                self.assertEqual(self.line(text)[0], 1)

    def test_look_alikes_that_are_not(self):
        h = "ho" + "me"
        for text in ("https://docs.example.com/" + h + "/about", "GET /users/42", "ask ok" + "@" + "example.com.",
                     "ask ok" + "@" + "example.org"):
            with self.subTest(text=text):
                code, out = self.line(text)
                self.assertEqual(code, 0, out)


class ScanSkipsAndAllows(Scan):
    """#52-54: nothing outside the scanned folder switches the scan off; the allow file can't blank a file; UTF-32."""

    def test_a_parent_folder_called_git_does_not_skip_the_scan(self):
        folder = self.tmp / ".git" / "checkout"
        folder.mkdir(parents=True)
        (folder / "a.md").write_text("by Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan(folder=folder)[0], 1)

    def test_a_file_called_pycache_is_scanned(self):
        self.assertEqual(self.line("by Jordan Avery", name="__pycache__")[0], 1)

    def test_no_skip_scans_inside_pycache_folders(self):
        (self.repo / "docs/__pycache__").mkdir(parents=True)
        (self.repo / "docs/__pycache__/leak.md").write_text("by Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)
        self.assertEqual(self.scan("--no-skip")[0], 1)

    def test_a_short_allow_phrase_is_ignored(self):
        (self.repo / "a.md").write_text("by Jordan Avery of Pinewick", encoding="utf-8")
        for phrase in ("", "e", "an"):
            with self.subTest(phrase=phrase):
                (self.repo / ".privacy-allow").write_text(f"a.md | {phrase}\n", encoding="utf-8")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("2 hits", out)

    def test_an_image_needs_the_checked_by_eye_phrase(self):
        (self.repo / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        (self.repo / ".privacy-allow").write_text("a.png | whatever\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)
        (self.repo / ".privacy-allow").write_text("a.png | image checked by eye\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)

    def test_the_allow_file_is_checked_for_paths_and_addresses(self):
        (self.repo / ".privacy-allow").write_text("# ask someone" + "@" + "realmail.com\nLICENSE | Jordan Avery\n",
                                                  encoding="utf-8")
        code, out = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("email address", out)

    def test_utf32_text_is_read(self):
        for codec in ("utf-32", "utf-32-le"):  # with a byte-order mark; without one (NUL bytes: unreadable, a hit)
            with self.subTest(codec=codec):
                (self.repo / "a.txt").write_bytes("by Jordan Avery of Pinewick".encode(codec))
                self.assertEqual(self.scan()[0], 1)


class HelperEnvironment(Base):
    """#56: the caller's own private-terms list and data folder don't reach the scripts under test."""

    def test_private_terms_in_the_environment_are_not_passed_on(self):
        terms = self.tmp / "mine.txt"
        terms.write_text("Zanzibar\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PRIVATE_TERMS": str(terms), "REVERSE_RECRUITER_DATA": str(self.tmp)}):
            code, _ = run("privacy_scan.py", self.tmp / "empty", "--strict", "--data", self.tmp / "nowhere")
        self.assertEqual(code, 2)


# ---- 23-29: ingest -------------------------------------------------------------------------------------------------

class ExtractStopsBeforeTheLedger(Base):
    """#23: a damaged, unrelated job record stops the extract before any PDF is marked as processed."""

    def test_the_pdf_is_still_processed_after_the_repair(self):
        import extract
        pdfs = self.data / "1-inbox/job-pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        (pdfs / "new.pdf").write_bytes(b"%PDF-1.4")
        other = self.job("9100000003")
        good = other.read_text(encoding="utf-8")
        other.write_text(good + "garbage", encoding="utf-8")
        ledger = (self.data / "6-system/ledger.json").read_text(encoding="utf-8")
        fake = ("9100000777", None, ("PM", "Acme"), ["Acme", "PM", "About the job", "text"])
        with mock.patch.object(extract, "page_lines", lambda pdf: fake), \
                mock.patch.object(sys, "argv", ["extract.py", "--data", str(self.data)]):
            with self.assertRaises(SystemExit) as e:
                extract.main()
            self.assertIn("9100000003.json", str(e.exception))
            self.assertEqual((self.data / "6-system/ledger.json").read_text(encoding="utf-8"), ledger)
            self.assertFalse(self.job("9100000777").exists())
            other.write_text(good, encoding="utf-8")
            extract.main()
        self.assertTrue(self.job("9100000777").exists())
        self.assertIn("new.pdf", (self.data / "6-system/ledger.json").read_text(encoding="utf-8"))


class PastedResults(Base):
    """#24: cards with area names, a town named like a title word, or a title that reads like 'City, ST' are kept,
    and a location line that belongs to no card is reported."""

    PASTE = "\n".join([
        "Solo line", "Denver, CO (Remote)", "",
        "Senior Product Manager", "Acme", "San Francisco Bay Area", "",
        "Product Lead", "Beta", "Washington DC-Baltimore Area", "",
        "Platform PM", "Gamma", "Leadville, CO (On-site)", "",
        "Chief of Staff, AI", "Stafco", "United States (Remote)", "",
        "Technical PM", "Delta", "Springfield, Illinois Metropolitan Area", ""])

    def ingest(self, text, encoding="utf-8"):
        src = self.tmp / "paste.txt"
        src.write_text(text, encoding=encoding)
        out = self.ok("ingest_results.py", src, self.tmp / "cards.json")
        return read(self.tmp / "cards.json"), out

    def test_every_card_is_found(self):
        cards, out = self.ingest(self.PASTE)
        self.assertEqual([(c["title"], c["location"]) for c in cards], [
            ("Senior Product Manager", "San Francisco Bay Area"), ("Product Lead", "Washington DC-Baltimore Area"),
            ("Platform PM", "Leadville, CO (On-site)"), ("Chief of Staff, AI", "United States (Remote)"),
            ("Technical PM", "Springfield, Illinois Metropolitan Area")])

    def test_a_location_with_no_card_is_reported(self):
        _, out = self.ingest(self.PASTE)
        self.assertIn("CHECK: 1 location-like", out)
        self.assertIn("line 2: Denver, CO (Remote)", out)
        _, out = self.ingest(self.PASTE.split("\n", 3)[3])
        self.assertNotIn("CHECK", out)

    def test_a_byte_order_mark_does_not_stick_to_the_first_title(self):
        cards, _ = self.ingest(self.PASTE.split("\n", 3)[3], encoding="utf-8-sig")
        self.assertEqual(cards[0]["title"], "Senior Product Manager")

    def test_a_missing_file_stops_cleanly(self):
        self.fails("ingest_results.py", self.tmp / "nofile.txt", self.tmp / "cards.json", mention="nofile.txt")


class SeedOrder(Base):
    """#25: seed reads every run file, oldest run first, so it gives what the incremental adds gave."""

    def run_file(self, name, date, company, decision, reason):
        (self.data / "6-system/search-runs" / name).write_text(json.dumps({
            "search": "S9 test", "date": date, "round": 2, "listings": [
                {"id": name[:4], "company": company, "title": "Order Manager", "decision": decision, "reason": reason,
                 "status": "candidate"}]}), encoding="utf-8")

    def entry(self, company):
        return next((e for e in read(self.data / "6-system/triaged.json")["entries"] if e["company"] == company), None)

    def test_the_later_run_wins_whatever_the_file_names(self):
        self.run_file("s2-run-2026-11-10.json", "2026-11-10", "Orderco", "keep", "looks good")
        self.run_file("s1-run-2026-11-22.json", "2026-11-22", "Orderco", "dq", "reposted with 50% travel")
        self.ok("triaged.py", "seed", "--data", self.data)
        self.assertEqual(self.entry("Orderco")["decision"], "dq")

    def test_a_run_file_with_another_name_is_not_dropped(self):
        self.run_file("s3-2026-11-21.json", "2026-11-21", "Namedco", "dq", "defense")
        self.ok("triaged.py", "seed", "--data", self.data)
        self.assertIsNotNone(self.entry("Namedco"))


class CheckIsRecomputed(Base):
    """#26: checking a cards file again recomputes every mark."""

    def test_a_company_taken_off_the_blocklist_is_no_longer_marked(self):
        spec = self.data / "5-criteria/spec.json"
        edit_json(spec, lambda s: s.setdefault("company_blocklist", []).append(
            {"value": "Blockedco", "reason": "test", "status": "confirmed"}))
        cards = self.tmp / "cards.json"
        cards.write_text(json.dumps([{"n": 1, "title": "Product Manager", "company": "Blockedco",
                                      "location": "United States (Remote)", "status": []}]), encoding="utf-8")
        self.ok("triaged.py", "check", cards, "--data", self.data)
        self.assertEqual(read(cards)[0]["triaged"]["action"], "blocklist (confirm)")
        edit_json(spec, lambda s: s.update(company_blocklist=[b for b in s["company_blocklist"]
                                                              if b["value"] != "Blockedco"]))
        self.ok("triaged.py", "check", cards, "--data", self.data)
        self.assertIsNone(read(cards)[0]["triaged"])


class PostingText(unittest.TestCase):
    """#27 and #29: the description isn't cut at its own 'About the company' heading; the header title loses the
    tab's unread count; the job ID comes from the page footer."""

    def test_a_heading_inside_the_description(self):
        from extract import parse_main
        rec = parse_main(["Acme", "PM", "About the job", "About the company", "We build freight software.",
                          "Requirements", "Travel 60% of the time.", "Set alert for similar jobs",
                          "About the company", "Acme", "1,000 employees", "More jobs"])
        self.assertIn("Travel 60%", rec["posting_text"])
        self.assertIn("1,000 employees", rec["company_text"])
        self.assertNotIn("Travel 60%", rec["company_text"])

    def test_without_the_alert_line_the_heading_still_ends_it(self):
        from extract import parse_main
        rec = parse_main(["Acme", "PM", "About the job", "Do the work.", "About the company", "Acme is big.",
                          "More jobs"])
        self.assertEqual(rec["posting_text"], "Do the work.")
        self.assertEqual(rec["company_text"], "Acme is big.")

    def test_tab_count_and_footer_id(self):
        from extract import find_job_id, strip_tab_count
        self.assertEqual(strip_tab_count("(3) Staff Product Manager"), "Staff Product Manager")
        self.assertEqual(strip_tab_count("(99+) Staff PM (Payments)"), "Staff PM (Payments)")
        self.assertEqual(strip_tab_count("Staff PM (Payments)"), "Staff PM (Payments)")
        view = "https://www.linkedin.com" + "/jobs/view/"
        raw = f"See also {view}7777777777/ for the sister role\nmore text\n{view}9200000004/ 1/3\n"
        self.assertEqual(find_job_id(raw), "9200000004")
        self.assertEqual(find_job_id(f"only a link in the text {view}7777777777/ here\n"), "7777777777")
        self.assertIsNone(find_job_id("no link"))


class ExternalRerun(Base):
    """#28: re-ingesting an external job keeps what was given the first time, and --pay isn't lost to a '$3
    billion' in the text."""

    def test_fields_survive_a_rerun(self):
        desc = self.data / "3-applications/x/d.txt"
        desc.parent.mkdir(parents=True)
        desc.write_text("About the role at a $3 billion company. Pay band $120,000 - $150,000.", encoding="utf-8")
        base = ("ingest_external.py", desc, "--id", "ext-x", "--company", "A", "--title", "B", "--data", self.data)
        self.ok(*base, "--location", "Springfield, IL", "--source", "recruiter", "--employment", "Contract",
                "--pay", "$70/hr", "--workplace", "Hybrid")
        self.ok(*base, "--status", "interview")
        rec = read(self.job("ext-x"))
        self.assertEqual((rec["location"], rec["source"], rec["employment_type"], rec["workplace"]),
                         ("Springfield, IL", "recruiter", "Contract", "Hybrid"))
        self.assertEqual(rec["salary_mentions"][0], "$70/hr")
        self.assertTrue(any("120,000" in s for s in rec["salary_mentions"]), rec["salary_mentions"])
        self.assertFalse(any(s.strip() == "$3" for s in rec["salary_mentions"]), rec["salary_mentions"])


# ---- 30-36: removal and the report ---------------------------------------------------------------------------------

class StaleReviewCopy(Base):
    """#30: a job whose review entry is gone from the review files isn't ranked from its record's old copy."""

    def test_it_is_listed_as_not_reviewed(self):
        self.report()  # every record has its copy
        edit_json(self.data / "6-system/reviews/round-02.json", lambda r: r["jobs"].pop(JOB_A) and None)
        text = self.report()
        self.assertIn("Not reviewed yet", text)
        self.assertNotIn("review", read(self.job(JOB_A)))
        self.assertNotIn("Fleet Platform APIs", text.split("## Not reviewed yet")[0].split("## Ranked list")[1])


class RemovalIds(Base):
    """#31 and #32: a mistyped ID changes nothing; a second removal brings the tombstone up to date."""

    def tombs(self):
        return read(self.data / "6-system/removed.json")

    def test_an_unknown_id_is_refused(self):
        before = self.tombs()
        self.fails("remove_job.py", "910000009", "--reason", "typo", "--data", self.data, mention="910000009")
        self.fails("remove_job.py", JOB, "910000009", "--reason", "typo", "--data", self.data)
        self.assertEqual(self.tombs(), before)
        self.assertTrue(self.job().exists())  # nothing in the batch was removed

    def test_a_job_removed_earlier_is_reported_not_refused(self):
        out = self.ok("remove_job.py", "9100000099", "--reason", "again", "--data", self.data)
        self.assertIn("already removed", out)
        self.assertEqual(len([t for t in self.tombs() if t["job_id"] == "9100000099"]), 1)
        self.assertNotIn("again", json.dumps(self.tombs()))

    def test_a_second_removal_updates_the_tombstone(self):
        first = next(t for t in self.tombs() if t["job_id"] == "9100000099")
        rec = read(self.job())
        rec.update(job_id="9100000099", pipeline={"status": "applied", "events": [
            {"date": "2026-11-12", "stage": "applied"}]})
        self.job("9100000099").write_text(json.dumps(rec), encoding="utf-8")
        self.ok("remove_job.py", "9100000099", "--reason", "rejected after applying", "--data", self.data)
        mine = [t for t in self.tombs() if t["job_id"] == "9100000099"]
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["reason"], mine[0]["removed"]), ("rejected after applying", TODAY))
        self.assertEqual(mine[0]["pipeline"]["status"], "applied")
        self.assertEqual(mine[0]["earlier"], [{"removed": first["removed"], "reason": first["reason"]}])


class ExternalConnection(Base):
    """#33: a person can be tied to an external job."""

    def test_ext_ids_load(self):
        import connections
        from paths import Paths
        (self.data / "5-criteria/connections.json").write_text(json.dumps({"people": {"pat-example": {
            "name": "Pat Example", "strength": "plus", "job_ids": ["ext-northwind-freight-sr-pm", 9100000002]}}}),
            encoding="utf-8")
        people = connections.load(Paths(str(self.data)))
        self.assertEqual(people["pat-example"]["job_ids"], ["ext-northwind-freight-sr-pm", "9100000002"])
        found = connections.people_at({"job_id": "ext-northwind-freight-sr-pm"}, {}, people)
        self.assertEqual(found, [("Pat Example", "plus")])


class ReportMissingFields(Base):
    """#34: a hand-written file missing a field the report prints still builds the report."""

    def test_review_without_a_summary(self):
        edit_json(self.data / "6-system/reviews/round-02.json", lambda r: r["jobs"][JOB_A].pop("summary", None) and None)
        self.assertIn("Fleet Platform APIs", self.report())

    def test_record_without_a_url(self):
        edit_json(self.job(JOB_A), lambda j: j.pop("url", None) and None)
        self.assertIn("Fleet Platform APIs", self.report())

    def test_skills_gap_item_without_an_action(self):
        edit_json(self.data / "6-system/skills-gap.json", lambda g: [i.pop("action", None) for i in g["items"]] and None)
        self.report()

    def test_calibration_without_questions_or_a_topic(self):
        cal = self.data / "6-system/calibration/round-02.json"
        cal.parent.mkdir(parents=True, exist_ok=True)
        for content in ({}, {"questions": [{"question": "Is travel fine?"}]}):
            with self.subTest(content=content):
                cal.write_text(json.dumps(content), encoding="utf-8")
                text = self.report()
        self.assertIn("Is travel fine?", text)


class SearchLinks(Base):
    """#35: a search in an unlisted cluster still gets its links; a spec with no radius center, a new data folder
    and a mistyped lookback are handled."""

    def links(self):
        self.ok("searches.py", "--data", self.data)
        return (self.data / "2-reports/search-links.md").read_text(encoding="utf-8")

    def test_an_unlisted_cluster_gets_a_section(self):
        cfg = self.data / "5-criteria/searches.json"
        first = read(cfg)["searches"][0]
        edit_json(cfg, lambda c: c["searches"][0].update(cluster="adjacent", status="active"))
        text = self.links()
        self.assertIn("## Adjacent", text)
        self.assertIn(f"### {first['id']} - ", text)

    def test_no_radius_center_and_no_reports_folder(self):
        edit_json(self.data / "5-criteria/spec.json",
                  lambda s: s["work_arrangement"]["machine_rule"].pop("hybrid_onsite_center", None) and None)
        edit_json(self.data / "5-criteria/searches.json", lambda c: [
            s.update(status="retired") for s in c["searches"] if s.get("where") == "local"] and None)
        shutil.rmtree(self.data / "2-reports")
        self.assertIn("LinkedIn search suggestions", self.links())

    def test_a_mistyped_lookback_names_the_file(self):
        edit_json(self.data / "5-criteria/searches.json",
                  lambda c: c.update(mode=dict(c.get("mode") or {}, mode="catch-up", lookback="2 weeks")))
        self.fails("searches.py", "--data", self.data, mention="searches.json")


class Leads(unittest.TestCase):
    """#36: a saved company's first word hides a lead only as a whole word."""

    def test_substring_does_not_hide_a_lead(self):
        from build_report import lead_is_saved
        saved = [{"title": "Tracking API", "company": "Age of Supply"}]
        self.assertFalse(lead_is_saved("Senior Product Manager, Tracking API", "Ferrous Freight Tech", saved))
        self.assertTrue(lead_is_saved("Tracking API", "Age of Supply", saved))
        self.assertTrue(lead_is_saved("Senior Product Manager, Tracking API", "Age Supply Holdings", saved))
        saved = [{"title": "Product Manager", "company": "The Harbor Co"}]
        self.assertFalse(lead_is_saved("Senior Product Manager", "Join the best team", saved))
        self.assertTrue(lead_is_saved("Senior Product Manager", "Harbor", saved))


# ---- 37-42: funnel, modes, images ----------------------------------------------------------------------------------

class Metrics(Base):
    metrics = property(lambda self: self.data / "6-system/metrics.json")

    def test_recording_a_round_again_keeps_its_date_and_mode(self):
        """#37"""
        edit_json(self.metrics, lambda m: m["rounds"][-1].update(date="2026-10-01", mode="keep-up"))
        self.ok("metrics.py", "--round", "2", "--data", self.data)
        last = read(self.metrics)["rounds"][-1]
        self.assertEqual((last["date"], last["mode"]), ("2026-10-01", "keep-up"))

    def test_a_first_recording_is_dated_today(self):
        self.metrics.write_text('{"rounds": []}', encoding="utf-8")
        self.ok("metrics.py", "--round", "1", "--data", self.data)
        self.assertEqual(read(self.metrics)["rounds"][0]["date"], TODAY)

    def test_at_must_be_a_time(self):
        """#38"""
        before = self.metrics.read_text(encoding="utf-8")
        self.fails("metrics.py", "--round", "2", "--event", "triage", "--at", "yesterday 3pm", "--data", self.data,
                   mention="--at")
        self.assertEqual(self.metrics.read_text(encoding="utf-8"), before)

    def test_an_offset_time_is_stored_as_local_and_compared(self):
        import metrics
        self.ok("metrics.py", "--round", "2", "--event", "triage", "--at", "2026-11-27T10:00:00+00:00", "--data", self.data)
        stored = [e["t"] for e in read(self.metrics)["rounds"][-1]["events"] if e["stage"] == "triage"][-1]
        self.assertIsNone(dt.datetime.fromisoformat(stored).tzinfo)
        mins = metrics.stage_minutes({"events": [{"t": "2026-11-27T10:00:00+00:00", "stage": "triage"},
                                                 {"t": "2026-11-27T10:20:00+00:00", "stage": "triage"},
                                                 {"t": "2026-11-27T10:30:00", "stage": "review"},
                                                 {"t": "2026-11-27T10:40:00", "stage": "review"}]})
        self.assertEqual((mins["triage"], mins["review"]), (20, 10))

    def test_no_changelog_yet(self):
        """#39"""
        (self.data / "5-criteria/changelog.md").unlink()
        self.ok("modes.py", "--data", self.data, "signals")
        self.ok("modes.py", "--data", self.data, "progress")

    def test_damaged_files_are_named(self):
        """#40"""
        run_f = self.data / "6-system/search-runs/s1-run-2026-11-13.json"
        good = run_f.read_text(encoding="utf-8")
        for content in ("[]", json.dumps(dict(json.loads(good), round="2")),
                        json.dumps(dict(json.loads(good), listings=["x"])),
                        json.dumps(dict(json.loads(good), unrecorded_cards="38"))):
            with self.subTest(content=content[:30]):
                run_f.write_text(content, encoding="utf-8")
                for args in (("metrics.py",), ("modes.py", "signals"), ("precision.py",)):
                    self.fails(args[0], "--data", self.data, *args[1:], mention="s1-run-2026-11-13.json")
        run_f.write_text(good, encoding="utf-8")
        for content in ("[]", '{"rounds": [{"date": "2026-11-10"}]}'):
            with self.subTest(content=content):
                self.metrics.write_text(content, encoding="utf-8")
                self.fails("metrics.py", "--data", self.data, mention="metrics.json")

    def test_project_file_that_is_not_an_object(self):
        (self.data / "6-system/linkedin-project.json").write_text("[]", encoding="utf-8")
        self.fails("linkedin_project.py", "check", "--data", self.data, mention="linkedin-project.json")

    def test_the_keep_column_says_what_it_counts(self):
        """#41"""
        self.assertIn("Keeps per 100 recorded cards", self.ok("modes.py", "--data", self.data, "signals"))


class Images(Base):
    """#42: a raw-count render leaves the per-100 pair alone, and no round but the latest can be asked for."""

    def test_kinds_are_archived_apart(self):
        import linkedin_images as li

        def render(browser, html, out_png, tmp):
            out_png.write_text("png", encoding="utf-8")
        args = ["--data", str(self.data)]
        with mock.patch.object(li, "BROWSERS", [sys.executable]), mock.patch.object(li, "render", render):
            live = li.main(args)["files"]
            raw = li.main(args + ["--raw"])["files"]
            for f in live + raw:
                self.assertTrue((self.data / f).exists(), f)
            with self.assertRaises(SystemExit) as e:
                li.main(args + ["--round", "1"])
            self.assertIn("latest", str(e.exception))
            li.main(args + ["--round", "2"])


# ---- 43-51: applications and interviews ----------------------------------------------------------------------------

class OpenChecks(Base):
    """#43 and #44: dates of things that happened can't be in the future, a stored future date can be corrected, and
    a check that isn't stored isn't reported as stored."""
    FUTURE = (dt.date.today() + dt.timedelta(days=30)).isoformat()

    def check(self, jid="9100000002"):
        return read(self.job(jid)).get("open_check") or {}

    def test_future_dates_are_refused(self):
        self.fails("staleness.py", "--data", self.data, "confirm", "9100000002", "open", "--date", self.FUTURE)
        self.fails("pipeline.py", "record", JOB, "applied", "--date", self.FUTURE, "--data", self.data)
        self.assertIsNone(read(self.job()).get("pipeline"))

    def test_a_stored_future_check_is_replaced(self):
        edit_json(self.job("9100000002"), lambda j: j.update(open_check={
            "date": self.FUTURE, "result": "open", "source": "confirmed by hand"}))
        self.ok("staleness.py", "--data", self.data, "confirm", "9100000002", "open")
        self.assertEqual(self.check()["date"], TODAY)

    def test_an_older_confirmation_is_refused_out_loud(self):
        self.ok("staleness.py", "--data", self.data, "confirm", "9100000002", "open")
        out = self.fails("staleness.py", "--data", self.data, "confirm", "9100000002", "closed", "--date", "2026-11-01")
        self.assertIn("newer check", out)
        self.assertEqual(self.check()["result"], "open")

    def test_an_impossible_date_in_a_file_name_is_refused(self):
        src = self.data / "1-inbox/tracked-jobs/tracked-2026-11-14.txt"
        bad = self.tmp / "tracked-2026-11-31.txt"
        shutil.copy(src, bad)
        before = {f.name: f.read_text(encoding="utf-8") for f in (self.data / "6-system/jobs").glob("*.json")}
        self.fails("staleness.py", "--data", self.data, "tracker", bad, mention="tracked-2026-11-31.txt")
        after = {f.name: f.read_text(encoding="utf-8") for f in (self.data / "6-system/jobs").glob("*.json")}
        self.assertEqual(before, after)

    def test_each_paste_uses_its_own_date(self):
        src = self.data / "1-inbox/tracked-jobs/tracked-2026-11-14.txt"
        later = self.tmp / "tracked-2026-11-20.txt"
        shutil.copy(src, later)
        self.ok("staleness.py", "--data", self.data, "tracker", src, later)
        dates = {read(f).get("open_check", {}).get("date") for f in (self.data / "6-system/jobs").glob("*.json")
                 if "tracker" in str(read(f).get("open_check", {}).get("source", "")).lower()
                 or "paste" in str(read(f).get("open_check", {}).get("source", "")).lower()}
        self.assertEqual(dates, {"2026-11-20"})


class InterviewRounds(Base):
    """#45-47."""
    J = "9100000002"

    def iv(self, *args):
        return self.ok("interviews.py", "--data", self.data, *args)

    def rec(self):
        return read(self.job(self.J))

    def debrief_file(self, content):
        f = self.tmp / "debrief.json"
        f.write_text(json.dumps(content), encoding="utf-8")
        return f

    def test_postponing_a_round_clears_its_date(self):
        self.iv("schedule", self.J, "--round", "1", "--date", "2026-12-10")
        out = self.iv("schedule", self.J, "--round", "1", "--date", "unknown")
        rec = self.rec()
        self.assertIsNone(rec["interviews"][0]["date"])
        self.assertEqual(rec["pipeline"]["stage"], "round 1")
        self.assertNotIn("on unknown", json.dumps(rec))
        self.assertIn("date unknown", out)

    def test_a_first_schedule_without_a_date_reads_cleanly(self):
        self.iv("schedule", self.J, "--round", "1", "--date", "unknown")
        self.assertNotIn("unknown", json.dumps(self.rec()["pipeline"]))

    def test_debriefing_an_unscheduled_round_moves_the_application(self):
        self.ok("pipeline.py", "record", self.J, "applied", "--date", "2026-11-10", "--data", self.data)
        self.iv("debrief", self.J, "--round", "1", "--file", self.debrief_file({"how": "fine"}), "--date", "2026-11-20")
        rec = self.rec()
        self.assertEqual(rec["pipeline"]["status"], "interview")
        self.assertEqual(rec["pipeline"]["stage"], "round 1 done 2026-11-20")
        self.assertEqual(rec["pipeline"]["events"][-1]["stage"], "interview")

    def test_a_debrief_without_any_date_has_no_none_in_the_stage(self):
        self.iv("debrief", self.J, "--round", "1", "--file", self.debrief_file({"how": "fine"}))
        self.assertEqual(self.rec()["pipeline"]["stage"], "round 1 done")

    def test_a_debrief_date_that_differs_is_applied(self):
        self.iv("schedule", self.J, "--round", "1", "--date", "2026-12-10")
        out = self.iv("debrief", self.J, "--round", "1", "--date", "2026-11-26",
                      "--file", self.debrief_file({"thank_you_to": ["the panel"]}))
        rec = self.rec()
        self.assertEqual(rec["interviews"][0]["date"], "2026-11-26")
        self.assertEqual(rec["interviews"][0]["thank_you"]["due"], "2026-11-27")
        self.assertIn("2026-12-10", out)

    def test_one_name_written_as_text_is_one_name(self):
        self.iv("debrief", self.J, "--round", "1", "--date", "2026-11-20",
                "--file", self.debrief_file({"asked": "Why us?", "thank_you_to": "Jane Doe"}))
        iv = self.rec()["interviews"][0]
        self.assertEqual(iv["thank_you"]["to"], ["Jane Doe"])
        self.assertEqual(iv["debrief"]["asked"], ["Why us?"])

    def test_a_debrief_file_of_the_wrong_shape_stops_cleanly(self):
        for content in (["how"], {"asked": [1, 2]}):
            with self.subTest(content=content):
                self.fails("interviews.py", "--data", self.data, "debrief", self.J, "--round", "1",
                           "--file", self.debrief_file(content))
        self.assertNotIn("interviews", self.rec())


class Queue(Base):
    """#48 and #49."""

    def test_closed_and_unconfirmed_come_before_a_stored_next_step(self):
        from pipeline import next_step
        j = {"company": "Acme", "pipeline": {"next": "Finish the Workday application", "events": []}}
        self.assertEqual(next_step(j, None, False, "closed"), "Closed: removal prompt")
        self.assertEqual(next_step(j, None, False, "fresh"), "Finish the Workday application")
        for code in ("check", "old"):
            self.assertEqual(next_step(j, None, False, code),
                             "Confirm the posting is open; then: Finish the Workday application")

    def test_an_applied_job_stays_in_progress_when_its_tier_changes(self):
        before = self.ok("pipeline.py", "queue", "--data", self.data)
        company = read(self.job(APPLIED))["company"]
        for tier, extra in (("X", {}), ("?", {}), ("A", {"held": "leadership"})):
            with self.subTest(tier=tier, extra=extra):
                edit_json(self.job(APPLIED), lambda j: j["review"].update(tier=tier, **extra))
                after = self.ok("pipeline.py", "queue", "--data", self.data)
                applied = lambda out: next(p for p in out.split(" -> ") if p.startswith("Applied "))
                self.assertEqual(applied(before), applied(after))
                text = (self.data / "2-reports/apply-queue.md").read_text(encoding="utf-8")
                self.assertIn(company, text.split("## In progress")[1].split("## Apply next")[0])


class TailorResume(Base):
    """#50: an edit that fits several runs, or only text another edit inserted, is refused."""

    def docx(self, *runs):
        body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in runs)
        src = self.tmp / "resume.docx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="urn:w"><w:body>'
                       + body + "</w:body></w:document>")
        return src

    def tailor(self, src, edits):
        f = self.tmp / "edits.json"
        f.write_text(json.dumps(edits), encoding="utf-8")
        dst = self.tmp / "out.docx"
        if dst.exists():
            dst.unlink()
        return run("tailor_resume.py", src, dst, f), dst

    def test_a_find_in_two_runs_is_refused(self):
        src = self.docx("2019 - 2021 Acme", "Grew revenue 20% in 2019")
        (code, out), dst = self.tailor(src, [["2019", "*", "2019", "2020", "*"]])
        self.assertNotEqual(code, 0, out)
        self.assertIn("2 runs", out)
        self.assertFalse(dst.exists())
        (code, out), dst = self.tailor(src, [["Grew revenue", "*", "Grew", "Raised", "*"]])
        self.assertEqual(code, 0, out)

    def test_inserted_text_is_not_edited_again(self):
        src = self.docx("Led the Acme launch", "Second line")
        (code, out), dst = self.tailor(src, [["Acme", "*", "Acme", "Acme migration strategy", "*"],
                                             ["migration", "*", "migration", "move", "*"]])
        self.assertNotEqual(code, 0, out)
        self.assertIn("Not found", out)

    def test_an_empty_edit_list_is_refused(self):
        (code, out), dst = self.tailor(self.docx("One line"), [])
        self.assertNotEqual(code, 0, out)
        self.assertFalse(dst.exists())


class PacketNames(unittest.TestCase):
    """#51: two packets with one name stop the build."""

    def test_duplicates_stop(self):
        import prep_pdf
        with tempfile.TemporaryDirectory() as td:
            kit = Path(td)
            (kit / "notes.md").write_text("# Notes\n\nText.\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as e:
                prep_pdf.packets(kit, {"packets": [{"source": "notes.md"}, {"source": "notes.md", "title": "Again"}]})
            self.assertIn("notes", str(e.exception))
            self.assertEqual(len(prep_pdf.packets(kit, {"packets": [{"source": "notes.md"},
                                                                    {"source": "notes.md", "name": "again"}]})), 2)


if __name__ == "__main__":
    unittest.main()
