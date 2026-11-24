"""Blocklist matching (engine/paths.py blocked_by) and the triage confirm step for blocklisted companies
(engine/triaged.py check)."""
import json
import unittest

from helpers import SampleCase
from paths import blocked_by

ENTRIES = [
    {"value": "SAIC", "reason": "r1", "status": "confirmed"},
    {"value": "Arity", "reason": "r2", "status": "confirmed"},
    {"value": "RTX (Raytheon, Pratt & Whitney)", "aliases": ["Raytheon", "Pratt & Whitney"], "reason": "r3",
     "status": "confirmed"},
    {"value": "Via", "match": "exact", "reason": "r4", "status": "confirmed"},
    {"value": "Companies owned by someone (e.g. Tesla)", "aliases": ["Tesla"], "reason": "r5", "status": "confirmed"},
    {"value": "Proposed Co", "reason": "r6", "status": "proposed"},
]


class BlockedBy(unittest.TestCase):
    def hit(self, company, **kw):
        b = blocked_by(company, ENTRIES, **kw)
        return b["reason"] if b else None

    def test_whole_words_only(self):
        self.assertEqual(self.hit("SAIC"), "r1")
        self.assertIsNone(self.hit("Mosaic"))
        self.assertIsNone(self.hit("Clarity"))
        self.assertEqual(self.hit("Arity, an Allstate company"), "r2")

    def test_aliases_and_case(self):
        self.assertEqual(self.hit("raytheon technologies"), "r3")
        self.assertEqual(self.hit("Pratt & Whitney"), "r3")
        self.assertEqual(self.hit("RTX"), "r3")

    def test_exact_entries_match_only_the_whole_name(self):
        self.assertEqual(self.hit("Via"), "r4")
        self.assertIsNone(self.hit("Via Transportation, Inc."))

    def test_category_entries_match_through_aliases_only(self):
        self.assertEqual(self.hit("Tesla"), "r5")
        self.assertIsNone(self.hit("Companies owned by someone"))

    def test_unit_beats_case_by_case_parent(self):
        entries = [{"value": "Acme", "case_by_case": True, "reason": "parent", "status": "confirmed"},
                   {"value": "Acme Defense", "reason": "unit", "status": "confirmed"}]
        self.assertEqual(blocked_by("Acme Defense Systems", entries)["reason"], "unit")
        self.assertEqual(blocked_by("Acme Corporation", entries)["reason"], "parent")

    def test_ampersand_and_accents_normalize(self):
        # Copilot review 2026-11-24: "Pratt & Whitney" missed "Pratt and Whitney"; "TUSAŞ" missed "Tusas".
        self.assertEqual(self.hit("Pratt and Whitney"), "r3")
        entries = [{"value": "Turkish Aerospace (TUSAŞ)", "aliases": ["TUSAŞ"], "reason": "t", "status": "confirmed"}]
        self.assertEqual(blocked_by("Tusas", entries)["reason"], "t")
        self.assertEqual(blocked_by("TUSAŞ Engine Industries", entries)["reason"], "t")
        exact = [{"value": "Moog (Moog Inc.)", "aliases": ["Moog Inc"], "match": "exact", "reason": "m",
                  "status": "confirmed"}]
        self.assertEqual(blocked_by("MOOG, Inc.", exact)["reason"], "m")
        self.assertIsNone(blocked_by("Moog Music", exact))

    def test_aliases_must_be_a_list(self):
        # A string would be read one character at a time, so "A" would block every company named "A ...".
        from paths import DataFileError, blocklist
        with self.assertRaises(DataFileError):
            blocklist({"company_blocklist": [{"value": "Acme", "aliases": "Acme Corp"}]}, "spec.json")
        with self.assertRaises(DataFileError):
            blocklist({"company_blocklist": [{"value": "Acme", "aliases": ["ok", 3]}]}, "spec.json")

    def test_confirmed_only(self):
        self.assertEqual(self.hit("Proposed Co"), "r6")
        self.assertIsNone(self.hit("Proposed Co", confirmed_only=True))


class TriageConfirm(SampleCase):
    def test_blocklisted_card_is_shown_for_confirmation_with_its_reason(self):
        spec_path = self.data / "5-criteria/spec.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        spec["company_blocklist"] = spec.get("company_blocklist", []) + [
            {"value": "Northwind Defense", "reason": "values: defense", "status": "confirmed"},
            {"value": "Contoso", "case_by_case": True, "reason": "parent of a defense unit", "status": "confirmed"}]
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        cards = self.tmp / "cards.json"
        cards.write_text(json.dumps([
            {"company": "Northwind Defense Systems", "title": "Senior Product Manager", "status": []},
            {"company": "Northwind Traders", "title": "Senior Product Manager", "status": []},
            {"company": "Contoso", "title": "Product Manager, Cloud", "status": []}]), encoding="utf-8")
        out = self.ok("triaged.py", "--data", self.data, "check", cards)
        got = json.loads(cards.read_text(encoding="utf-8"))
        self.assertEqual(got[0]["triaged"]["action"], "blocklist (confirm)")
        self.assertEqual(got[0]["triaged"]["reason"], "values: defense")
        self.assertFalse(got[0]["triaged"]["case_by_case"])
        self.assertIsNone(got[1]["triaged"])
        self.assertTrue(got[2]["triaged"]["case_by_case"])
        self.assertIn("2 blocklisted (confirm)", out)
        self.assertIn("blocklisted: Northwind Defense Systems - Senior Product Manager -> Northwind Defense", out)
        self.assertIn("blocklisted [case by case: is this role in the blocked area?]: Contoso", out)


if __name__ == "__main__":
    unittest.main()
