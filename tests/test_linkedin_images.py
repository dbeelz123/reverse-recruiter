"""The public images' numbers: the funnel per 100, the grade split, and a hand-set split (no browser needed)."""
import unittest

from helpers import SampleCase


class GradeSplit(SampleCase):
    def test_bands_add_up_to_the_funnels_targets(self):
        import linkedin_images as li
        t = {"processed": 702, "decided": 286, "pdfs": 144, "ranked": 62}
        f, g = li.per100(t, {"A": 10, "B": 21, "C": 26, "D": 5})
        self.assertEqual(f, {"processed": 100, "decided": 41, "pdfs": 21, "ranked": 9})
        self.assertEqual(sum(g.values()), f["ranked"])

    def test_hand_set_split(self):
        import linkedin_images as li
        self.assertEqual(li.parse_grades("A=2,B=3,C=3,D=1"), {"A": 2, "B": 3, "C": 3, "D": 1})
        with self.assertRaises(SystemExit):
            li.parse_grades("A=two")

    def test_grade_image_has_no_percentages(self):
        import linkedin_images as li
        html = li.grades_html({"A": 2, "B": 3, "C": 3, "D": 1}, "9 qualified targets per 100 job listings processed")
        self.assertNotIn("%</", html)
        self.assertIn("A 2", html)
        funnel = li.funnel_html({"processed": 100, "decided": 41, "pdfs": 21, "ranked": 9})
        self.assertNotIn("<small>", funnel)


if __name__ == "__main__":
    unittest.main()
