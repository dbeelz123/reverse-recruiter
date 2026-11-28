# How it works

This is the full process: the data folder, the round, the learning loop, triage, reports, and each feature for applying and interviewing. Setup is in [setup.md](setup.md); the working rules Claude follows are in [CLAUDE.md](../CLAUDE.md).

## Runtime model

- **Mechanical steps** are plain Python in `engine/` and run anywhere, without an LLM.
- **Judgment steps** (reading a posting in full, scoring, calibration, writing) are done by Claude in Claude Code, following the rules in `engine/prompts/` and `CLAUDE.md`. They are written so a later version can call the same prompts through the Claude API on a schedule.
- **Calibration** is conversational by nature and stays a conversation.
- **Your decisions** stay yours: every criteria change, removal, application and message.

## The data folder

All personal data lives in one folder, outside the engine (default `my-data/`, git-ignored; any folder works with `--data <folder>`, or set `REVERSE_RECRUITER_DATA` to it once; `--data` wins when both are given). Every script gets its paths from `engine/paths.py`. It's grouped by what you do with it:

```
<data>/
  1-inbox/        YOU DROP FILES HERE
    job-pdfs/          saved job postings, one PDF each (they stay here while the job is saved)
    search-results/    pasted search-result pages (.txt) for triage
    tracked-jobs/      the saved-jobs list (printed to PDF, or pasted), to check the project matches your saves
    role-explorer/     a title + job description to research
  2-reports/      YOU READ THESE: the round report, search links, apply queue
  3-applications/ one folder per application kit
  4-profile/      WHO YOU ARE: resume/, profile exports, career-master.md, voice-guide.md
  5-criteria/     YOUR RULES: spec.json, changelog.md, searches.json, places.json,
                  connections.json (your call on each connection: plus or neutral)
  6-system/       MACHINE DATA: jobs/, reviews/, calibration/, search-runs/, ledger and tallies
  7-recommendations/  (optional) one folder per person you've exchanged a LinkedIn recommendation with
                      (<first-last>/received/recommendation.md, given/final.md); a connection with one scores
                      spec.json -> scoring.network.recommendation_points instead of the plain connection bonus
  private-terms.txt   (optional) terms the privacy scan must never find in shareable files
  8-mentor-advice/, 9-learning/   (optional, yours) no script reads them; the pre-commit hook guards them
                      like the folders above, as it does any folder laid out this way
```

Each folder keeps only working files; superseded ones move to an `archive/` subfolder, which scripts ignore.

## Criteria: three tiers

`5-criteria/spec.json` is the written model of what you want; `changelog.md` records every change with its date, source and reason.
- **Dealbreakers** exclude a job, and the reason is shown.
- **Negatives** lower the score without excluding (e.g. heavy travel, a required growth-metrics track record).
- **Positives** raise it (e.g. core domain, a 1st-degree connection at the company).
- **Work arrangement:** remote anywhere; hybrid and on-site only within a radius of a home point (`machine_rule.hybrid_onsite_center`, `radius_miles`), checked offline against your own city table in `places.json`.
- **Eligibility baseline:** what you meet by default (e.g. work authorization). Reviews list every requirement beyond it, quoted, for you to judge.
- **Connections:** only 1st-degree connections count; they are the strongest positive (a route around the applicant tracking system), and a job with one is never removed automatically. Optionally they score by level (`connections.py`, on when `spec.json` → `scoring.network` has `neutral_points`): someone who has exchanged a LinkedIn recommendation with you scores highest, someone you'd ask for a referral ("plus") next, and someone you wouldn't ask ("neutral") least, since a recruiter who sees the connection may still ask them or give your application a second look. Calibration asks about each new connection, and your answer goes in `connections.json`. The best connection at a company counts; levels don't add up.

## The round

A round processes new saved jobs and re-ranks everything. In order:

1. **Triage** (when working from search results): paste the results into `1-inbox/search-results/`, then `ingest_results.py` → cards, and `triaged.py check` skips what's already decided (a listing DQ'd before comes back for a fresh look if its salary or location is new; a listing from a blocklisted company is shown with the blocklist entry and reason for you to confirm, never dropped silently; a company blocked before that no blocklist entry matches now, because you took it off or the card shows another name, is flagged too). Claude shows batches with its own call on each card; you open each, decide keep or DQ, and save the keeps. The triage ends with a **save check** (`triaged.py keeps`).
2. **Extract:** `extract.py` turns new PDFs into job records (only new or changed files). It also flags duplicate saves, possible reposts, and a job saved again after it was removed ("PREVIOUSLY REMOVED", with the earlier reason; Claude asks before reviewing it again). `triaged.py match-saved` links saves made outside the batches to the run.
3. **Review** (Claude): every new posting read in full against `engine/prompts/review-rubric.md`: score, tier, positives, caveats, gaps, eligibility.
4. **Calibration** (you and Claude): a few questions, only about what's new: conflicts between sources, uncertain signals, proposed disqualifiers. Approved answers become rules in `spec.json` and `changelog.md`.
5. **Search insights:** Claude looks across the round for patterns (level, domain, employer type, location) and proposes search changes. You approve each.
6. **Resume and profile review** (optional, offered every round): things calibration uncovered that your documents don't show yet.
7. **Re-screen:** `rescreen.py` flags every current job a rule may now hit (jobs already excluded, tier X, are skipped), including hybrid and on-site jobs outside the current radius or in a place it can't locate; Claude judges each flag. Real dealbreakers go through the **removal prompt**: Claude asks before anything is removed, and `remove_job.py` keeps a one-line tombstone with the reason. A job with a 1st-degree connection is never removed automatically: `remove_job.py` stops and names the connection, and runs only with `--confirm-connections` after the user says yes.
8. **Metrics:** `metrics.py --round N` records the search funnel and time per stage.
9. **Triage precision:** `precision.py --round N` compares the agent's calls with your decisions; new miss patterns become calling guidance.
10. **Mode signals:** `modes.py signals` reports whether the system looks settled enough to switch triage modes.
11. **Repost watch:** `triaged.py reposts` writes `2-reports/repost-watch.md`: listings that never go away (possible pipeline or ghost postings), listings that disappear and come back, saved jobs listed again after removal, pay that changed, and companies that relist often. It only reports patterns; nothing is skipped or removed because of it.
12. **Report:** `build_report.py --round N` ranks **every** current job, old and new, with caveats, connections, leads, the skills gap and the funnels. The previous report moves to `archive/`.

## Design principles

- **Inputs are noisy.** A save is a quick check of the title, location and the platform's match line, without reading the description. So a save is a candidate, never a preference signal; criteria come from calibration, reviews and removal reasons.
- **Full-text review of every posting.** Buried details decide fit: work arrangement, location, travel, clearance or citizenship, contract vs. full-time, salary, industry and customers.
- **"Looks good, but…"** Every ranked job shows its score, the reasons and the caveats a skim would miss.
- **Learn the reason, not the job.** When a job is removed, only the specific reason is kept, as a general rule ("required CS degree = dealbreaker"); the rest of the job teaches nothing.
- **One home per rule.** Criteria live only in `spec.json`; the process lives here; how Claude works lives in `CLAUDE.md`.

## Triage modes: Catch-up and Keep-up

| | Catch-up (backlog, setup) | Keep-up (routine) |
|---|---|---|
| Goal | Clear the backlog; build the rules that make screening reliable | Spot anything new worth a look, with the least effort |
| When | First use, after a long gap, after a big criteria change | Backlog under control; any cadence |
| Your involvement | High: interactive, explained, in-depth calibration | Low: confirm the agent's pre-sort; calibration only on new cases |
| Searches | Wide windows, exploratory searches welcome | Only tuned searches, windows matched to the cadence |
| Output | A full round each time | A short digest per check-in; the full round weekly |

The mode lives in `5-criteria/searches.json` → `mode`. A new user starts in Catch-up with a short setup interview (goal, lookback, pace, what still feels fuzzy). The agent **asks** before switching and never switches on its own. It asks when volume is met and at least 2 of 4 stability signals hold: fewer than 1 new rule per 100 search cards for two rounds; its triage calls match yours 90% of the time; 70% of a run's cards are already decided; a steady keep rate. In Keep-up it suggests a short Catch-up burst after a long gap or when drift shows.

## The platform's match line: two scales

LinkedIn shows a match line on each job's page (a search card doesn't show it), and triage leans on it. What it says depends on the account, so the save rule below is written for both. The wording is LinkedIn's as seen in November 2026; it may change.

| Account | What the page says | Recorded as `linkedin_match` | Usual triage decision |
|---|---|---|---|
| Free | "Your profile and resume match the required qualifications well" | `well` (a "strong match") | Save |
| Free | "You match some of the qualifications" | `some` | DQ |
| Free | "You are missing some qualifications" | `missing` | DQ |
| Free | "Job match summary not available" | `not available` | No signal: decide on the posting itself |
| Premium | "You'd be a top applicant" | `top` | Save |
| Premium | "Job match is high, we can help you stand out" | `high` | Save |
| Premium | "Job match is medium, review match details" | `medium` | DQ |
| Premium | "Job match is low, review match details" | `low` | DQ |

- **The two scales are not the same measurement.** The free line has three levels and Premium has four, and nothing here assumes that a free "strong match" equals a Premium "high" or "top applicant". If your account changes mid-search, expect the share of saves to shift, and say so in the round's notes.
- **The decisions are defaults, and you can make them more or less restrictive.** They are the ones this project was built with. Your own rule is the text in `5-criteria/searches.json` → `triage_flow`: save only "top applicant", say, or also look at "matches some". It is a written rule that you and Claude follow in triage, not a setting a script enforces.
- **Either way it is a pre-screen.** A save is a candidate, never a verdict: a top match still gets the full read, and about half of one round's strong matches hit a written dealbreaker.
- **Where it is recorded:** `linkedin_match` on the run's row for a search card. For a save made from LinkedIn's recommendations (no card), the strength is asked for only when the job passes review, and goes on the review as `premium_match`.
- **The match gate:** a DQ made on the match line (`some`, `missing`, `medium` or `low`) is something the agent couldn't have seen on the card, so `precision.py` reports agreement with and without those cards. That list is fixed in the code: under a stricter rule of your own, a DQ on `high` counts as an ordinary disagreement with the agent's call.

## The agent's triage calls, measured

Before you decide each card, Claude records its own call: `likely keep`, `lean keep`, `possible: <missing fact>`, `lean DQ`, or `weak` (likely DQ). `precision.py` compares those calls with your decisions, with and without the cards decided by the platform's match line (which a search card doesn't show), follows your keeps to their final tier, and lists every miss with both sides' reasons. Miss patterns become explicit calling guidance in `searches.json` → `triage_flow` (how to call, never criteria). In Keep-up, these calls become the pre-sort you confirm in bulk.

## Reports

- **Ranked list:** every current job with score, tier, work arrangement and distance, connections, and its caveats, plus a grade-band image (A/B/C/D). A job with no review yet is listed under "Not reviewed yet", with no score, rather than left out.
- **Search funnel:** job listings processed → baseline match (kept in triage) → agent deep-fit review (saved and read in full) → qualified targets (ranked), per round and cumulative, with an image.
- **Phone triage:** saves made straight from LinkedIn alerts on a phone, judged on LinkedIn's match signal alone, have no result cards behind them. Record them as one run file with `"triage_type": "phone"` and their job IDs in `saved_job_ids`; the funnel shows their listings and triage calls as unknown and leaves them out of the known totals and every per-100 number.
- **Recommendation saves:** saves from LinkedIn's job recommendations (not a search) have no result cards either. Record them the same way with `"triage_type": "recommendations"`; they are counted like phone triage and labelled apart in the funnel and mode tables.
- **Time per round:** active minutes per stage and per 100 listings, from timing events logged at each stage boundary.
- **Applications funnel:** qualified target → kit built → applied → employer response → interview → offer.
- **Leads:** similar jobs from saved postings, with search links, prioritized where you have connections.
- **Skills gap:** have / have but not on the resume / partial / missing, weighted by how often and how strongly top jobs ask, grouped into training tracks.
- **Triage mode:** progress toward the Catch-up goal and the stability signals.
- **Optional, public funnel:** `linkedin_project.py` and `linkedin_images.py` keep a public description and two images of your funnel in step, always **per 100 listings processed** and only updated when you say so.

## Applying

### Apply queue
Progress lives in a `pipeline` block on each job record. Stages: kit → applied → response → interview → offer, plus `outreach`, `hold`, and the end states `passed`, `rejected`, `withdrawn`, `closed`. A job in an end state goes back to an active stage only with `--reopen` (in `pipeline.py record` and `interviews.py schedule`). When you report a step, Claude runs `pipeline.py record` and rebuilds `2-reports/apply-queue.md`:
- **Due:** debriefs, thank-you notes and follow-ups owed now or in the next 3 days;
- **In progress:** with the last step and how long ago;
- **Apply next:** A and B jobs without an application, best first, each with whether it's still open and its next step;
- **Not applying:** with the reason.

### Staleness gate
Postings close without notice. `staleness.py` keeps each job's latest open check (`open_check`). Evidence comes from the saved PDF's posting date, the saved-jobs list (`staleness.py tracker`, which marks every listed job at once; print the list to PDF and jobs match exactly by the ID in each link, and a complete capture also lists project jobs that dropped off it; a copied-text paste still works, matched by title), or you confirming after opening the link. Before any kit work or application, Claude runs `staleness.py gate <job>`: **FRESH** (seen open in the last 3 days) or **CHECK FIRST**, with the link. A listing about a month old or more is CHECK FIRST even when the saved-jobs list shows it, until you confirm it yourself after opening the link; that confirmation passes the gate for 3 days, with the listing's age shown. A closed job goes through the removal prompt; nothing is removed automatically.

### Application kits
Say **"prep <company>"**.
1. **Stretch review first, in chat:** each requirement you don't clearly meet (required or preferred, the kind of stretch, how big), the closest real evidence, and what a cover letter would have to ask the employer to accept. You decide: build, build without that ask, or pass. Your answers are calibration input.
2. **The kit,** in `3-applications/<company-role>/`: a copy of the posting; a fit map (requirement → strongest evidence; gaps and how to handle each); a cover letter of about 250–350 words in your voice (`voice-guide.md`); a tailored copy of your working resume with Word tracked changes (author "Claude", one page) for you to review; and `log.md`.

Every claim comes from `career-master.md`; titles, dates and timeline never change, and the letter names only the gaps you chose to name.

### External jobs
A job from anywhere (a recruiter's document, another site) becomes a regular job record with `ingest_external.py` and runs through the same review, re-screen and report.

## Interviewing

### Role Explorer
For a role you're pursuing with only a title and a description, drop the description into `1-inbox/role-explorer/` and say **"explore <title>"**. Claude reads it in full, looks for the real posting, maps the likely team and its public work (marked confirmed or inferred, with sources), defines the role day to day and at 30/60/90 days, maps your fit from the career master, and prepares you for each interviewer group. People are researched only from full names you give, and only from public, professional information.

### Interview primer
Say **"primer <company>"** before any interview (the apply queue prompts for it).
1. `primer.py draft` splits the posting into Required, Nice-to-have and Duties items, suggests career-master evidence for each, and gathers what the project already knows.
2. Claude writes `fit-map.md` (every requirement rated **Have / Partial / Gap**, with evidence, where the employer can see it, and how to say it) and **likely interview questions** grouped by interviewer, by `engine/prompts/interview-primer.md`.
3. `primer.py check` must print PRIMER COMPLETE.

### Interview prep PDFs
Prep is written in Markdown in the kit and read on a phone as PDFs. `prep_pdf.py all <kit>` renders one PDF per packet, a combined master (each document on new pages), and an anonymized copy of the master for sharing as an example. The kit's `prep-pdf.json` names the packets, titles and subtitle, and its rules file says what to replace (literal or regex, applied in order; rules that matched nothing are reported). Nothing kit-specific is in the engine. Re-render after every edit, so the PDFs never lag the Markdown.

### Interview loop and follow-up timers
`interviews.py` records each round (`schedule`), the **debrief** you give afterwards (who was there, what they asked, what landed, what missed, signals, lessons), and the **thank-you notes** Claude drafts for you to send (due the day after). `interviews.py due` lists what's owed: debriefs, thank-yous, and follow-ups 7 days after applying, 5 after messaging a connection, and 5 after an interview with no news. `interviews.py lessons` collects every debrief and the questions actually asked, which feed the next primer.

## Finding more jobs

- **Search links:** `searches.py` turns `searches.json` into ready-to-run search URLs with the filters set (window, remote or local radius, exclusions). Searches are tuned by what they yield and what they teach; good ones become saved alerts.
- **Backlog-sweep cleanup:** after a wide, fast save whose jobs are mostly removed, `sweep.py` builds a few searches that name the swept companies and title families, so the unsaved (now "Viewed") jobs come back together and can be dismissed for good with the X on each card. That keeps them out of later searches.
- **Capturing results:** run a search, copy each results page by hand, and paste them into a `.txt` in `1-inbox/search-results/` (step by step, with Chrome keystrokes: [capture-workflow.md → 3](capture-workflow.md#3-search-results), which also covers your resume, profile and job pages). `ingest_results.py` also accepts a `.csv` or `.json` with `title`, `company`, `location` (optional: `salary`, `posted`, `status`, `network`) if you capture results another way; that choice and its terms-of-service implications are yours.

## Your profile

- `4-profile/career-master.md` is the only source of claims for applications: every bullet tagged by theme (migration, API, pricing, partners…) so the primer and kits can match bullets to requirements.
- `4-profile/voice-guide.md` is style only: how you write, with a table of your own edits to drafts, which is the strongest evidence of your voice.
- Resume edits are always made on a copy, with tracked changes, keeping one page. A version an employer already holds is never changed.
- Profile text (e.g. LinkedIn) is drafted as paste-ready blocks; you edit your profile by hand.

## Privacy

The engine and docs never contain personal data. `engine/privacy_scan.py` checks any path for the terms in your private list plus home-folder paths, email addresses and profile links (an image counts as a hit until you've checked it by eye and listed it in `.privacy-allow`); the pre-commit hook in `scripts/hooks/` runs it on everything staged and refuses to run without your list (see [setup.md](setup.md)).
