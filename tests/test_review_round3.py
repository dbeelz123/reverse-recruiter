"""Fixes from the third code review: each test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest
import zipfile

from helpers import SampleCase, run

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class ExternalReingest(SampleCase):
    def test_reingesting_keeps_pipeline_history(self):
        kit = self.data / "3-applications/northwind-freight-sr-pm-marketplace"
        rec_p = self.data / "6-system/jobs/ext-northwind-freight-sr-pm.json"
        before = json.loads(rec_p.read_text(encoding="utf-8"))["pipeline"]["events"]
        self.assertTrue(before)
        self.ok("ingest_external.py", kit / "job-description.txt", "--id", "ext-northwind-freight-sr-pm",
                "--company", "Northwind Freight", "--title", "Senior PM", "--status", "interview",
                "--data", self.data)
        pl = json.loads(rec_p.read_text(encoding="utf-8"))["pipeline"]
        self.assertEqual(pl["events"], before)
        self.assertEqual(pl["status"], "interview")


class Rescreen(SampleCase):
    def test_invalid_pattern_names_the_rule(self):
        spec_p = self.data / "5-criteria/spec.json"
        spec = json.loads(spec_p.read_text(encoding="utf-8"))
        spec["negatives"][0]["rescreen_regex"] = "(unclosed"
        spec_p.write_text(json.dumps(spec), encoding="utf-8")
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0)
        self.assertIn("Invalid patterns", out)
        self.assertIn("(unclosed", out)
        self.assertNotIn("Traceback", out)


class InterviewDates(SampleCase):
    def test_unknown_date_is_stored_as_no_date(self):
        self.ok("interviews.py", "--data", self.data, "schedule", "arcadia", "--round", "1", "--date", "unknown")
        rec = json.loads((self.data / "6-system/jobs/9100000009.json").read_text(encoding="utf-8"))
        self.assertIsNone(rec["interviews"][0]["date"])
        self.ok("interviews.py", "--data", self.data, "due", "--soon", "30")

    def test_bad_stored_date_does_not_crash(self):
        p = self.data / "6-system/jobs/ext-northwind-freight-sr-pm.json"
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["interviews"][-1]["date"] = "next week"
        p.write_text(json.dumps(rec), encoding="utf-8")
        self.ok("interviews.py", "--data", self.data, "due", "--soon", "30")
        self.ok("pipeline.py", "queue", "--data", self.data)


class TailorResume(SampleCase):
    def make_docx(self):
        doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>'
               f'<w:p><w:r><w:t>Led Acme &amp; Co migrations</w:t></w:r></w:p>'
               f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold line</w:t></w:r></w:p></w:body></w:document>')
        src = self.tmp / "resume.docx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("word/document.xml", doc)
        return src

    def test_runs_without_formatting_are_editable_and_output_is_valid(self):
        from xml.dom.minidom import parseString
        src, dst, edits = self.make_docx(), self.tmp / "out.docx", self.tmp / "edits.json"
        edits.write_text(json.dumps([["Led", "", "Led", "Ran", "*"], ["Bold", "", "Bold", "Strong", "*"]]),
                         encoding="utf-8")
        self.ok("tailor_resume.py", src, dst, edits)
        xml = zipfile.ZipFile(dst).read("word/document.xml").decode("utf-8")
        parseString(xml.encode("utf-8"))                      # well-formed
        self.assertIn("Acme &amp; Co", xml)                    # kept text not double-escaped
        self.assertNotIn("&amp;amp;", xml)
        self.assertEqual(xml.count("<w:ins "), 2)              # both runs edited, with and without <w:rPr>

    def test_inserted_text_is_escaped(self):
        src, dst, edits = self.make_docx(), self.tmp / "out.docx", self.tmp / "edits.json"
        edits.write_text(json.dumps([["Led", "", "Led", "R&D <led>", "*"]]), encoding="utf-8")
        self.ok("tailor_resume.py", src, dst, edits)
        xml = zipfile.ZipFile(dst).read("word/document.xml").decode("utf-8")
        self.assertIn("R&amp;D &lt;led&gt;", xml)


class Report(SampleCase):
    def test_malformed_review_names_file_job_and_field(self):
        p = self.data / "6-system/reviews/round-01.json"
        rv = json.loads(p.read_text(encoding="utf-8"))
        rv["jobs"]["9100000002"]["fit"] = "eighty"
        p.write_text(json.dumps(rv), encoding="utf-8")
        code, out = run("build_report.py", "--data", self.data, "--round", "2")
        self.assertNotEqual(code, 0)
        self.assertIn("Malformed review for job 9100000002", out)
        self.assertIn("round-01.json", out)
        self.assertIn("'fit'", out)


class SearchResultsJson(SampleCase):
    def test_json_must_be_a_list_of_rows(self):
        src = self.tmp / "results.json"
        src.write_text(json.dumps({"title": "PM", "company": "A", "location": "Remote"}), encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)
        self.assertIn("expected a JSON list", out)
        src.write_text(json.dumps(["just a string"]), encoding="utf-8")
        code, out = run("ingest_results.py", src, self.tmp / "cards.json")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
