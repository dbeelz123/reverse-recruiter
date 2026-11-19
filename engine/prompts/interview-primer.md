# Interview primer: rules for the judgment step

Trigger: "primer <company>", or a recorded `interview` step with no primer yet. Goal: before an employer interview, the candidate knows exactly where they meet each requirement, where they don't, and what they'll probably be asked.

## Inputs
1. `python engine/primer.py draft <job> --out <scratchpad>/primer-draft.md`: the posting's requirement sections split into items (R = required, N = nice-to-have, D = duties), candidate career-master bullets for each, the review's gaps and caveats, and any stretch-review answers. **Candidates are suggestions from word overlap, not evidence.** Read each one before using it.
2. The full posting (`posting_text` in the job record, or the original file for an external job). The draft flags sections a PDF collapsed and sections that ran into boilerplate: fix those by hand.
3. `career-master.md`: the only source of claims. Titles, dates and timeline never change.
4. The kit folder, if one exists: `log.md`, an earlier `fit-map.md`, `interview-prep.md` (Role Explorer brief), the stretch review.
5. What the candidate has said about the interview: rounds so far, who is on the panel, what the recruiter or hiring manager said about the role.

## Output 1: `fit-map.md` (in the kit folder)
Open with the date, the interview it's for, the source of the requirements, and which resume version the employer holds.

Three tables: **Required**, **Nice to have**, and **What the duties ask of you**. Required and nice-to-have rows use IDs `R1…` and `N1…` (the check reads them) and these columns:

| # | Requirement | Rating | Your evidence | Where they can see it | How to say it |

- **Rating**, in bold: **Have** (clear, citable evidence), **Partial** (real evidence, but adjacent or smaller than asked), **Gap** (not in the history). When unsure between two ratings, pick the lower one and say why.
- **Your evidence:** specific, from the career master only: the product, the decision, the number. Never a claim the master doesn't hold; if the master is silent, it's a Gap.
- **Where they can see it:** the resume version the employer has, the LinkedIn profile as published, or "not written down anywhere they can see" (then say it in the room).
- **How to say it:** one line. For a Gap: name it plainly, then the bridge (the closest real evidence, or how the candidate would close it). Never paper over a gap.
- Merge near-duplicate posting items into one row, but don't drop any; `check` compares row counts with the posting.

End with a **Summary**: counts by rating, the strongest match, what isn't written down anywhere, and any resume-timeline caution.

## Output 2: likely interview questions
A section headed `## Likely interview questions` in `interview-prep.md` (create a lean `interview-prep.md` if there's no Role Explorer brief). Numbered tables with `| # | Question | Use |`, where "Use" points to the answer material (a story, a fit-map row, a section).
- **Group by interviewer:** each group on the panel gets its own table (e.g., the hiring manager's program side, the domain experts, the recruiter), plus **Behavioral and fit**.
- **Sources of questions, in order:** each Required row (a "tell us about a time" probe), each Gap and Partial (the "you don't have X" probe), the duties ("how would you…"), what the review's caveats imply, and the standard set: why this role, walk us through your background, how you use AI in your work, what questions do you have for us.
- **15 or more questions**, plus two or three curveballs worth one practice run.
- Add a resume-timeline question if the employer's resume version differs from the current one.

## Company and role primer
If there's no Role Explorer brief, add a short section above the questions: what the company does, the team the role likely sits in, two or three recent public facts worth knowing (from public sources, with links), and five questions to ask them. Mark each finding as confirmed or inferred. Research people only from full names the candidate gives; never guess identities from partial names.

## Finish
1. `python engine/primer.py check <job>` must print **PRIMER COMPLETE**. Read any notes it prints (dropped items, gaps without a handling plan).
2. Add a row to the kit's `log.md` timeline: "Interview primer prepared".
3. In chat: the rating counts, the two or three gaps most likely to come up and how to handle each, and the file paths.
