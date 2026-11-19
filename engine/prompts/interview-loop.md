# Interview loop: rules for the judgment steps

The script (`engine/interviews.py`) keeps the record and the timers. These are the parts that need judgment: the debrief conversation, the thank-you notes, and turning lessons into better preparation.

## When an interview is scheduled
1. `python engine/interviews.py schedule <job> --round R --date YYYY-MM-DD --with "..." --format "..."`. This also moves the pipeline to `interview` if it isn't there yet.
2. Run the staleness gate (`engine/staleness.py gate <job>`) and the primer check (`engine/primer.py check <job>`). If there's no primer, offer one ("primer <company>").
3. Before writing the primer, run `python engine/interviews.py lessons` and use what earlier interviews taught: questions that keep coming up go into the likely questions, and recurring misses become prep points.

## Debrief (as soon as possible after the interview, ideally the same day)
Ask a short set of questions in chat, one message, so the candidate can answer from memory while it's fresh:
1. Who was there (names and roles as shown on the call; full names only as the candidate gives them)?
2. What did they ask? List as many questions as they remember, roughly in order.
3. What landed: an answer, story or question that got a visible reaction?
4. What missed: a question they struggled with, something they wish they'd said, a gap that came up.
5. Signals and next steps: timing, the next round, anything said about other candidates, salary or contract terms.
6. Did anything come up that isn't in the career master (a fact about their own history they mentioned)? Facts go to the career master only after the candidate confirms them.

Write the answers as a JSON file in the session scratchpad with the keys `how`, `asked`, `landed`, `missed`, `signals`, `next`, `lessons`, `thank_you_to` (lists for asked, landed, missed, lessons, thank_you_to), then `python engine/interviews.py debrief <job> --round R --file <file>`. **Lessons** are short, reusable rules for the next interview ("lead with the decision, then the outcome; I rambled on the trade-off story"), not a summary of this one.

Then:
- Add a timeline row to the kit's `log.md` (round, date, who, one line on how it went, next step).
- Record any pipeline change the debrief reveals (`engine/pipeline.py record`: response, rejected, offer, withdrawn) and rebuild the queue.
- Update the primer for the next round: mark which likely questions were actually asked, add the ones that weren't predicted.

## Thank-you notes
Draft one per person in `thank_you_to` (or one to the group when the candidate prefers), in `3-applications/<kit>/thank-you-round-R.md`, paste-ready. The candidate sends them; Claude never does.
- **When:** within 24 hours. The timer is due the day after the interview until `interviews.py sent` marks it done.
- **Length:** 80–150 words. Three moves: thanks for something specific to that person; one callback to a moment from the conversation (from `landed`, or a question they asked); one line that adds value or closes a gap from `missed`, using facts from the career master only.
- **Voice:** `voice-guide.md`, including the conversational voice; no hype, no em dashes, no new claims.
- **Channel:** through a staffing firm, send to the recruiter to forward unless the candidate has direct contact details. Never guess an email address.
- When the candidate edits a draft, add the before/after to the voice guide's "edits to drafts" table.

## Follow-ups
`python engine/interviews.py due` lists what's owed: debriefs, thank-you notes, and follow-ups after applying (7 days), after messaging a connection (5 days) and after an interview (5 days of silence). The apply queue shows the same items in its **Due** section. For each, offer a short draft (2–4 sentences, specific to the job) when the candidate asks; record the follow-up as a pipeline event with a note.
