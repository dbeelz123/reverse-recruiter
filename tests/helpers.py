"""Shared helpers for the test suite: run engine scripts against throwaway copies of sample-data."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine"
SAMPLE = REPO / "sample-data"
sys.path.insert(0, str(ENGINE))


def run(script, *args, cwd=REPO):
    """Run an engine script (or scripts/ file) with -B; returns (exit code, combined output)."""
    path = script if Path(str(script)).is_absolute() else (REPO / script if "/" in str(script) else ENGINE / script)
    # The caller's own settings must not reach the scripts under test: a private-terms list or a data folder set
    # in the environment would change what they read (every test passes its own --data and --terms).
    env = {k: v for k, v in os.environ.items() if k not in ("PRIVATE_TERMS", "REVERSE_RECRUITER_DATA")}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", str(path), *map(str, args)], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout + r.stderr


class SampleCase(unittest.TestCase):
    """Each test gets its own copy of sample-data in a temporary folder (self.data) and a scratch folder (self.tmp)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.data = self.tmp / "data"
        shutil.copytree(SAMPLE, self.data)

    def tearDown(self):
        self._td.cleanup()

    def ok(self, script, *args):
        code, out = run(script, *args)
        self.assertEqual(code, 0, f"{script} {' '.join(map(str, args))} failed:\n{out}")
        return out
