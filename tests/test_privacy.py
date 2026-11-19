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

    def test_staged_content_is_what_counts(self):
        self.stage("notes.md", "clean")
        (self.repo / "notes.md").write_text("Jordan Avery", encoding="utf-8")  # unstaged change
        self.assertEqual(self.hook().returncode, 0)


if __name__ == "__main__":
    unittest.main()
