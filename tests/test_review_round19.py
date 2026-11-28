"""Fixes from the review of commit f729e09 (2026-11-28, areas 1 and 3: data integrity, screening and removal): each
test reproduces the reported problem and checks the fixed behavior."""
import json
import unittest
from pathlib import Path
from unittest import mock

from helpers import SampleCase, run


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def edit_json(path, change):
    d = read(path)
    change(d)
    Path(path).write_text(json.dumps(d, indent=1), encoding="utf-8")


class Base(SampleCase):
    def spec(self, change):
        edit_json(self.data / "5-criteria/spec.json", change)

    def fails(self, script, *args, mention=()):
        code, out = run(script, *args)
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        for m in mention:
            self.assertIn(m, out)
        return out


class RuleStatuses(Base):
    """#1: a rule whose status is mistyped (or missing) is named, not silently left out of the re-screen."""

    def test_an_unknown_status_stops_the_rescreen(self):
        for section in ("dealbreakers", "negatives", "qualifiers", "company_blocklist"):
            for bad in ("confimed", "Confirmed", "", None, 1):
                with self.subTest(section=section, status=bad):
                    good = read(self.data / "5-criteria/spec.json")
                    name = str(good[section][0]["value"])[:30]
                    self.spec(lambda d: d[section][0].update(status=bad))
                    self.fails("rescreen.py", "--data", self.data, mention=("spec.json", section, name))
                    (self.data / "5-criteria/spec.json").write_text(json.dumps(good), encoding="utf-8")

    def test_a_rule_with_no_status_stops_the_rescreen(self):
        self.spec(lambda d: d["dealbreakers"][0].pop("status"))
        self.fails("rescreen.py", "--data", self.data, mention=("spec.json", "dealbreakers", "status"))

    def test_a_rule_that_is_not_an_object_stops_the_rescreen(self):
        self.spec(lambda d: d["negatives"].append("no travel"))
        self.fails("rescreen.py", "--data", self.data, mention=("spec.json", "negatives"))
        self.spec(lambda d: d.update(negatives="no travel"))
        self.fails("rescreen.py", "--data", self.data, mention=("spec.json", "negatives"))

    def test_the_known_statuses_pass(self):
        from paths import RULE_STATUSES
        self.assertEqual(set(RULE_STATUSES), {"proposed", "confirmed", "rejected", "superseded", "retired"})
        for status in RULE_STATUSES:
            with self.subTest(status=status):
                self.spec(lambda d: d["negatives"][0].update(status=status))
                self.ok("rescreen.py", "--data", self.data)

    def test_a_status_from_the_users_own_legend_passes(self):
        def own(d):
            d.setdefault("status_legend", {})["on hold"] = "parked until the next calibration"
            d["negatives"][0]["status"] = "on hold"
        self.spec(own)
        self.ok("rescreen.py", "--data", self.data)

    def test_a_mistyped_dealbreaker_no_longer_goes_unflagged(self):
        """The reported case end to end: before, the re-screen ran clean and printed no flag for the rule."""
        before = self.ok("rescreen.py", "--data", self.data)
        self.spec(lambda d: [r.update(status="confimed") for r in d["dealbreakers"]])
        code, out = run("rescreen.py", "--data", self.data)
        self.assertNotEqual(code, 0, out)
        self.assertIn("confimed", out)
        self.assertNotIn("Re-screen against", out)  # stopped before screening, not after a clean-looking run
        self.assertIn("Re-screen against", before)


class Radius(Base):
    """#2: a radius that isn't a number from 0 up stops the commands that use it, instead of flagging every local
    job as outside the radius (a negative value) or stopping with a traceback (text)."""

    def test_an_invalid_radius_is_named(self):
        for bad in (-1, "50", None, True, [50], float("inf")):
            with self.subTest(radius=bad):
                good = read(self.data / "5-criteria/spec.json")
                self.spec(lambda d: d["work_arrangement"]["machine_rule"].update(radius_miles=bad))
                if bad == float("inf"):  # written as the bare word Infinity, which Python's reader accepts
                    self.assertIn("Infinity", (self.data / "5-criteria/spec.json").read_text(encoding="utf-8"))
                for args in (("rescreen.py",), ("build_report.py", "--round", "2"), ("searches.py",)):
                    out = self.fails(*args, "--data", self.data, mention=("spec.json", "radius_miles"))
                    self.assertNotIn("OUTSIDE RADIUS", out)
                (self.data / "5-criteria/spec.json").write_text(json.dumps(good), encoding="utf-8")

    def test_a_missing_radius_is_50_miles_and_zero_is_allowed(self):
        from paths import radius_miles
        self.assertEqual(radius_miles({}, "spec.json"), 50)
        self.assertEqual(radius_miles({"work_arrangement": {"machine_rule": {"radius_miles": 0}}}, "spec.json"), 0)
        self.assertEqual(radius_miles({"work_arrangement": {"machine_rule": {"radius_miles": 37.5}}}, "spec.json"), 37.5)
        self.spec(lambda d: d["work_arrangement"]["machine_rule"].pop("radius_miles"))
        self.ok("rescreen.py", "--data", self.data)

    def test_the_report_changes_no_record_before_it_stops(self):
        record = self.data / "6-system/jobs/9100000001.json"
        edit_json(record, lambda j: j.pop("review", None))  # a completed report would write the review copy back
        before = record.read_text(encoding="utf-8")
        self.spec(lambda d: d["work_arrangement"]["machine_rule"].update(radius_miles=-1))
        self.fails("build_report.py", "--round", "2", "--data", self.data)
        self.assertEqual(record.read_text(encoding="utf-8"), before)


class WriteJson(Base):
    """#3: a failure while the temporary file is written (disk full, folder not writable) stops with the file
    named, leaves the data file as it was and leaves no partial .tmp behind."""

    def test_a_failed_temporary_write_is_named_and_cleaned_up(self):
        from paths import DataFileError, write_json
        target = self.tmp / "ledger.json"
        target.write_text('{"kept": true}', encoding="utf-8")
        real = Path.write_text

        def full_disk(path, data, *a, **k):
            if path.name.endswith(".tmp"):
                real(path, data[: len(data) // 2], *a, **k)  # half the file reaches the disk, then it is full
                raise OSError(28, "No space left on device")
            return real(path, data, *a, **k)
        with mock.patch.object(Path, "write_text", full_disk):
            with self.assertRaises(DataFileError) as e:
                write_json(target, {"new": list(range(50))})
        self.assertIn("ledger.json", str(e.exception))
        self.assertIn("No space left", str(e.exception))
        self.assertEqual(target.read_text(encoding="utf-8"), '{"kept": true}')
        self.assertFalse((self.tmp / "ledger.json.tmp").exists())

    def test_a_value_that_is_not_json_changes_nothing(self):
        from paths import write_json
        target = self.tmp / "ledger.json"
        target.write_text('{"kept": true}', encoding="utf-8")
        with self.assertRaises(TypeError):  # a programming error, not a disk problem: it stays what it is
            write_json(target, {"when": object()})
        self.assertEqual(target.read_text(encoding="utf-8"), '{"kept": true}')
        self.assertFalse((self.tmp / "ledger.json.tmp").exists())

    def test_a_normal_write_still_works(self):
        from paths import write_json
        target = self.tmp / "ledger.json"
        write_json(target, {"a": "é"}, newline=True)
        self.assertEqual(read(target), {"a": "é"})
        self.assertFalse((self.tmp / "ledger.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
