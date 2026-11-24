"""Interview-prep PDFs (engine/prep_pdf.py): the Markdown converter, reading a kit through its manifest, the
combined master, the anonymizer's rules, and one real render when a browser is available."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import run

import prep_pdf

PREP = """# 1. Game plan
Intro line.
## At a glance
- one
- two
  - nested
## Questions to ask (ranked)
1. First question?
2. Second question?
## Rules for the room
Be brief.
# 2. The panel
## Person A
Notes on [a profile](https://example.com/a) and [a local file](notes.md).
"""


def make_kit(root):
    kit = Path(root) / "kit"
    kit.mkdir()
    (kit / "interview-prep.md").write_text(PREP, encoding="utf-8")
    (kit / "fit-map.md").write_text("# Fit map\n| Requirement | Evidence | Rating |\n|---|---|---|\n"
                                    "| APIs | Built them | Have |\n", encoding="utf-8")
    m = {
        "out": "out", "subtitle": "Example Co · Round 1",
        "reading_order": ["Game plan", "The panel", "Fit map"],
        "packets": [
            {"source": "interview-prep.md", "parts": ["01 Game plan", "02 The panel"]},
            {"source": "fit-map.md", "name": "03 Fit map", "title": "Fit map: requirements vs. evidence",
             "label": "03 Fit map"},
            {"source": "reading-list.md", "name": "04 Reading list", "optional": True},
            {"source": "interview-prep.md", "section": "Questions to ask", "name": "05 My questions",
             "title": "My questions (ranked)"}],
        "master": {"name": "master", "subtitle": "all", "include": ["01 Game plan", "02 The panel", "03 Fit map",
                                                                     "05 My questions"]},
        "cleaned": {"name": "cleaned", "subtitle": "anon", "include": ["01 Game plan", "02 The panel"],
                    "rules": "rules.txt", "preamble": "preamble.md"}}
    (kit / "prep-pdf.json").write_text(json.dumps(m), encoding="utf-8")
    return kit


class Convert(unittest.TestCase):
    def test_blocks(self):
        h = prep_pdf.convert("## Head\nPara **bold** *it* `c`\n\n- a\n  - b\n> quote")
        self.assertIn("<h2>Head</h2>", h)
        self.assertIn("<strong>bold</strong> <em>it</em> <code>c</code>", h)
        self.assertIn("<ul><li>a<ul><li>b</li></ul></li></ul>", h)
        self.assertIn("<blockquote><p>quote</p></blockquote>", h)

    def test_links_keep_web_drop_local(self):
        h = prep_pdf.inline("[web](https://example.com) and [local](file.md)")
        self.assertIn('<a href="https://example.com">web</a>', h)
        self.assertIn("and local", h)

    def test_tables_two_columns_stay_wider_become_cards(self):
        self.assertIn("<table>", prep_pdf.convert("| A | B |\n|---|---|\n| 1 | 2 |"))
        cards = prep_pdf.convert("| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |")
        self.assertIn('class="card"', cards)
        self.assertNotIn("<table>", cards)

    def test_html_is_escaped(self):
        self.assertIn("&lt;script&gt;", prep_pdf.convert("a <script> tag"))


class Kit(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.kit = make_kit(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_packets_from_manifest(self):
        pk = prep_pdf.packets(self.kit, prep_pdf.load_manifest(self.kit))
        self.assertEqual([p["name"] for p in pk], ["01 Game plan", "02 The panel", "03 Fit map", "05 My questions"])
        self.assertEqual(pk[0]["title"], "Game plan")
        self.assertEqual(pk[1]["label"], "02 The panel")
        self.assertTrue(pk[0]["toc"])  # reading order goes on the first packet by default
        self.assertNotIn("# Fit map", pk[2]["md"])  # the file's own title is dropped
        self.assertIn("1. First question?", pk[3]["md"])
        self.assertNotIn("Be brief", pk[3]["md"])  # a section stops at the next heading

    def test_part_count_must_match(self):
        m = prep_pdf.load_manifest(self.kit)
        m["packets"][0]["parts"] = ["01 Only one"]
        with self.assertRaises(SystemExit):
            prep_pdf.packets(self.kit, m)

    def test_missing_required_source_fails(self):
        m = prep_pdf.load_manifest(self.kit)
        m["packets"].append({"source": "nope.md"})
        with self.assertRaises(SystemExit):
            prep_pdf.packets(self.kit, m)

    def test_master_compose_and_html(self):
        m = prep_pdf.load_manifest(self.kit)
        md = prep_pdf.compose(prep_pdf.pick(prep_pdf.packets(self.kit, m), m["master"]["include"], "master"))
        self.assertEqual([l for l in md.splitlines() if l.startswith("# ")],
                         ["# 01 Game plan", "# 02 The panel", "# 03 Fit map", "# 05 My questions"])
        page = prep_pdf.combined_html(md, "master", "all")
        self.assertEqual(page.count("<h1 class='doc'>"), 4)
        self.assertIn("break-before: page", page)
        with self.assertRaises(SystemExit):
            prep_pdf.pick(prep_pdf.packets(self.kit, m), ["99 Missing"], "master")

    def test_cleaned_applies_rules_and_preamble(self):
        (self.kit / "rules.txt").write_text("Person A ==> Trusted Source 1\nnever matches ==> x\n", encoding="utf-8")
        (self.kit / "preamble.md").write_text("# 00 Key\nWho is who.\n", encoding="utf-8")
        md, unused = prep_pdf.cleaned_markdown(self.kit, prep_pdf.load_manifest(self.kit))
        self.assertTrue(md.startswith("# 00 Key"))
        self.assertIn("Trusted Source 1", md)
        self.assertNotIn("Person A", md)
        self.assertEqual(unused, ["line 2: never matches"])

    def test_bad_manifest(self):
        (self.kit / "prep-pdf.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            prep_pdf.load_manifest(self.kit)


class Anonymize(unittest.TestCase):
    def test_rules_in_order_regex_newline_delete_and_comments(self):
        rules = ("# a comment\n\nAcme Corp ==> the Client\nre: \\bBob( Smith)?\\b ==> Trusted Source 2\n"
                 "re: (?s)<<.*?>> ==> [cut]\\n\nsecret ==>\n")
        text, unused = prep_pdf.anonymize("Acme Corp hired Bob Smith. <<a\nb>> secret end", rules)
        self.assertEqual(text, "the Client hired Trusted Source 2. [cut]\n  end")  # no capitalize rule given
        self.assertEqual(unused, [])

    def test_unused_rules_reported_with_line_numbers(self):
        _, unused = prep_pdf.anonymize("text", "zzz ==> y\nre: qqq ==> y\n")
        self.assertEqual(unused, ["line 1: zzz", "line 2: re: qqq"])

    def test_capitalize_at_starts_only(self):
        rules = "Acme ==> the Client\ncapitalize: the Client\n"
        text, _ = prep_pdf.anonymize("Acme wins. We like Acme.\n- Acme rules\n| Acme | x |\n## 3 Acme", rules)
        self.assertEqual(text, "The Client wins. We like the Client.\n- The Client rules\n| The Client | x |\n"
                               "## 3 The Client")

    def test_capitalize_matches_the_whole_phrase_only(self):
        text, _ = prep_pdf.anonymize("the Clientele grew. the Client wins.", "capitalize: the Client")
        self.assertEqual(text, "the Clientele grew. The Client wins.")

    def test_bad_regex_is_a_clear_error(self):
        with self.assertRaises(SystemExit):
            prep_pdf.anonymize("x", "re: ( ==> y\n")

    def test_cli(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "r.txt").write_text("Acme ==> the Client\n", encoding="utf-8")
            (td / "in.md").write_text("Acme here.", encoding="utf-8")
            code, out = run("prep_pdf.py", "anonymize", "--rules", td / "r.txt", "--in", td / "in.md",
                            "--out", td / "out.md")
            self.assertEqual(code, 0, out)
            self.assertEqual((td / "out.md").read_text(encoding="utf-8"), "the Client here.")


class PrintSafety(unittest.TestCase):
    def test_a_failed_copy_keeps_the_previous_pdf(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            pdf = Path(td) / "packet.pdf"
            pdf.write_bytes(b"%PDF old")

            def fake_run(cmd, **kw):  # the "browser" writes its output where --print-to-pdf points
                out = next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1]
                Path(out).write_bytes(b"%PDF new")
            with mock.patch.object(prep_pdf.subprocess, "run", fake_run), \
                    mock.patch.object(prep_pdf.shutil, "copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    prep_pdf.print_pdf("browser", "<html></html>", pdf, timeout=2)
            self.assertEqual(pdf.read_bytes(), b"%PDF old")

    def test_a_failed_swap_keeps_the_pdf_and_leaves_no_part_file(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            pdf = Path(td) / "packet.pdf"
            pdf.write_bytes(b"%PDF old")

            def fake_run(cmd, **kw):
                out = next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1]
                Path(out).write_bytes(b"%PDF new")
            with mock.patch.object(prep_pdf.subprocess, "run", fake_run), \
                    mock.patch.object(prep_pdf.os, "replace", side_effect=PermissionError("open in a viewer")):
                with self.assertRaises(PermissionError):
                    prep_pdf.print_pdf("browser", "<html></html>", pdf, timeout=2)
            self.assertEqual(pdf.read_bytes(), b"%PDF old")
            self.assertFalse(pdf.with_name("packet.pdf.part").exists())

    def test_a_good_print_replaces_the_pdf(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            pdf = Path(td) / "packet.pdf"
            pdf.write_bytes(b"%PDF old")

            def fake_run(cmd, **kw):
                out = next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1]
                Path(out).write_bytes(b"%PDF new")
            with mock.patch.object(prep_pdf.subprocess, "run", fake_run):
                prep_pdf.print_pdf("browser", "<html></html>", pdf, timeout=2)
            self.assertEqual(pdf.read_bytes(), b"%PDF new")
            self.assertFalse(pdf.with_name("packet.pdf.part").exists())


def browser():
    try:
        return prep_pdf.find_browser()
    except SystemExit:
        return None


@unittest.skipUnless(browser(), "no Edge or Chrome to print with")
class Render(unittest.TestCase):
    def test_all_writes_every_pdf(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            kit = make_kit(td)
            (kit / "rules.txt").write_text("Person A ==> Trusted Source 1\n", encoding="utf-8")
            (kit / "preamble.md").write_text("# 00 Key\nWho is who.\n", encoding="utf-8")
            code, out = run("prep_pdf.py", "all", kit)
            self.assertEqual(code, 0, out)
            names = sorted(p.name for p in (kit / "out").glob("*.pdf"))
            self.assertEqual(names, ["01 Game plan.pdf", "02 The panel.pdf", "03 Fit map.pdf", "05 My questions.pdf",
                                     "cleaned.pdf", "master.pdf"])
            self.assertTrue(all((kit / "out" / n).read_bytes().startswith(b"%PDF") for n in names))


if __name__ == "__main__":
    unittest.main()
