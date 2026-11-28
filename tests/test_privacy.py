"""The privacy scan and the pre-commit hook catch what they should, and only allow deliberate exceptions."""
import shutil
import subprocess
import unittest

from helpers import ENGINE, REPO, SampleCase, run

TERMS = "Jordan Avery\nPinewick\n"  # both invented


class Scan(SampleCase):
    def setUp(self):
        super().setUp()
        self.terms = self.tmp / "terms.txt"
        self.terms.write_text(TERMS, encoding="utf-8")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def scan(self, *extra):
        return run("privacy_scan.py", self.repo, "--terms", self.terms, *extra)

    def test_clean_folder_passes(self):
        (self.repo / "a.md").write_text("nothing personal", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)

    def test_terms_emails_paths_profiles_caught(self):
        # Built at runtime so this file doesn't trip the repo's own privacy scan.
        for line in ("by Jordan Avery", "write to someone" + "@" + "realmail.com",
                     "C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "x", "linkedin.com" + "/in/someone"):
            (self.repo / "a.md").write_text(line, encoding="utf-8")
            self.assertEqual(self.scan()[0], 1, line)

    def test_example_com_email_allowed(self):
        (self.repo / "a.md").write_text("contact ok" + "@" + "example.com", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)

    def test_archive_folders_scanned(self):
        (self.repo / "reports/archive").mkdir(parents=True)
        (self.repo / "reports/archive/old.md").write_text("Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)

    def test_ignore_marker_only_works_in_the_scanner(self):
        (self.repo / "a.md").write_text("Jordan Avery  # privacy-scan: ignore", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)

    def test_allow_file_is_exact_and_narrow(self):
        (self.repo / ".privacy-allow").write_text("LICENSE | Jordan Avery\n", encoding="utf-8")
        (self.repo / "LICENSE").write_text("Copyright Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)
        (self.repo / "LICENSE").write_text("Copyright Jordan Avery, Pinewick", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)                       # another term on the same line still caught
        (self.repo / "LICENSE").write_text("Copyright Jordan Avery", encoding="utf-8")
        (self.repo / "other.md").write_text("Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)                       # the exception doesn't spread to other files

    def test_strict_without_terms_refuses(self):
        code, _ = run("privacy_scan.py", self.repo, "--strict", "--data", self.tmp / "nowhere")
        self.assertEqual(code, 2)

    # Whole-project review of 2026-11-27 (commit ac6a523), findings 15-17.

    def test_terms_in_encoded_and_joined_forms_are_caught(self):
        bs = chr(92)
        forms = {
            "search link": "https://jobs.example.com/search/?keywords=%22Pinewick%22",
            "json newline": '{"t": "About us' + bs + 'nPinewick is hiring"}',
            "json tab": '{"t": "Company' + bs + 'tPinewick"}',
            "json unicode escape": '{"t": "Jord' + bs + 'u0061n Avery"}',
            "percent space": "Jordan%20Avery",
            "plus space": "q=Jordan+Avery",
            "underscore file": "Jordan_Avery_Resume.pdf",
            "underscore after": "Pinewick_Resume.pdf",
            "digits after": "Pinewick2026",
            "slug": "7-recommendations/jordan-avery/received",
            "run together": "user jordanavery signed in",
            "two spaces": "Jordan  Avery",
            "non-breaking space": "Jordan" + chr(0xa0) + "Avery",
            "html entity": "Jordan&nbsp;Avery",
            "wrapped over two lines": "recommended by Jordan\nAvery last year",
            "accent added": "Jord" + chr(0xe1) + "n Avery",
        }
        for name, text in forms.items():
            with self.subTest(form=name):
                (self.repo / "a.md").write_text(text, encoding="utf-8")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("private term", out)

    def test_a_term_inside_a_longer_word_is_not_a_hit(self):
        (self.repo / "a.md").write_text("Pinewicker spinewick Jordanian Avery, Jordan and Avery", encoding="utf-8")
        code, out = self.scan()
        self.assertEqual(code, 0, out)

    def test_an_accented_term_matches_plain_and_escaped_text(self):
        self.terms.write_text("Jos" + chr(0xe9) + " Avery\n", encoding="utf-8")
        for text in ("by Jose Avery", '{"n": "Jos' + chr(92) + 'u00e9 Avery"}', "by Jos" + chr(0xe9) + " Avery"):
            with self.subTest(text=text):
                (self.repo / "a.md").write_text(text, encoding="utf-8")
                self.assertEqual(self.scan()[0], 1)

    def test_encoded_profile_links_are_caught(self):
        (self.repo / "a.md").write_text("next=linkedin.com" + "%2Fin%2F" + "someone", encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)

    def test_a_terms_file_with_a_byte_order_mark_keeps_its_first_term(self):
        self.terms.write_text(TERMS, encoding="utf-8-sig")
        (self.repo / "a.md").write_text("by Jordan Avery", encoding="utf-8")
        code, out = self.scan()
        self.assertEqual(code, 1, out)

    def test_an_allow_file_with_a_byte_order_mark_keeps_its_first_line(self):
        (self.repo / ".privacy-allow").write_text("LICENSE | Jordan Avery\n", encoding="utf-8-sig")
        (self.repo / "LICENSE").write_text("Copyright Jordan Avery", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)

    def test_strict_refuses_a_list_with_no_terms(self):
        self.terms.write_text("# nothing yet\n\n", encoding="utf-8")
        (self.repo / "a.md").write_text("nothing personal", encoding="utf-8")
        code, out = self.scan("--strict")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.scan()[0], 0)  # without --strict an empty list is only a note

    def test_file_and_folder_names_are_checked(self):
        for rel in ("notes/Jordan Avery.md", "kits/pinewick-product-manager/log.md", "Jordan_Avery_Resume.txt"):
            with self.subTest(rel=rel):
                f = self.repo / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("clean", encoding="utf-8")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("file name", out)
                f.unlink()

    def test_an_allowed_phrase_in_a_file_name_is_not_a_hit(self):
        (self.repo / ".privacy-allow").write_text("docs/pinewick-case.md | Pinewick\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/pinewick-case.md").write_text("About Pinewick", encoding="utf-8")
        self.assertEqual(self.scan()[0], 0)


@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class Hook(SampleCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        shutil.copytree(ENGINE, self.repo / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "scripts/hooks", self.repo / "scripts/hooks")
        terms = self.tmp / "terms.txt"
        terms.write_text(TERMS, encoding="utf-8")
        for cmd in (["init", "-q"], ["config", "reverse-recruiter.privateTerms", str(terms)],
                    ["config", "user.name", "Test"], ["config", "user.email", "test@example.com"]):
            self.git(*cmd)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)

    def hook(self):
        return subprocess.run(["sh", "scripts/hooks/pre-commit"], cwd=self.repo, capture_output=True, text=True)

    def stage(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", "-f", name)

    def test_clean_commit_passes(self):
        self.git("add", "engine", "scripts")
        self.assertEqual(self.hook().returncode, 0)

    def test_private_term_blocked(self):
        self.stage("notes.md", "Jordan Avery")
        self.assertNotEqual(self.hook().returncode, 0)

    def test_document_formats_blocked(self):
        self.stage("resume.pdf", "binary")
        result = self.hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("document files", result.stdout)

    def test_personal_data_folder_blocked(self):
        self.stage("my-data/x.txt", "anything")
        self.assertNotEqual(self.hook().returncode, 0)

    def test_data_folder_under_any_name_blocked(self):
        self.stage("personal/6-system/jobs/1.json", "{}")
        result = self.hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("personal-data paths", result.stdout)

    def test_every_layout_folder_is_recognized(self):
        # Fourth whole-project review (2026-11-27): the guard stopped at 6-system.
        for folder in ("7-recommendations/jane-doe/received/recommendation.md", "8-mentor-advice/index.md",
                       "9-learning/topic/primer.md"):
            with self.subTest(folder=folder):
                self.stage(f"career-data/{folder}", "nothing the text scan would catch")
                result = self.hook()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("personal-data paths", result.stdout)
                self.git("rm", "-q", "--cached", "-r", "career-data")

    def test_data_folder_names_match_in_any_case(self):
        # Whole-project review of 2026-11-27, finding 55: Windows and macOS file names ignore case.
        for name in ("My-Data/x.txt", "Stuff/6-System/jobs/1.json"):
            with self.subTest(name=name):
                self.stage(name, "anything")
                result = self.hook()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("personal-data paths", result.stdout)
                self.git("rm", "-q", "--cached", "-r", name.split("/")[0])

    def test_a_missing_terms_file_blocks(self):
        self.git("config", "reverse-recruiter.privateTerms", str(self.tmp / "gone.txt"))
        self.stage("notes.md", "clean")
        result = self.hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stdout)

    def test_private_term_in_a_file_name_blocked(self):
        self.stage("kits/pinewick-product-manager/log.md", "clean")
        result = self.hook()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("file name", result.stdout)

    def test_sample_data_layout_allowed(self):
        self.stage("sample-data/6-system/jobs/1.json", "{}")
        self.assertEqual(self.hook().returncode, 0)

    def test_staged_content_is_what_counts(self):
        self.stage("notes.md", "clean")
        (self.repo / "notes.md").write_text("Jordan Avery", encoding="utf-8")  # unstaged change
        self.assertEqual(self.hook().returncode, 0)


if __name__ == "__main__":
    unittest.main()
