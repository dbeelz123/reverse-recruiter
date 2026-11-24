"""Pasted search results (engine/ingest_results.py): where LinkedIn's "may not be exact matches" banner starts."""
import unittest

import helpers  # noqa: F401  (puts engine/ on the path)
from ingest_results import parse_paste

BANNER = ("We found more results related to your search that may not be exact matches, "
          "but could still be a great fit.")

CARD_A = "Senior Product Manager\nAcme\nUnited States (Remote)\nPosted 2 days ago\n"
CARD_B = "Principal Product Manager\nGlobex\nUnited States (Remote)\nViewed\n"


class Banner(unittest.TestCase):
    def test_linkedin_banner_marks_later_cards(self):
        cards = parse_paste(CARD_A + "\n" + BANNER + "\n\n" + CARD_B)
        self.assertEqual([c["section"] for c in cards], ["exact", "after banner"])

    def test_quoted_banner_in_a_note_is_not_the_banner(self):
        # 2026-11-24: the user's note at the top of the paste quoted the banner text, and every card was marked
        # "after banner" although all of them came before the real one.
        note = 'S1\n99+ results\nonly showing results up until "' + BANNER + '"\n\n'
        cards = parse_paste(note + CARD_A + "\n" + CARD_B)
        self.assertEqual([c["section"] for c in cards], ["exact", "exact"])

    def test_note_then_real_banner(self):
        note = 'copied up until "' + BANNER + '"\n\n'
        cards = parse_paste(note + CARD_A + "\n" + BANNER + "\n\n" + CARD_B)
        self.assertEqual([c["section"] for c in cards], ["exact", "after banner"])


if __name__ == "__main__":
    unittest.main()
