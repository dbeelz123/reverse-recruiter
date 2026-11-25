# Reverse Recruiter

A job-search agent that works for the candidate instead of the employer. It reads every job posting you save in full, checks it against an explicit, written model of what you want, and gives you a ranked list where every score is explained, including the caveats a quick phone skim would miss.

The model isn't written once and left alone. Each round, the agent compares three sources (the jobs you saved, what your resume and profile can prove, and short calibration conversations about what you actually mean), asks a few targeted questions where they disagree, and turns your answers into recorded rules. The next round scores more accurately. Along the way it keeps a skills-gap tally, suggests better searches, and builds application and interview material from a single, fact-checked record of your career.

It is built with [Claude Code](https://claude.com/claude-code): plain Python for the mechanical steps, Claude for the judgment steps, and you for every decision.

> **Terminology.** *Calibration* is the agent asking you short questions to tune its criteria in both directions: **qualifiers** (what makes a job good) and **disqualifiers** (what makes it bad, from a dealbreaker to a score penalty). *Interview* is reserved for employer interviews.

---

## Why

Job boards optimize for applications, not fit. A saved job is usually a 20-second judgment on a phone: the title, the location, maybe the platform's own match line. The details that decide whether a job is worth your time are further down: an in-office expectation inside a "remote" role, a required degree in a field you don't hold, 40% travel, a residency restriction near the bottom.

Reverse Recruiter treats every save as a *candidate*, not a preference, and does the full read for you.

## What it does

**1. Screens every word, not just the headline.** For each saved posting it extracts role, level, pay, work arrangement, location, travel, requirements, industry and 1st-degree connections, then:
- **excludes** jobs that hit a dealbreaker, and says which one;
- **scores** the rest: a 0–100 fit judgment plus visible adjustments (core-domain bonus, travel scale, scored negatives, connection bonus), so a strong fit with bonuses can total above 100, and sorts them into tiers A–D;
- **flags "looks good, but…"** details a skim misses.

**2. Learns your criteria, continuously.**

| Source | What it tells the agent | Weakness on its own |
|---|---|---|
| Saved jobs | Candidates worth a full read | Not a preference signal: saves are quick and unread |
| Resume and profile | What you can prove | Compressed; misses things you've done |
| Calibration answers | What you actually mean | Only covers what's been asked |

Where they disagree, the agent asks instead of guessing, and each answer becomes a standing rule with its reason in a changelog, so it's never asked again.

**3. Improves your materials as a side effect.** Comparing what jobs ask for with what your profile shows separates *real gaps* (a ranked development list) from *hidden strengths* (things you've done that your resume doesn't say), which become resume and profile wording.

**4. Finds jobs you didn't save.** Top-ranked jobs seed ready-to-run searches, and "similar jobs" become leads.

**5. Helps you apply and interview.**
- **Application kits** ("prep <company>"): a *stretch review* first (each requirement you don't clearly meet, and what a cover letter would have to ask the employer to accept), then a fit map, a one-page cover letter, a tailored resume copy with Word tracked changes, and a log.
- **Apply queue:** what to apply to next, what's in progress, and an outcome funnel from qualified target to offer.
- **Staleness gate:** confirms a posting is still open before any kit work or application.
- **Interview primer:** every requirement rated Have / Partial / Gap with evidence, plus likely questions grouped by interviewer.
- **Interview loop:** debriefs, thank-you notes, follow-up timers, and lessons that feed the next primer.
- **Role Explorer:** for a role found through a recruiter, it finds the real posting, maps the team and the role, and writes an interview-prep brief.

Every claim in an application comes from one career record (`career-master.md`), so nothing is invented and gaps are named, not papered over.

## The loop (each round)

```
 new saved jobs ──► extract ──► score against criteria ──► ranked report
   (PDFs)            (script)     (full read, explained)     + "looks good, but…"
                                        │                    + leads + skills gap
                                        ▼
                          mismatches & open questions
                                        │
                                        ▼
                     calibration (only what's new)
                                        │
                                        ▼
               criteria updated (with reasons)  ──► next round scores better
                 removals logged with the reason     resume wording improves
                                                     searches tuned by yield
```

The round ends with a **re-screen** (every current job against the latest rules), funnel metrics, a triage-precision check, the triage-mode signals, a repost watch, and the report.

## Results from the author's own search

Seven rounds over about a week, several hundred listings, shown **per 100 job listings processed** (raw volume says more about the backlog than about the system):

| Stage | Per 100 listings |
|---|---|
| Job listings processed (search results seen, plus jobs saved outside a search) | 100 |
| Baseline match (kept in a quick triage, mostly on the platform's own match line) | 41 |
| Agent deep-fit review (postings saved and read in full) | 21 |
| Qualified targets (on the ranked list after calibration and re-screen) | 9 |

What the numbers taught, and what changed because of them:
- **A strong platform match isn't a fit.** In one round, about half the postings that passed the platform's "strong match" line hit a written dealbreaker on a full read. That's the gap this tool closes.
- **New rules per 100 listings fall each round** (from about 12 to about 4), which is the signal that the criteria are settling. The agent uses it to suggest when to move from high-touch *Catch-up* triage to low-touch *Keep-up*.
- **The agent's own triage calls are measured.** Its "likely DQ" calls agreed with the human decision 28 of 29 times; its "likely keep" calls only 2 of 7, and it hedged on more than half the cards. Those misses became explicit calling rules (commit to a lean, treat titles that point at a dealbreaker as lean DQ). See `engine/precision.py`.

## How it's built

| Who | Does what |
|---|---|
| **Code** (Python, `engine/`) | The mechanical steps: reading PDFs, tracking what's processed, the location radius, re-screen flags, funnel metrics, reports, the apply queue, timers. Runs without an LLM. |
| **Claude** (in Claude Code) | The judgment steps: reading each posting in full, scoring, writing caveats, calibration, resume and profile wording, application kits, primers. Rules for these are in `engine/prompts/` and `CLAUDE.md`. |
| **You** | Saving jobs, answering calibration questions, approving every criteria change and removal, and everything outward-facing: applying, messaging, editing your profile. |

Data and engine are separate. The engine never contains personal data; your data lives in its own folder (default `my-data/`, git-ignored) and every script takes `--data <folder>`, or reads the folder from the `REVERSE_RECRUITER_DATA` environment variable when it's set (handy when your data lives outside the repo; set it once, for example in Claude Code's project settings). A pre-commit hook runs `engine/privacy_scan.py` so personal details can't be committed by accident.

## What it deliberately doesn't do

- **Touch job sites automatically.** It works from pages you save yourself (PDFs) and results you copy by hand. No scraping, no browser automation, no logging in on your behalf. Many job sites prohibit automated access in their terms; this tool is designed to stay on the right side of that.
- **Act on your behalf.** No applications, messages or profile edits are sent by the tool. It drafts; you send.
- **Treat a save as a verdict.** Preferences come from calibration, not from what you saved.
- **Learn everything from a rejection.** Only the specific disqualifying reason is kept, as a general rule.

## Quick start

```bash
git clone <this repo> reverse-recruiter
cd reverse-recruiter
pip install -r requirements.txt
cp -r sample-data demo-data                                    # a scratch copy of the fictional candidate
python -B engine/build_report.py --data demo-data --round 2    # rebuild the ranked report
python -B engine/pipeline.py queue --data demo-data            # what to apply to next
python -B engine/interviews.py --data demo-data due --soon 14  # follow-ups owed
```

Run the test suite (standard library only; pytest runs it too):

```bash
python -B -m unittest discover -s tests
```

The sample is a fictional candidate (two rounds, 11 invented postings, one recruiter job with a kit and an interview in progress), generated by `scripts/make_sample_data.py`. Its reports are already in `sample-data/2-reports/`.

Then open the folder in Claude Code and follow [docs/setup.md](docs/setup.md) to create your own data folder and run your first round. The full process is in [docs/how-it-works.md](docs/how-it-works.md).

**Your data goes in by hand.** The agent never connects to LinkedIn (automating a logged-in session is against LinkedIn's terms), so you start it by saving your resume, your LinkedIn profile, search results and job pages yourself. [docs/capture-workflow.md](docs/capture-workflow.md) covers what to capture and how, step by step, with Chrome keystrokes.

## Repository layout

```
reverse-recruiter/
├─ README.md            this file
├─ CLAUDE.md            working rules for Claude in this project
├─ requirements.txt
├─ docs/
│   ├─ capture-workflow.md  saving your resume, LinkedIn profile, searches and jobs by hand (Chrome + keystrokes)
│   ├─ how-it-works.md  the round, the learning loop, and every feature in detail
│   └─ setup.md         install, create your data folder, run your first round
├─ engine/              Python scripts (no personal data)
│   ├─ paths.py            where every file lives (one place to change)
│   ├─ extract.py          saved job PDFs → structured job records
│   ├─ ingest_results.py   pasted search results → triage cards
│   ├─ ingest_external.py  a job from anywhere (recruiter document, other site) → a job record
│   ├─ triaged.py          skips listings already decided; blocklist confirm; repost watch
│   ├─ searches.py         criteria → ready-to-run search links
│   ├─ sweep.py            backlog sweep → searches that bring removed jobs back to dismiss
│   ├─ rescreen.py         flags jobs a newer rule may hit
│   ├─ build_report.py     scores + caveats → ranked report
│   ├─ metrics.py          search funnel and time per round
│   ├─ precision.py        how often the agent's triage call matches the decision
│   ├─ modes.py            Catch-up / Keep-up triage modes and when to switch
│   ├─ pipeline.py         application steps → apply queue + outcome funnel
│   ├─ staleness.py        is the posting still open?
│   ├─ primer.py           interview primer: requirement draft and completeness check
│   ├─ connections.py      connection levels (recommendation / plus / neutral) → network points
│   ├─ prep_pdf.py         interview prep → phone-friendly PDFs, a combined master and an anonymized copy
│   ├─ interviews.py       interview rounds, debriefs, thank-yous, follow-up timers
│   ├─ tailor_resume.py    tailored resume copy with Word tracked changes
│   ├─ remove_job.py       remove a job, keep the reason
│   ├─ locations.py        offline distance check for hybrid/on-site jobs
│   ├─ linkedin_project.py / linkedin_images.py   optional: publish your funnel per 100
│   ├─ privacy_scan.py     checks shareable files for personal details
│   └─ prompts/            rules for the judgment steps
├─ sample-data/         a fictional candidate, so everything runs end to end
├─ tests/               end-to-end, file-safety, robustness and privacy tests (unittest)
└─ scripts/
    ├─ make_sample_data.py   rebuilds sample-data/ (all content invented)
    └─ hooks/pre-commit      the privacy check on every commit
```

## Status and roadmap

**V1 (this repo):** an interactive, manual-input system run through Claude Code. All features above are built and in use.

**V2 (planned):** the same scoring core with automated inputs, in this order: job-alert emails, company job boards and aggregator APIs (Greenhouse, Lever, Ashby; JSearch, Adzuna), then an opt-in browser layer, only where a site's terms allow it. Scheduled runs through the Claude API, a daily digest, and calibration as a review queue.

## Author

Built by David Beeler, a product manager, as a working tool for a real job search and a public example of designing an AI agent around explicit, explainable criteria.

## License

MIT. See [LICENSE](LICENSE).

LinkedIn is a trademark of LinkedIn Corporation. This project is independent and is not affiliated with, sponsored by or endorsed by LinkedIn or any job site. It reads only pages you save yourself.
