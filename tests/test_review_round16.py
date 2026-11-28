"""Fixes from the review of commit 922d48f (2026-11-28, areas 3-4: screening and removal, scoring and the report):
each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest

from helpers import ENGINE, SampleCase, run

BAD = "9100000003"    # the record that is damaged in these tests
FIRST = "9100000001"  # sorts before it, so the report would reach it first


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class MalformedJobRecords(SampleCase):
    """#1: a job record that is valid JSON but not an object, or has no job ID, stops the re-screen and the report
    with the file named, and the report changes no record before it stops."""

    def test_the_file_is_named_and_nothing_is_rewritten(self):
        first = self.data / f"6-system/jobs/{FIRST}.json"
        rec = read(first)
        rec.pop("review", None)  # a completed report would write the review copy back
        first.write_text(json.dumps(rec), encoding="utf-8")
        before = first.read_text(encoding="utf-8")
        bad = self.data / f"6-system/jobs/{BAD}.json"
        for content in ("[]", '{"title": "Principal Product Manager"}', '{"job_id": 5, "title": "x"}',
                        '{"job_id": "  ", "title": "x"}', '"text"'):
            with self.subTest(content=content):
                bad.write_text(content, encoding="utf-8")
                for args in (("rescreen.py",), ("build_report.py", "--round", "2")):
                    code, out = run(*args, "--data", self.data)
                    self.assertNotEqual(code, 0, out)
                    self.assertNotIn("Traceback", out)
                    self.assertIn(f"{BAD}.json", out)
                self.assertEqual(first.read_text(encoding="utf-8"), before)

    def test_good_records_still_work(self):
        self.ok("rescreen.py", "--data", self.data)
        self.ok("build_report.py", "--data", self.data, "--round", "2")


class SweepTitleFamilies(unittest.TestCase):
    """#2: the AI title families match on a word boundary. The patterns held a literal backspace character where
    the boundary belonged, so they matched nothing."""

    def test_prefixed_ai_titles_reach_their_family(self):
        from sweep import family
        self.assertEqual(family("VP AI Engineer"), "ai engineer")
        self.assertEqual(family("VP AI Strategist"), "ai strategist")
        self.assertEqual(family("Head of AI Engineering"), "ai engineer")
        self.assertEqual(family("Senior AI Engineer, Product Engineering"), "ai engineer")

    def test_ai_inside_a_longer_word_is_not_the_family(self):
        from sweep import family
        self.assertNotEqual(family("Chai Engineer"), "ai engineer")
        self.assertNotEqual(family("Thai Strategist"), "ai strategist")

    def test_no_control_characters_in_the_engine(self):
        for f in sorted(ENGINE.glob("*.py")):
            odd = [c for c in f.read_text(encoding="utf-8") if ord(c) < 32 and c not in "\n\r\t"]
            self.assertEqual(odd, [], f"{f.name} holds control characters")


if __name__ == "__main__":
    unittest.main()
