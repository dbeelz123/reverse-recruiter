"""A name-collision save may use the long '_possibleduplicate' suffix or the short '_possdup' one."""
import unittest

import helpers  # noqa: F401  (puts engine/ on the path)
from extract import dup_original


class DupSuffix(unittest.TestCase):
    def test_both_suffixes_map_to_the_original_name(self):
        self.assertEqual(dup_original("1-inbox/job-pdfs/Acme PM _ LinkedIn_possibleduplicate.pdf"),
                         "1-inbox/job-pdfs/Acme PM _ LinkedIn.pdf")
        self.assertEqual(dup_original("Acme PM _ LinkedIn_possdup.pdf"), "Acme PM _ LinkedIn.pdf")
        self.assertEqual(dup_original("Acme PM _ LinkedIn_PossDup.pdf"), "Acme PM _ LinkedIn.pdf")

    def test_other_files_are_not_duplicates(self):
        self.assertIsNone(dup_original("Acme PM _ LinkedIn.pdf"))
        self.assertIsNone(dup_original("Acme PM _ LinkedIn_people.pdf"))
