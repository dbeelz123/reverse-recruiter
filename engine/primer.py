"""Interview primer: the mechanical half of preparing for an employer interview.

Usage:
  python engine/primer.py draft <job> [--out FILE]   # working draft for Claude: requirements, candidate evidence, question seeds
  python engine/primer.py check <job>                 # is the kit's primer complete? (fit map ratings + likely questions)

<job> is a job ID, a kit folder name, or a word that matches one company (same as pipeline.py).

The primer has two parts, both kept in the job's kit folder (3-applications/<company-role>/):
  fit-map.md          every Required and Nice-to-have requirement (plus the duties), each rated Have / Partial / Gap
                      with evidence from the career master and where the employer can see it
  interview-prep.md   a "Likely interview questions" section (and, for a Role Explorer brief, everything else)

`draft` does what a script can: pulls the requirement sections out of the posting, splits them into items, suggests
career-master bullets whose words and tags overlap each item, and gathers what the project already knows (the review's
gaps and caveats, any stretch review, years and degree requirements). It writes nothing into the kit: Claude judges the
ratings and writes the files by the rules in engine/prompts/interview-primer.md. `check` reads the finished files back.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import Paths  # noqa: E402
from pipeline import kits, load, resolve  # noqa: E402

# Section headers in postings, matched against short lines (checked in the order given in sections()).
NICE = r"prefer|nice|bonus|\bplus\b|extras|might also|helpful|not required"
REQ = (r"require|qualif|looking for|bring|need|about you|who you are|must|minimum|basic|skills|competenc|"
       r"education|you (will )?have|experience$|expertise|essentials|ideal|great fit|good fit|what makes you|succeed"
       r"|do well")
DUTY = (r"what you('|’)?ll do|what you will do|responsibilit|day[- ]to[- ]day|typical day|in this role|you will"
        r"|difference you")
OTHER = (r"benefit|compensation|salary|\bpay\b|perks|why (join|work)|equal (opportunity|employment)|\beeo\b"
         r"|location|success looks|our (values|culture)|what we offer|how (we|to) |life at|^about (?!you)"
         r"|additional information|take care|privacy|reward|interview process|what to expect|why this role|the team"
         r"|community|commitment|inclusion")
LONG_SECTION = 20  # more items than this usually means the section ran into boilerplate
BULLET = "•-*·▪●◦–"
WRAP = 90  # PDF lines this long or longer were probably wrapped mid-item
RATINGS = ("Have", "Partial", "Gap")
STOP = set("""a an and or the of to in on for with by as at from into across over your you our we us is are be
being been will can able ability strong proven demonstrated experience experienced years year working work worked
including such similar related relevant other who what how that this these those their its it not just than more
plus least deep solid excellent great good high highly well using use within new e.g etc via also both every""".split())

# Career-master tags -> words that suggest them in a requirement. Generic product vocabulary, no personal data.
TAG_WORDS = {
    "migration": "migrat modern legacy transition move cutover",
    "ha-dr": "availab disaster recover resilien failover uptime continuity",
    "replication": "replicat sync",
    "backup": "backup protect restor",
    "database": "database sql data storage",
    "cloud": "cloud aws azure gcp saas iaas hybrid multi-cloud",
    "marketplace": "marketplace listing catalog",
    "iac": "terraform infrastructure-as-code iac automat provision",
    "api": "api apis rest sdk integrat developer",
    "ai": "ai ml llm agent agentic genai machine model prompt claude copilot",
    "pricing": "pricing packaging monetiz commercial",
    "gtm": "go-to-market gtm launch positioning messaging",
    "partners": "partner alliance ecosystem channel",
    "hyperscaler": "aws azure gcp hyperscal",
    "customer-discovery": "customer discovery research interview user",
    "prototyping": "prototyp mvp experiment zero-to-one 0-to-1",
    "portfolio": "portfolio roadmap strategy program multiple prioriti",
    "leadership": "lead leadership manage mentor team agile scrum safe",
    "enablement": "enablement training adoption onboard",
    "metrics": "metric kpi outcome measur data-driven analytics",
    "sales-eng": "pre-sales presales sales engineer solution",
}


def norm_words(text):
    words = re.findall(r"[a-z][a-z0-9+\-]{2,}", text.lower())
    return {w[:6] for w in words if w not in STOP}


def sections(posting, empty=None):
    """Split a posting into (kind, header, [items]) for required, nice-to-have and duty sections.
    Headers of those kinds that have no items (a PDF can collapse a section) are added to `empty` if given."""
    out, kind, header, items, prev = [], None, None, [], ""

    def close():
        # A bullet or rule on a line of its own (PDF text often puts "•" on one line and its text on the next)
        # leaves nothing once the bullet characters are stripped: not an item.
        cleaned = [c for c in (re.sub(r"\s+", " ", i).strip(" " + BULLET) for i in items) if c]
        if kind and cleaned:
            out.append((kind, header, cleaned))
        elif kind and empty is not None:
            empty.append(header)

    for raw in (posting or "").splitlines():
        line = raw.strip()
        if not line:
            prev = ""
            continue
        bare = line.rstrip(":").strip()
        first = next((c for c in bare if c.isalpha()), "")
        is_header = (len(bare) < 70 and not bare.endswith(".") and line[0] not in BULLET and len(bare.split()) <= 9
                     and first.isupper())  # a wrapped fragment ("plus", "cohorts") starts lowercase
        new_kind = None
        if is_header:
            # Order matters: "Preferred Qualifications" is nice-to-have, "Your Location" is not a requirement,
            # and "The Essentials - You Will Have" is a requirement even though it says "you will".
            for k, rx in (("nice", NICE), ("other", OTHER), ("required", REQ), ("duty", DUTY)):
                if re.search(rx, bare, re.I):
                    new_kind = k
                    break
        if new_kind:
            close()
            kind, header, items = (None if new_kind == "other" else new_kind), bare, []
            prev = ""
            continue
        if kind:
            starts_new = (line[0] in BULLET or not items or prev.endswith((".", ";", "!", "?", ":"))
                          or ((line[0].isupper() or line[0].isdigit()) and len(prev) < WRAP))
            if starts_new:
                items.append(line)
            else:
                items[-1] += " " + line
        prev = line
    close()
    return out


def master_bullets(P):
    """Career-master bullets that carry tags: [(tags, text)]."""
    text = Path(P.career_master).read_text(encoding="utf-8")
    out, role = [], ""
    for line in text.splitlines():
        if line.startswith("### "):
            role = line[4:].strip()
        m = re.match(r"^- ((?:`[\w-]+` ?)+)(.*)", line)
        if m:
            tags = re.findall(r"`([\w-]+)`", m.group(1))
            body = re.sub(r"\*\*|\*\(.*?\)\*", "", m.group(2)).strip()
            out.append((tags, body, role))
    return out


def evidence_for(req, bullets, n=3):
    rw = norm_words(req)
    tag_hits = {t for t, words in TAG_WORDS.items() if rw & {w[:6] for w in words.split()}}
    scored = []
    for tags, body, role in bullets:
        score = len(rw & norm_words(body)) + 2 * len(tag_hits & set(tags))
        if score >= 3:
            scored.append((score, tags, body, role))
    scored.sort(key=lambda s: -s[0])
    return scored[:n]


def stretch_reviews(P, job):
    company = re.split(r"[\s(,]", (job.get("company") or "").strip())[0].lower()
    hits = []
    for f in sorted(P.calibration.glob("round-*.json")):
        for q in (load(f) or {}).get("questions", []):
            if q.get("type") == "stretch review" and company and company in q.get("topic", "").lower():
                hits.append((f.stem, q))
    return hits


def draft(P, job, kit):
    rev = job.get("review") or {}
    bullets = master_bullets(P)
    empty = []
    secs = sections(job.get("posting_text"), empty)
    posting = job.get("posting_text") or ""
    lines = []
    w = lines.append
    w(f"# Primer draft: {job['company']} - {job['title']}\n")
    w(f"Working draft from `engine/primer.py draft` for Claude. Not a deliverable: judge each row by "
      f"`engine/prompts/interview-primer.md`, then write `fit-map.md` and the questions in the kit folder "
      f"(`{P.applications.name}/{kit['folder'] if kit else '<company-role>'}/`).\n")
    w(f"- Job record: `{job['job_id']}` · score {rev.get('total', '?')} ({rev.get('tier', '?')}) · "
      f"status: {(job.get('pipeline') or {}).get('status', 'none')}")
    if not any(k == "required" for k, _, _ in secs):
        w("- **No required section found.** Read the posting in full and list the requirements by hand.")
    if empty:
        w(f"- **Headers with nothing under them:** {', '.join(repr(h) for h in empty)}. The saved PDF may have "
          f"collapsed those sections; open the live posting (or the original file) and add them by hand.")
    for kind, header, items in secs:
        if len(items) > LONG_SECTION:
            w(f"- \"{header}\" has {len(items)} items: it probably ran into boilerplate (benefits, legal text); "
              f"ignore what isn't a requirement.")
    years = sorted(set(re.findall(r"(\d+)\+?\s*(?:or more\s*)?years", posting)), key=int)
    if years:
        w(f"- Years asked for: {', '.join(y + '+' for y in years)} (check against the career master timeline)")
    if re.search(r"(?i)\b(bachelor|master'?s|mba|ph\.?d|degree)\b", posting):
        w("- Mentions a degree: check the wording (required vs. preferred, which field)")
    w("")
    labels = {"required": "Required", "nice": "Nice to have", "duty": "Duties"}
    count = {"required": 0, "nice": 0, "duty": 0}
    for kind, header, items in secs:
        w(f"## {labels[kind]} (posting header: \"{header}\")\n")
        for item in items:
            count[kind] += 1
            prefix = {"required": "R", "nice": "N", "duty": "D"}[kind]
            w(f"**{prefix}{count[kind]}.** {item}")
            ev = evidence_for(item, bullets)
            if ev:
                for score, tags, body, role in ev:
                    w(f"  - candidate ({score}; {' '.join(tags)}{'; ' + role if role else ''}): {body[:220]}")
            else:
                w("  - no career-master match: likely Partial or Gap; check by hand")
            w("")
    if rev:
        w("## What the review already says\n")
        for k in ("gaps", "caveats"):
            for x in rev.get(k) or []:
                w(f"- {k[:-1]}: {x}")
        for e in rev.get("eligibility") or []:
            w(f"- eligibility: {e.get('requirement')} (\"{e.get('quote', '')}\")")
        w("")
    sr = stretch_reviews(P, job)
    if sr:
        w("## Stretch review answers\n")
        for rnd, q in sr:
            w(f"- {rnd} {q.get('id')}: {q.get('question')} → **{q.get('answer', 'unanswered')}**")
        w("")
    w("## Question seeds (Claude turns these into the likely-questions tables)\n")
    for kind, header, items in secs:
        if kind == "required":
            for item in items:
                w(f"- Probe: \"Tell us about a time you {item[0].lower() + item[1:].rstrip('.')}.\"")
    for x in rev.get("gaps") or []:
        w(f"- Gap probe: \"You don't have {x.split(':')[0].split('(')[0].strip().lower()}. How would you close that?\"")
    for q in ("Why this role, and why this company?", "Walk us through your background (check which resume version "
              "they hold)", "How do you use AI tools in your own work?", "What questions do you have for us?"):
        w(f"- Standard: {q}")
    w("")
    return "\n".join(lines), count


MIN_QUESTIONS = 15  # likely interview questions a primer should have (prompts/interview-primer.md)


def fit_rows(text):
    """[(row ID, rating or None, cells)] for a fit map's R and N rows. The rating is read from the Rating column
    only (found in the table's header row; the third column when there is none): a requirement such as "Have 5+
    years in payments", or a bold **Have** in the evidence, is not a rating."""
    rows, col = [], 2
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        heads = [c.strip("* ").lower() for c in cells]
        if "rating" in heads:
            col = heads.index("rating")
        elif len(cells) >= 3 and re.match(r"^[RN]\d+$", cells[0]):
            cell = cells[col] if col < len(cells) else ""
            rating = next((r for r in RATINGS if re.search(rf"\*\*{r}\*\*|^{r}\b", cell)), None)
            rows.append((cells[0], rating, cells))
    return rows


def check(P, job, kit):
    if not kit:
        sys.exit(f"No kit folder for {job['company']}: say 'prep {job['company']}' or create the folder first.")
    folder = P.applications / kit["folder"]
    problems, notes = [], []
    fm = folder / "fit-map.md"
    rows = []
    if not fm.exists():
        problems.append("fit-map.md is missing")
    else:
        rows = fit_rows(fm.read_text(encoding="utf-8-sig"))
        reqs = [r for r in rows if r[0].startswith("R")]
        nice = [r for r in rows if r[0].startswith("N")]
        unrated = [r[0] for r in rows if not r[1]]
        if not reqs:
            problems.append("fit-map.md has no Required rows (R1, R2, ...)")
        if unrated:
            problems.append(f"rows without a Have / Partial / Gap rating: {', '.join(unrated)}")
        thin = [r[0] for r in rows if r[1] == "Gap" and len(r[2][-1]) < 15]
        if thin:
            problems.append(f"Gap rows without a plan for handling them (last column): {', '.join(thin)}")
        found = {"required": 0, "nice": 0}
        for kind, _, items in sections(job.get("posting_text")):
            if kind in found:
                found[kind] += len(items)
        if found["required"] > len(reqs):
            notes.append(f"the posting has {found['required']} required items and the fit map {len(reqs)} rows "
                         f"(fine if items were merged; check nothing was dropped)")
        if found["nice"] > len(nice):
            notes.append(f"the posting has {found['nice']} nice-to-have items and the fit map {len(nice)} rows")
        counts = {r: sum(1 for x in rows if x[1] == r) for r in RATINGS}
        notes.insert(0, f"fit map: {len(reqs)} required, {len(nice)} nice-to-have; "
                        + ", ".join(f"{v} {k}" for k, v in counts.items()))
    ip = folder / "interview-prep.md"
    text = ip.read_text(encoding="utf-8") if ip.exists() else ""
    m = re.search(r"^## [^\n]*likely interview questions[^\n]*$(.*?)(?=^## |\Z)", text, re.I | re.M | re.S)
    if not m:
        problems.append("interview-prep.md has no 'Likely interview questions' section")
    else:
        qn = len(re.findall(r"^\| *\d+ *\|", m.group(1), re.M))
        # The primer rules (prompts/interview-primer.md) ask for 15 or more, and the check holds a primer to that:
        # it used to pass from 10 up, so a primer could be reported complete below its own rule.
        notes.append(f"likely questions: {qn}")
        if qn < MIN_QUESTIONS:
            problems.append(f"only {qn} likely questions: the primer rules ask for {MIN_QUESTIONS} or more across "
                            f"the interviewer groups ({MIN_QUESTIONS - qn} short)")
    print(f"{job['company']} - {job['title']} (`{kit['folder']}`)")
    for n in notes:
        print(f"  - {n}")
    for p in problems:
        print(f"  ! {p}")
    print("PRIMER COMPLETE" if not problems else "PRIMER INCOMPLETE")
    return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("job")
    d.add_argument("--out", help="write the draft here (use the session scratchpad, never the kit folder)")
    sub.add_parser("check").add_argument("job")
    a = ap.parse_args()
    P = Paths(a.data)
    jobs = {f.stem: load(f) for f in P.jobs.glob("*.json")}
    kitmap = kits(P)
    jid = resolve(jobs, kitmap, a.job)
    if a.cmd == "draft":
        text, count = draft(P, jobs[jid], kitmap.get(jid))
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"Wrote {a.out}: {count['required']} required, {count['nice']} nice-to-have, {count['duty']} duties")
        else:
            print(text)
    else:
        sys.exit(0 if check(P, jobs[jid], kitmap.get(jid)) else 1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
