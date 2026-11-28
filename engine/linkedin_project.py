"""Keep the LinkedIn project (description numbers + the two images) in step with the funnel, on the user's call.

Usage:
  python engine/linkedin_project.py check     # current numbers vs. what's published; says whether to ask the user
  python engine/linkedin_project.py update    # after the user says yes: render both images and put the new numbers
                                              # into the description in 4-profile/linkedin/linkedin-profile.md
  python engine/linkedin_project.py live      # after the user has uploaded the images and pasted the description

The description and the images go together: the description quotes qualified targets per 100 job listings processed;
the images show the per-100 funnel and grade bands. `update` always does both, so they never
disagree. Records live in 6-system/linkedin-project.json: "live" is what's on LinkedIn now, "ready" is an update
waiting for the user to upload, and "history" keeps every earlier live set.

When to ask (decided 2026-11-18): the user decides. Claude runs `check` at the end of every round (after metrics and the
report) and asks only when the public numbers would change noticeably.

Per 100 (decided 2026-11-18): the public description and images show rates per 100 job listings processed, never raw
totals or applications in progress (raw volume read to an outside reviewer as a dire lead rate). So volume growth alone
is no reason to ask: `check` asks when the per-100 qualified-target figure changes, or any per-100 funnel stage moves
by ASK_STAGE_MOVE or more.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linkedin_images  # noqa: E402
import metrics  # noqa: E402
import pipeline  # noqa: E402
from paths import Paths, read_json, write_json  # noqa: E402

ASK_STAGE_MOVE = 2  # ask when any per-100 funnel stage moved by 2 or more (or qualified targets changed at all)
# The sentence in the description that carries the number (section 7 of linkedin-profile.md).
NUMBERS = re.compile(r"about \d+ in every 100 listings processed make the cut as qualified targets")


def load(P):
    return read_json(P.linkedin_project, {})


def save(P, rec):
    write_json(P.linkedin_project, rec, indent=2)


def current(P):
    t = metrics.totals(P)
    if not t:
        raise SystemExit("No recorded rounds: run engine/metrics.py --round N first.")
    return {"round": t["round"], "processed": t["processed"], "decided": t["decided"], "pdfs": t["pdfs"],
            "ranked": t["ranked"], "phone_pdfs": t["phone_pdfs"], "phone_ranked": t["phone_ranked"],
            "rec_pdfs": t.get("rec_pdfs", 0),
            "applications_in_progress": pipeline.in_progress_count(P),
            "grades": linkedin_images.grade_counts(P)}


def rates(n):
    return linkedin_images.per100(n, n.get("grades") or {})[0]


def sentence(n):
    return f"about {rates(n)['ranked']} in every 100 listings processed make the cut as qualified targets"


def show(n):
    r = rates(n)
    return " / ".join(str(r[k]) for k in linkedin_images.FUNNEL_KEYS)


def check(P):
    rec, now = load(P), current(P)
    live = rec.get("live")
    print(f"Now (round {now['round']}): per 100 {show(now)} (real {now['processed']} / {now['decided']} / "
          f"{now['pdfs']} / {now['ranked']})")
    if now.get("phone_pdfs"):
        kind = ("phone-triage" if not now.get("rec_pdfs") else "recommendation" if now["rec_pdfs"] == now["phone_pdfs"]
                else "phone-triage and recommendation")
        print(f"Left out: {now['phone_pdfs']} {kind} saves ({now['phone_ranked']} qualified targets now); the "
              f"listings behind them are unknown, so they stay out of every per-100 number.")
    if rec.get("ready"):
        r = rec["ready"]
        print(f"Waiting for the user to upload: the update prepared {r['prepared']} (round {r['round']}). "
              f"After the user uploads the images and pastes the description, run `linkedin_project.py live`.")
    if not live:
        print("Nothing recorded as live yet.")
        return
    a, b = rates(live), rates(now)
    moved = max(abs(b[k] - a[k]) for k in linkedin_images.FUNNEL_KEYS)
    print(f"Live on LinkedIn (since {live['published']}, round {live['round']}): per 100 {show(live)}"
          f"{'' if live.get('per100') else ' (live set shows raw counts)'}")
    if rec.get("ready"):
        print("No need to ask: an update is already waiting for the user (rerun `update` first if the numbers moved).")
    elif not live.get("per100"):
        print("ASK USER: the live set still shows raw counts. Switch it to per 100? (yes -> linkedin_project.py update)")
    elif b["ranked"] != a["ranked"] or moved >= ASK_STAGE_MOVE:
        print(f"ASK USER: per-100 numbers moved (qualified targets {a['ranked']} -> {b['ranked']}, largest stage "
              f"move {moved}). Update the LinkedIn project description and images? (yes -> linkedin_project.py update)")
    else:
        print(f"No need to ask: per-100 numbers unchanged (largest stage move {moved}, under {ASK_STAGE_MOVE}).")


def update(P):
    rec, now = load(P), current(P)
    # Check the description first: a failure here must leave the live images untouched.
    ref = P.linkedin_dir / "linkedin-profile.md"
    if not ref.exists():
        raise SystemExit(f"{P.rel(ref) if P.inside(ref) else ref} not found: no numbers sentence to update; "
                         f"no images rendered.")
    text = ref.read_text(encoding="utf-8")
    if not NUMBERS.search(text):
        raise SystemExit(f"Couldn't find the numbers sentence in {P.rel(ref)}; nothing changed, no images rendered.")
    args = ["--data", str(P.data)]
    override = rec.get("grades_override") or {}
    if override.get("grades"):  # the user's chosen split for the public grade image (see linkedin_images.py)
        args += ["--grades", ",".join(f"{g}={n}" for g, n in override["grades"].items())]
        print(f"Grade image uses the recorded override: {override['grades']} ({override.get('reason', 'no reason')})")
    imgs = linkedin_images.main(args)
    ref.write_text(NUMBERS.sub(sentence(now), text, count=1), encoding="utf-8")
    rec["ready"] = dict(now, prepared=dt.date.today().isoformat(), images=imgs["files"], per100=imgs["per100"],
                        shown={"funnel": imgs["funnel"], "grades": imgs["grades"]})
    save(P, rec)
    print(f"Description numbers updated in {P.rel(ref)}: {sentence(now)}")
    print("Next: the user uploads both images (replacing the old ones on the project) and pastes the description, "
          "then run `linkedin_project.py live`.")


def live(P):
    rec = load(P)
    if not rec.get("ready"):
        raise SystemExit("No prepared update to mark live; run `update` first.")
    if rec.get("live"):
        rec.setdefault("history", []).append(rec["live"])
    rec["live"] = dict(rec.pop("ready"), published=dt.date.today().isoformat())
    save(P, rec)
    print(f"Live: {sentence(rec['live'])} (round {rec['live']['round']}, {rec['live']['published']})")


def main():
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: otherwise the subcommand's default (None) overwrites a --data given before the subcommand.
    common.add_argument("--data", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "update", "live"):
        sub.add_parser(c, parents=[common])
    a = ap.parse_args()
    P = Paths(getattr(a, "data", None))
    {"check": check, "update": update, "live": live}[a.cmd](P)


if __name__ == "__main__":
    main()
