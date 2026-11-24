"""Job Tracker → Saved printed to PDF (engine/staleness.py tracker): jobs match by the ID in each card's link, open
and closed come from the card, and a complete capture lists project jobs that dropped off the list."""
import json

import pymupdf

import helpers

OPEN_IDS = ["9100000002", "9100000003", "9100000004", "9100000006", "9100000007", "9100000008", "9100000009"]


def card(page, y, jid, title, company, status):
    page.insert_text((40, y), title)
    page.insert_text((40, y + 14), f"{company} · United States (Remote)")
    page.insert_text((40, y + 28), status)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(36, y - 12, 560, y + 32),
                      "uri": f"https://www.linkedin.com/jobs/view/{jid}/?trk=tracker"})


def title_only_card(page, y, jid, title, company, status):
    """A card whose link covers only its title line (the status line sits below the link's area)."""
    page.insert_text((40, y), title)
    page.insert_text((40, y + 14), f"{company} · United States (Remote)")
    page.insert_text((40, y + 28), status)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(36, y - 12, 300, y + 3),
                      "uri": f"https://www.linkedin.com/jobs/view/{jid}/"})


def make_pdfs(folder, rows, header, per_file=4):
    """rows: [(job_id, title, company, status)], split over several files; the first page carries the header."""
    folder.mkdir(parents=True, exist_ok=True)
    for n, start in enumerate(range(0, len(rows), per_file), 1):
        doc = pymupdf.open()
        page = doc.new_page()
        if n == 1 and header is not None:
            page.insert_text((40, 30), f"Saved · {header}")
        for k, row in enumerate(rows[start:start + per_file]):
            card(page, 80 + k * 60, *row)
        doc.save(folder / f"Job tracker _ LinkedIn{n}.pdf")
        doc.close()


class TrackerPdf(helpers.SampleCase):
    def job(self, jid):
        return json.loads((self.data / "6-system" / "jobs" / f"{jid}.json").read_text(encoding="utf-8"))

    def rows(self):
        out = []
        for jid in OPEN_IDS:
            j = self.job(jid)
            out.append((jid, j["title"], j["company"], "Posted 3d ago"))
        return out

    def test_matches_by_id_marks_open_and_closed_and_lists_both_directions(self):
        rows = self.rows()
        rows[1] = (rows[1][0], rows[1][1], rows[1][2], "No longer accepting applications")
        rows.append(("4000000001", "Brand New Role", "Newco", "Reposted 2d ago"))
        # 9100000010 left off the list: it dropped off LinkedIn's Saved list
        folder = self.data / "1-inbox" / "tracked-jobs"
        make_pdfs(folder, rows, header=len(rows))
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertIn(f"{len(rows)} saved jobs of Saved · {len(rows)}; marked 6 open, 1 closed", out)
        self.assertEqual(self.job("9100000002")["open_check"],
                         {"date": "2030-01-15", "result": "open", "source": "tracker PDF", "note": "Posted 3d ago"})
        self.assertEqual(self.job("9100000003")["open_check"]["result"], "closed")
        self.assertIn("saved but not in the project: Brand New Role · Newco", out)
        self.assertIn("https://www.linkedin.com/jobs/view/4000000001/", out)
        self.assertIn("no longer saved (closed, or unsaved?): Quillstone Software", out)
        # applied (9100000001), passed (9100000005) and external jobs are expected to be off the Saved list
        self.assertNotIn("Harborline", out.split("no longer saved")[1] if "no longer saved" in out else "")
        self.assertNotIn("Tessellate", out)
        self.assertNotIn("Northwind", out)

    def test_same_title_jobs_stay_apart(self):
        rows = self.rows()[:2]
        rows = [(rows[0][0], "Senior Product Manager", "Twin Co", "Posted 1d ago"),
                (rows[1][0], "Senior Product Manager", "Twin Co", "No longer accepting applications")]
        folder = self.tmp / "pdfs"
        make_pdfs(folder, rows, header=None)
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertEqual(self.job(rows[0][0])["open_check"]["result"], "open")
        self.assertEqual(self.job(rows[1][0])["open_check"]["result"], "closed")
        self.assertIn("reverse check is skipped", out)  # no header: can't tell what's missing

    def test_incomplete_capture_skips_the_reverse_check(self):
        folder = self.tmp / "pdfs"
        make_pdfs(folder, self.rows(), header=40)
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertIn("but the header says 40", out)
        self.assertNotIn("no longer saved", out)

    def test_overlapping_pages_count_each_job_once(self):
        rows = self.rows()
        folder = self.tmp / "pdfs"
        make_pdfs(folder, rows + rows[:3], header=len(rows))  # the last file repeats the first three cards
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertIn(f"{len(rows)} saved jobs of Saved · {len(rows)}", out)

    def test_older_capture_never_overwrites_a_newer_check(self):
        folder = self.tmp / "pdfs"
        make_pdfs(folder, self.rows(), header=None)
        self.ok("staleness.py", "--data", self.data, "confirm", "9100000002", "closed", "--date", "2030-02-01")
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertEqual(self.job("9100000002")["open_check"]["result"], "closed")
        self.assertIn("1 kept a newer check", out)

    def test_partial_link_area_still_finds_the_status(self):
        folder = self.tmp / "pdfs"
        folder.mkdir()
        doc = pymupdf.open()
        page = doc.new_page()
        rows = self.rows()[:3]
        statuses = ["Posted 3d ago", "No longer accepting applications", "Reposted 1w ago"]
        for k, ((jid, title, company, _), st) in enumerate(zip(rows, statuses)):
            title_only_card(page, 80 + k * 60, jid, title, company, st)
        doc.save(folder / "Job tracker _ LinkedIn1.pdf")
        doc.close()
        out = self.ok("staleness.py", "--data", self.data, "tracker", folder, "--date", "2030-01-15")
        self.assertIn("marked 2 open, 1 closed", out)
        self.assertNotIn("no Posted/closed line", out)
        self.assertEqual(self.job(rows[1][0])["open_check"]["result"], "closed")  # not the next card's status

    def test_text_paste_still_works(self):
        j = self.job("9100000002")
        paste = self.tmp / "tracked-2030-01-15.txt"
        paste.write_text(f"Saved · 1\n\n{j['title']}\n{j['company']} · United States (Remote)\nPosted 2d ago\n",
                         encoding="utf-8")
        out = self.ok("staleness.py", "--data", self.data, "tracker", paste)
        self.assertIn("marked 1 open", out)
        self.assertEqual(self.job("9100000002")["open_check"]["date"], "2030-01-15")


if __name__ == "__main__":
    import unittest
    unittest.main()
