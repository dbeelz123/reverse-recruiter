"""Choosing the data folder: --data, then the REVERSE_RECRUITER_DATA environment variable, then my-data/."""
import os
import subprocess
import sys
import unittest

from helpers import ENGINE, REPO, SampleCase


def run_env(env_value, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    env.pop("REVERSE_RECRUITER_DATA", None)
    if env_value is not None:
        env["REVERSE_RECRUITER_DATA"] = str(env_value)
    r = subprocess.run([sys.executable, "-B", str(ENGINE / "pipeline.py"), *map(str, args)], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout + r.stderr


class DataFolderSetting(SampleCase):
    def test_the_environment_variable_names_the_data_folder(self):
        queue = self.data / "2-reports/apply-queue.md"
        queue.unlink()
        code, out = run_env(self.data, "queue")
        self.assertEqual(code, 0, out)
        self.assertTrue(queue.exists())

    def test_data_flag_wins_over_the_environment_variable(self):
        other = self.tmp / "other"
        other.mkdir()
        queue = self.data / "2-reports/apply-queue.md"
        queue.unlink()
        code, out = run_env(other, "queue", "--data", self.data)
        self.assertEqual(code, 0, out)
        self.assertTrue(queue.exists())
        self.assertFalse((other / "2-reports").exists())

    def test_a_missing_folder_is_a_clear_error_not_a_fallback(self):
        code, out = run_env(self.tmp / "no-such-folder", "queue")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertIn("REVERSE_RECRUITER_DATA", out)
        self.assertFalse((REPO / "my-data").exists())


if __name__ == "__main__":
    unittest.main()
