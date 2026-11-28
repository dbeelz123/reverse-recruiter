# Setup

From an empty folder to your first ranked report. The process itself is in [how-it-works.md](how-it-works.md).

## 1. Install

- **Python 3.10+** and the one package the engine needs: `pip install -r requirements.txt` (`pymupdf`, for reading PDFs).
- **[Claude Code](https://claude.com/claude-code)** for the judgment steps (a Claude subscription or an API key).
- **Optional:** Microsoft Edge or Google Chrome, used headless only if you render the public funnel images (`engine/linkedin_images.py`) or print interview-prep PDFs (`engine/prep_pdf.py`).

```bash
git clone <this repo> reverse-recruiter
cd reverse-recruiter
pip install -r requirements.txt
cp -r sample-data demo-data                                      # scratch copy of the fictional candidate
python -B engine/build_report.py --data demo-data --round 2      # sanity check: rebuilds its ranked report
```

## 2. Turn on the privacy hook (if you'll commit changes)

Your personal details must never reach the repo. Keep a list of them **outside the repo** (your data folder is a good place) and point git at it:

```bash
git config core.hooksPath scripts/hooks
git config reverse-recruiter.privateTerms "<path to your private-terms.txt>"
```

`private-terms.txt` is one term per line: your name, home town, employers, products you worked on, contacts and interviewers, account names (see `sample-data/private-terms.example.txt`). Every commit is then scanned for those terms plus home-folder paths, email addresses and profile links, and blocked on any hit. Four hooks do it: `pre-commit` and `pre-merge-commit` check the files, `commit-msg` checks the message (a co-author line's no-reply address is the one address allowed), and `pre-push` checks every commit again before it leaves your machine, because git runs no commit hook for a cherry-pick, a rebase or a revert. Run the same check by hand with `python -B engine/privacy_scan.py [PATH ...] --terms <file>`.

## 3. Create your data folder

Use `my-data/` inside the repo (it's git-ignored) or any folder elsewhere. If it's elsewhere, create `CLAUDE.local.md` in the repo root (also git-ignored) so Claude knows where it is:

```markdown
# My settings
- Data folder: <full path>  (pass --data to every engine script)
- Name: <how you'd like to be addressed>
```

Create the layout (or copy `sample-data/` and replace its contents):

```
<data>/1-inbox/job-pdfs/
<data>/1-inbox/search-results/
<data>/1-inbox/tracked-jobs/
<data>/1-inbox/role-explorer/
<data>/2-reports/
<data>/3-applications/
<data>/4-profile/resume/
<data>/4-profile/linkedin/
<data>/5-criteria/
<data>/6-system/
<data>/7-recommendations/
```

Folders you add beside these are yours; no script reads them. The pre-commit hook guards two such names as well, `8-mentor-advice/` and `9-learning/` (advice you were given, and study notes), so they can't be committed either.

## 4. Add your inputs

Everything goes in by hand; [capture-workflow.md](capture-workflow.md) has the step-by-step for each (Chrome + keystrokes).
- **Your resume** (`.docx` and `.pdf`) in `4-profile/resume/`.
- **Your LinkedIn profile** in `4-profile/linkedin/`: the main profile page saved as a PDF with every "…more" expanded, then one PDF per "Show all →" section (`…_LinkedIn_experience`, `_projects`, …). Recommendations go in `7-recommendations/`.
- **10 to 30 saved jobs** in `1-inbox/job-pdfs/`, one PDF each, saved from the job page with the description expanded, through the browser's **Save as PDF** ("Microsoft Print to PDF" produces images with no text), keeping the default file name. If the job shows a 1st-degree connection, save a second PDF of "People you can reach out to" and add `_people` to its name.
- **Jobs from anywhere else** (a recruiter's document, another site): `python -B engine/ingest_external.py <file> --id ext-<slug> --company … --title …` turns it into a regular job record.
- **Optional, for the local radius:** `5-criteria/places.json` lists the cities around your home with their coordinates (see the sample). Hybrid and on-site jobs in cities not listed show as "distance unknown" until you add them.

## 5. Run your first round

Open the repo in Claude Code and say **"run round 1"**. The first round is also the setup:
1. Claude extracts the PDFs (`extract.py`) and reads every posting in full.
2. It drafts your profile of record from the resume and profile export, a **career master** (the only source of claims for applications, every fact tagged by theme), and a first `spec.json` from what the postings and your documents show.
3. It asks a first **calibration**: a dozen or so short questions where the sources disagree or the signal is unclear. Your answers become rules, each logged in `changelog.md`.
4. It writes the first ranked report in `2-reports/`, with a skills-gap tally and suggested searches (`searches.json` → `2-reports/search-links.md`).

From there, each round follows [how-it-works.md](how-it-works.md): triage new search results, save the keeps, "run round N".

## 6. Everyday commands

You mostly talk to Claude; these are the phrases it knows:

| Say | What happens |
|---|---|
| "run round N" | Extract, review, calibrate, re-screen, metrics, report |
| "start the triage" | Batches from pasted search results, with the agent's call on each card |
| "check saves" | Compares a pasted saved-jobs page with the project, and refreshes which postings are still open |
| "prep <company>" | Stretch review, then an application kit |
| "primer <company>" | Fit map rated Have / Partial / Gap, and likely interview questions |
| "explore <title>" | Role Explorer brief from a description in `1-inbox/role-explorer/` |
| "applied to X", "X replied", "passing on X" | Recorded in the apply queue |

Every engine script also runs on its own; the docstring at the top of each one shows its usage, and most take `--help`.
