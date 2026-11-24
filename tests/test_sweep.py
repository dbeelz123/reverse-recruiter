"""Backlog-sweep cleanup searches (engine/sweep.py): links that bring back a sweep's removed jobs for dismissal."""
import json
import unittest
from urllib.parse import parse_qs, urlparse

import helpers
from sweep import build, company_term, family, select


class Family(unittest.TestCase):
    def test_known_families(self):
        self.assertEqual(family("Senior Product Manager, AI Agents"), "product manager")
        self.assertEqual(family("Technical Product Manager (Remote)"), "technical product manager")
        self.assertEqual(family("Technical Program Manager, AI"), "technical program manager")
        self.assertEqual(family("Senior Product Owner"), "product owner")
        self.assertEqual(family("Head of Product"), "head of product")
        self.assertEqual(family("Cloud Data Center Product Management Director"), "product director")
        self.assertEqual(family("Senior Product Manger - Remote"), "product manager")  # posting typo

    def test_unknown_title_falls_back_to_its_core(self):
        self.assertEqual(family("Senior AI Strategist"), "ai strategist")
        self.assertEqual(family("Builder (Product Led)"), "builder")
        self.assertEqual(family("Senior AI Development Lead"), "ai development")
        self.assertEqual(family("Manager, AI Solutions Owner"), "solutions owner")
        self.assertEqual(family("Senior AI Engineer, Product Engineering"), "ai engineer")
        self.assertEqual(family("Agent Manager - Growth"), "agent manager")
        self.assertEqual(family("Senior Manager, Product / Program Management - COSMC Products"), "product manager")


class CompanyTerm(unittest.TestCase):
    def test_cleanup(self):
        self.assertEqual(company_term("AUI™ (Augmented Intelligence)"), "AUI")
        self.assertEqual(company_term("Reddit, Inc."), "Reddit")
        self.assertEqual(company_term("Naylor Association Solutions (Naylor, LLC)"), "Naylor Association Solutions")
        self.assertEqual(company_term("CompuGroup Medical SE & Co. KGaA"), "CompuGroup Medical")
        self.assertEqual(company_term("Acme"), "Acme")


class Build(unittest.TestCase):
    JOBS = [{"job_id": str(i), "company": c, "title": t} for i, (c, t) in enumerate([
        ("Acme", "Senior Product Manager"), ("Acme", "Product Owner"), ("Beta Co", "Head of Product"),
        ("Gamma, Inc.", "Technical Program Manager"), ("Delta", "Staff Product Manager")], 1)]

    def test_chunks_and_keywords(self):
        s = build(self.JOBS, chunk=2)
        self.assertEqual([x["companies"] for x in s], [["Acme", "Beta Co"], ["Delta", "Gamma"]])
        self.assertEqual(s[0]["keywords"], '(Acme OR "Beta Co") AND ("head of product" OR "product manager" OR "product owner")')
        self.assertEqual(sum(len(x["jobs"]) for x in s), 5)  # every job lands in exactly one search

    def test_everyday_word_names_get_their_own_search(self):
        jobs = self.JOBS + [{"job_id": "9", "company": "Lead", "title": "Senior Product Manager"},
                            {"job_id": "10", "company": "Point", "title": "Product Manager"}]
        s = build(jobs, chunk=12)
        self.assertEqual(s[-1]["companies"], ["Lead", "Point"])
        self.assertTrue(s[-1]["noisy"])
        self.assertFalse(s[0]["noisy"])
        self.assertNotIn("Lead", s[0]["companies"])

    def test_default_url_is_us_remote_past_month_newest_first(self):
        q = parse_qs(urlparse(build(self.JOBS)[0]["url"]).query)
        self.assertEqual(q["location"], ["United States"])
        self.assertEqual(q["sortBy"], ["DD"])
        self.assertEqual(q["f_WT"], ["2"])  # set by the user in the first real run; it cut the noise
        self.assertEqual(q["f_TPR"], ["r2592000"])

    def test_options_drop_the_filters(self):
        q = parse_qs(urlparse(build(self.JOBS, posted="any", remote=False)[0]["url"]).query)
        self.assertNotIn("f_WT", q)
        self.assertNotIn("f_TPR", q)


class Select(unittest.TestCase):
    T = [{"job_id": "1", "removed": "2026-11-23", "reason": "round 9 full review"},
         {"job_id": "2", "removed": "2026-11-23", "reason": "Rejected by employer"},
         {"job_id": "3", "removed": "2026-11-19", "reason": "round 8"}]

    def test_by_date_and_reason(self):
        self.assertEqual([t["job_id"] for t in select(self.T, "2026-11-23")], ["1", "2"])
        self.assertEqual([t["job_id"] for t in select(self.T, "2026-11-23", "round 9")], ["1"])

    def test_by_ids(self):
        self.assertEqual([t["job_id"] for t in select(self.T, ids=[3, "1"])], ["1", "3"])

    def test_ids_add_to_a_date_selection(self):
        self.assertEqual([t["job_id"] for t in select(self.T, "2026-11-23", "round 9", ids=["3"])], ["1", "3"])


class EndToEnd(helpers.SampleCase):
    def test_writes_links_and_archives_the_previous_file(self):
        removed = self.data / "6-system" / "removed.json"
        tombs = json.loads(removed.read_text(encoding="utf-8")) if removed.exists() else []
        tombs += [{"job_id": "9000000001", "company": "Acme", "title": "Senior Product Manager",
                   "removed": "2030-01-02", "reason": "sweep test"},
                  {"job_id": "9000000002", "company": "Beta Co", "title": "Product Owner",
                   "removed": "2030-01-02", "reason": "sweep test"}]
        removed.write_text(json.dumps(tombs), encoding="utf-8")
        old = self.data / "2-reports" / "sweep-links-2000-01-01.md"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text("old", encoding="utf-8")
        out = self.ok("sweep.py", "--data", self.data, "--removed-on", "2030-01-02")
        self.assertIn("2 jobs in 1 searches", out)
        new = [p for p in (self.data / "2-reports").glob("sweep-links-*.md")]
        self.assertEqual(len(new), 1)
        text = new[0].read_text(encoding="utf-8")
        self.assertIn("https://www.linkedin.com/jobs/view/9000000001/", text)
        self.assertTrue((self.data / "2-reports" / "archive" / old.name).exists())

    def test_no_match_stops_cleanly(self):
        code, out = helpers.run("sweep.py", "--data", self.data, "--removed-on", "1999-01-01")
        self.assertNotEqual(code, 0)
        self.assertIn("No matching tombstones", out)


if __name__ == "__main__":
    unittest.main()
