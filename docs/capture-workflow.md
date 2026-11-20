# Capturing your data from LinkedIn (Chrome + keystrokes)

Reverse Recruiter never connects to LinkedIn. Everything the agent knows about you and the jobs comes from files you save by hand. That's deliberate: automating a logged-in LinkedIn session is against LinkedIn's terms, while reading a page and saving it as you would for yourself is not. So the first step of the process, and every round after it, is manual capture.

**This guide shows one way to do it, not the only way.** The steps use Chrome on Windows and mostly keystrokes, because that combination has proven fast and reliable. Everything here can also be done with the mouse (click each "…more", use the browser's Print menu), in another browser, or with your own mix of the two. The method doesn't matter; the result does. As long as what you save is **complete** (every "…more" expanded, every section captured), **readable** (a PDF with real text, not a picture of the page) and **in the right folder with the expected name**, the agent's results are the same however you saved it.

Whatever you use, do it yourself: **don't record the keystrokes as a macro or script**, which would make it automation again.

## What you capture, and why

The agent works from two sources of truth about **you**, and two inputs about **jobs**: what your searches turn up, and the postings you keep.

| # | Input | What you save | Where it goes (in your data folder) | What the agent uses it for |
|---|---|---|---|---|
| 1 | **Your resume** | `.docx` and `.pdf` | `4-profile/resume/` | First pillar: your titles, dates and accomplishments as you present them to employers |
| 2 | **Your LinkedIn profile** | The main profile page, plus one PDF per "Show all →" section | `4-profile/linkedin/` (recommendations: `7-recommendations/`) | Second pillar: the fuller picture (About, every role, projects, volunteering, skills, recommendations) |
| 3 | **Search results** | The job cards from each search, copied as text | `1-inbox/search-results/` | Triage, and the feedback loop on the searches themselves: each search's yield (found, kept, scored high) shows which searches to tune or retire |
| 4 | **Job pages** | One PDF per job you keep, plus a `_people` PDF when you have a 1st-degree connection there | `1-inbox/job-pdfs/` | Full review, scoring, ranking and application kits |

From 1 and 2 the agent builds your profile and a **career master**, which is the only source of claims it will make on your behalf in applications. The more you give it about your experience and accomplishments, the better it can judge which jobs truly fit.

## Terms used

| Term | What it means |
|---|---|
| Job search page | The split-screen results page (`linkedin.com/jobs/search…`), with the job list on the left and details on the right |
| Results header | The line above the first card, for example "99+ results · United States". It is plain text, not a link |
| Left pane (job list) | The scrolling list of job cards. It scrolls separately from the rest of the page |
| Job card | One entry in the left pane: logo, title, company, location, pay, posted date |
| Placeholder card | A card LinkedIn has not filled in yet. It loads only when it scrolls into view (lazy loading) |
| Right pane (job details pane) | The detail view for whichever card is selected on the left |
| Job page | A single job opened full-page (`linkedin.com/jobs/view/…`), reached by clicking the job title in the right pane |
| "…more" link | The link that expands a shortened block of text (a job description, a profile's About section, one role in Experience) |
| "Show all →" link | The link at the bottom of a profile section that has more entries than fit. It opens that section on a page of its own |
| Anchor click | A single left-click on plain text or white space. It sets where a text selection starts, and it tells Chrome which pane your keystrokes scroll |
| Shift + click | Extends the selection from the anchor to the spot you click |

## Two moves you'll repeat

### Expand every "…more" with Find

1. Press **Ctrl + F**, type `...more`, and press **Enter**. The first "…more" is highlighted.
2. Press **Esc**, then **Enter** to click it.
3. For the next one, press **Ctrl + F**, then **Enter** (Find remembers what you typed), then **Esc**, **Enter**.
4. Repeat until Find shows no more matches you care about.

### Save the page as a PDF

1. Press **Ctrl + P** to open the Print dialog.
2. **The first time:** set Destination to **Save as PDF** (not "Microsoft Print to PDF", which saves pictures of text the agent can't read), press **Enter**, choose the folder, and press **Enter**.
3. **After that:** Chrome remembers the destination and the folder, so it's just **Enter**, **Enter**.
4. **Keep the default file name** unless a step below says to add a suffix. The engine relies on it.
5. If a "file already exists / replace?" prompt appears, **don't replace the file**. See the step you're on for what to name it.

Chrome remembers the **last folder you used**. Profile pages and job pages go to different folders, so the first save after switching between them needs the folder chosen again.

## 1. Your resume

Copy your current resume into `4-profile/resume/`, as a `.docx` (the agent edits copies of it, with tracked changes, for each application) and a `.pdf`. This is one of the two pillars everything else is checked against, so use the version you'd send an employer today.

## 2. Your LinkedIn profile

This is your first real navigation of LinkedIn for capture, and it's worth doing thoroughly: your profile page leads to every detail the agent can use to build the most complete picture of you as a candidate.

**How profile sections behave:**
- Some sections have a single "…more" expansion, like **About** (unless it's very short).
- Others list several entries, and each entry may have its own "…more": **Experience**, **Projects**, **Volunteering**, **Recommendations**, and so on.
- A section with more entries than fit shows a **"Show all →"** link at the bottom. Those sections need a separate save, because of how Chrome's Save as PDF works: it saves only what's on the current page.

> **The gotcha:** clicking *any* "Show all →" link takes you away from the main profile page. When you come back, every "…more" you expanded has collapsed again and you have to start over. **Save the main profile page first, before opening any "Show all →" section.**

### 2a. The main profile page

1. Open your profile page and scroll down through it.
2. Expand every "…more" in the sections that **don't** have a "Show all →" link at the bottom (About, and any section with one or two entries). Use [Expand every "…more" with Find](#expand-every-more-with-find). Leave the "Show all →" sections for later.
3. [Save the page as a PDF](#save-the-page-as-a-pdf) into **`4-profile/linkedin/`**.
4. Keep Chrome's default file name, **`Firstname Lastname _ LinkedIn`**. Don't customize it: every section save below starts from that same name, so keeping it makes them faster.

### 2b. Each "Show all →" section

For example, if you've held more roles than the Experience summary on the main page shows:

1. Click **Show all →** at the bottom of the section. It opens on a new page.
2. Expand every "…more" in that section's entries (Find, as above).
3. Press **Ctrl + P**, then **Enter**.
4. **At the file name, don't press Enter yet.** Chrome offers the same name it used for the main profile page, and saving over it would replace your main profile PDF. Click at the end of the name and add a section suffix, so it reads **`Firstname Lastname _ LinkedIn_experience`**. Then press **Enter**.
5. Go back and repeat for each "Show all →" section: `_projects`, `_volunteering`, `_skills`, `_certifications`, `_courses`, `_honors`, and so on.

**Recommendations** work the same way, with two tabs, **Received** and **Given**. Save each one into **`7-recommendations/`** (not `4-profile/linkedin/`) as `Firstname Lastname _ LinkedIn_recommendations-received` and `…_recommendations-given`. A 1st-degree connection you've exchanged a recommendation with counts for more when jobs are scored (see [how-it-works.md](how-it-works.md)).

## 3. Search results

The agent builds your LinkedIn searches (saved in `2-reports/search-links.md`). Open one, then:

**Before copying:** check the filter chips (Remote or your local radius, experience level, date posted, sort by most recent) and note the result count in the results header; the agent records it.

1. Click the far-left character of the **first card's job title**. The card shows as selected.
2. Press **Shift + Tab** once and release.
3. Press **Ctrl + End** (on laptops where Home and End share keys, **Ctrl + Fn + End**). The left pane jumps to the bottom and every placeholder card loads.
4. **Shift + click** in the white space at the bottom-right of the last job card.
5. Press **Ctrl + C**.
6. Paste into a `.txt` file in `1-inbox/search-results/` with **Ctrl + Shift + V** (plain text, without logos, links or highlighting).
7. Check the paste: the first line should be the first card's job title.
8. For more pages of results, go to the next page and repeat, pasting each page below the last, in order.

**Never Shift + click on a job title.** Titles are links, and Shift + click on a link opens it in a new window.

`engine/ingest_results.py` turns the pasted text into triage cards. You then triage with the agent and **save** the keeps on LinkedIn. Each run is also recorded against its search, so over the rounds the agent can tell which searches find good jobs and which only add noise, and suggest changes.

**Other ways to capture results** (a screen recording read by another model, a browser extension, an export tool) work too, as long as they produce a `.csv` or `.json` with `title`, `company` and `location` for each job; `ingest_results.py` takes that directly.

## 4. Job pages

### 4a. Save each kept job as a PDF

Start on the **job page** (the full-page job description). Usually you'll follow the direct link the agent gives you; you can also click the job title in the right pane of a search.

1. Expand the descriptions with Find: the first "…more" is **About the job**, the second is **About the company**. If About the company is short, it has no "…more"; skip to step 3. Some pages have one or two more; expand them if you like, but the job and company text is what matters.
2. Check that the description doesn't end in "…more".
3. [Save the page as a PDF](#save-the-page-as-a-pdf) into **`1-inbox/job-pdfs/`**, keeping LinkedIn's default name.
4. If the file name already exists (the same title at the same company), don't replace it. Add **`_possdup`** to the new one's name (`_possibleduplicate` also works). The agent checks whether it's the same job or a repost.

### 4b. Capture your connections there ("People you can reach out to")

If the job page shows a **1st-degree connection** at the employer, capture it. A 1st-degree connection adds points to the job's score, and more if you've exchanged a recommendation with that person, and the agent can only count connections it can see in a file.

1. On the job page, find **People you can reach out to**. It's almost always a **"Show all →"** link.
2. Open it so the list of connections shows.
3. Save as a PDF into `1-inbox/job-pdfs/`, adding **`_people`** to the end of the default name.

Only 1st-degree connections count; alumni and 2nd-degree contacts don't.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Ctrl + End scrolls the whole page, not the left pane | Keyboard focus isn't in the left pane | Redo section 3, steps 1–2 |
| First card's title is missing from the paste | The first click missed the title's far-left character | Redo section 3, steps 1–2 |
| A new window opens | Shift + click landed on a job title, which is a link | Close that window and Shift + click on white space |
| Some cards in the middle paste as blanks | LinkedIn unloaded cards that scrolled out of view | Before selecting, press **Ctrl + −** to zoom to about 50% so all cards stay on screen. **Ctrl + 0** resets |
| Paste includes logos, links or blue highlighting | Pasted with Ctrl + V | Paste with Ctrl + Shift + V, or paste into Notepad first |
| A description ends with "…more" | A "…more" link wasn't expanded | Expand it with Find, then print again |
| Your profile's "…more" sections collapsed | You opened a "Show all →" section before saving the main page | Expand them again and save the main page first (2a) |
| A PDF landed in the wrong folder | Chrome reused the last folder | Move the file, and pick the folder at the next save |
| The PDF has no selectable text | Saved with "Microsoft Print to PDF" | Save again with Destination **Save as PDF** |

## Keyboard reference

| Keys | What they do |
|---|---|
| Ctrl + F, Enter, Esc, Enter | Find the next "…more", close Find, click the link |
| Ctrl + P, Enter, Enter | Print → Save as PDF → save with the remembered folder and default name |
| Ctrl + End / Ctrl + Home | Jump to the bottom or top of the pane that has focus (add Fn on keyboards where Home and End share keys) |
| Shift + Tab | (After clicking the first card) puts keyboard focus in the left pane, so Ctrl + End scrolls the job list |
| Ctrl + C, Ctrl + Shift + V | Copy, then paste as plain text |
| Ctrl + − / Ctrl + 0 | Zoom out / reset zoom |
