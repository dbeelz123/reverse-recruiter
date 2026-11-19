"""The 'no response since applying' reminder mentions a connection only when the job has a 1st-degree one."""
import datetime as dt
import unittest

import helpers  # noqa: F401  (puts engine/ on the import path)


def applied_job(connections):
    return {"pipeline": {"status": "applied", "events": [{"date": "2026-11-01", "stage": "applied"}]},
            "connections_1st": connections}


class FollowUpWording(unittest.TestCase):
    def texts(self, job):
        from interviews import due_items
        return [t for _, t in due_items(job, dt.date(2026, 11, 30))]

    def test_no_connection_means_no_connection_advice(self):
        texts = self.texts(applied_job([]))
        self.assertTrue(any("no response since applying" in t for t in texts), texts)
        self.assertFalse(any("connection" in t for t in texts), texts)

    def test_a_connection_is_named(self):
        texts = self.texts(applied_job([{"name": "Pat Example"}]))
        self.assertTrue(any("Pat Example" in t for t in texts), texts)


if __name__ == "__main__":
    unittest.main()
