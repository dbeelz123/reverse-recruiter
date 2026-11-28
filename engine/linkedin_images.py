"""Render the two LinkedIn project images (Job Search Funnel, Qualified Targets) from the current numbers.

Usage:  python engine/linkedin_images.py [--round N] [--data my-data]

Writes  4-profile/linkedin/project-images/job-search-funnel-round-NN.png
        4-profile/linkedin/project-images/job-search-grade-bands-round-NN.png
Earlier rounds' images in that folder move to its archive/ (folder hygiene).

Numbers come from engine/metrics.py (funnel totals, labels) and the current job records' review tiers, so run it
after the round is recorded (metrics.py --round N) and the report is built. N defaults to the latest recorded round.

Layout settled with the user on 2026-11-18:
- 3264 x 2121 px (1088 x 707 CSS px at 3x): about 1.54:1, the shape of LinkedIn's media viewer, which leaves only a
  thin line at the top (wider or narrower shapes left black bars).
- Funnel: main title, four stat cards with the number only (per 100 it already is the percentage; 2026-11-19), and
  bars with counts only (the bar length already shows the share). Grade bands: main title, a subtitle, one bar split
  into A/B/C/D with counts (each segment wide enough for its label), and an even four-column legend below with each
  grade's name (2026-11-19: labels under narrow segments ran together). No percentages: per 100 they read at a
  glance. It is a public, best-foot-forward image, so the user may set the band split by hand (--grades, recorded as
  "grades_override" in linkedin-project.json); otherwise the funnel's targets are split by the real grade mix.
- Content is inset from the image edges because LinkedIn's media viewer crops the sides of the preview (2026-11-19).
Rendering uses headless Microsoft Edge (or Chrome) to screenshot an HTML page; the page is written to a temp folder
outside the project.

Per 100 (decided 2026-11-18): the public images show the funnel scaled to 100 job listings processed, with a
"Per 100 job listings processed" subtitle and no round text, because raw volume read to an outside reviewer as a dire
lead rate. Grade bands split the funnel's per-100 targets (largest-remainder rounding). --raw renders real counts.
"""
import argparse
import collections
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import metrics
from paths import Paths, read_json, round_number

W, H, SCALE = 1088, 707, 3
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
TIERS = [("A", "strong fit", "#0C447C", "#fff"), ("B", "good fit", "#378ADD", "#fff"),
         ("C", "possible", "#85B7EB", "#0C447C"), ("D", "weak", "#B5D4F4", "#0C447C")]
# LinkedIn's media viewer crops a few percent off the sides of the preview, so the card sits well inside the image
# (MX px from each side) and nothing important comes near an edge.
MX, MY = 56, 28
BASE = (f'html,body{{margin:0;background:#fff;font-family:"Segoe UI",Helvetica,Arial,sans-serif;width:{W}px;'
        f'height:{H}px;overflow:hidden}}.card{{width:{W - 2 * MX}px;height:{H - 2 * MY}px;margin:{MY}px {MX}px;'
        'box-sizing:border-box;border:1px solid #e3e2dc;border-radius:16px;display:flex;flex-direction:column;'
        'justify-content:center}')


def pct(a, b):
    return f"{round(100 * a / b)}%" if b else ""


FUNNEL_KEYS = ("processed", "decided", "pdfs", "ranked")


def per100(t, counts):
    """Scale the funnel to 100 listings processed, and split its qualified targets (about 9 per 100) into the grade
    bands with largest-remainder rounding, so the bands add up to the funnel's last number. The grade image continues
    the funnel's story: of the targets per 100 listings, how many fall in each band."""
    top = t["processed"] or 1
    f = {k: round(100 * t[k] / top) for k in FUNNEL_KEYS}
    n = sum(counts.values()) or 1
    raw = {g: f["ranked"] * c / n for g, c in counts.items()}
    g = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - int(raw[k]), reverse=True)[: f["ranked"] - sum(g.values())]:
        g[k] += 1
    return f, g


def parse_grades(s):
    """'A=2,B=3,C=3,D=1' -> {'A': 2, 'B': 3, 'C': 3, 'D': 1} (a chosen split for the public grade image)."""
    out = {g: 0 for g, *_ in TIERS}
    for part in filter(None, (x.strip() for x in (s or "").split(","))):
        k, _, v = part.partition("=")
        if k.strip().upper() not in out or not v.strip().isdigit():
            raise SystemExit(f"--grades expects A=n,B=n,C=n,D=n; got {part!r}")
        out[k.strip().upper()] = int(v)
    return out


def grades_note(grades, ranked):
    """A warning when a chosen grade split doesn't add up to the funnel's qualified targets per 100 (the grade image
    continues the funnel's story, so the two should agree); None when it does. The split stays the user's call."""
    total = sum(grades.values())
    if total == ranked:
        return None
    return (f"WARNING: the chosen grade split adds up to {total}, but the funnel shows {ranked} qualified targets "
            f"per 100; the grade image's caption will say {total}. Check the split (linkedin-project.json).")


def funnel_html(t, subtitle=""):
    vals = [t["processed"], t["decided"], t["pdfs"], t["ranked"]]
    colors = ["#B5D4F4", "#378ADD", "#185FA5", "#0C447C"]
    top = vals[0] or 1
    # Cards show the number only: per 100 it already is the percentage, and in raw counts the bars show the share.
    cards = "".join(f'<div class="k"><div class="t">{lab}</div><div class="v">{v}</div></div>'
                    for lab, v in zip(metrics.LABELS, vals))
    rows = "".join(f'<div class="row"><b>{lab}</b><div class="fill" style="width:{100 * v / top:.1f}%;'
                   f'background:{c}"></div><em>{v}</em></div>' for lab, v, c in zip(metrics.LABELS, vals, colors))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.card{{padding:28px 32px 36px}}h1{{font-size:32px;font-weight:600;color:#0b0b0b;margin:4px 0 22px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:34px}}
.k{{background:#f7f6f2;border-radius:12px;padding:20px 16px}}.k .t{{font-size:16px;color:#52514e;white-space:nowrap}}
.k .v{{white-space:nowrap;font-size:38px;font-weight:600;color:#0b0b0b;margin-top:6px}}
h2{{font-size:20px;font-weight:500;color:#52514e;margin:0 0 18px}}.chart{{margin-left:240px;margin-right:110px}}
.row{{position:relative;height:42px;margin:0 0 26px;display:flex;align-items:center}}.row:last-child{{margin-bottom:0}}
.row b{{position:absolute;right:100%;margin-right:16px;font-size:18px;font-weight:400;color:#0b0b0b;white-space:nowrap}}
.fill{{height:42px;border-radius:0 6px 6px 0}}.row em{{font-style:normal;font-size:18px;color:#0b0b0b;margin-left:12px}}
.st{{font-size:18px;color:#52514e;margin:-18px 0 22px}}
</style></head><body><div class="card"><h1>Job Search Funnel</h1>{f'<div class="st">{subtitle}</div>' if subtitle else ''}<div class="kpis">{cards}</div>
<h2>Overall funnel</h2><div class="chart">{rows}</div></div></body></html>"""


def grades_html(counts, subtitle):
    n = sum(counts.values())
    shown = [x for x in TIERS if counts.get(x[0])]
    # Segment widths follow the counts, but never so narrow that "A 1" doesn't fit. The names and shares sit in an
    # even four-column legend below, so a small grade's label can't run into its neighbor's.
    bands = "".join(f'<div class="seg" style="flex:{counts[g]};background:{bg};color:{ink}">{g} {counts[g]}</div>'
                    for g, _, bg, ink in shown)
    # Names only: the counts are on the bar, and per 100 they already read as shares.
    legend = "".join(f'<div class="li"><i style="background:{bg}"></i><div><b>{g}</b> {name}</div></div>'
                     for g, name, bg, _ in shown)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.card{{padding:40px 52px}}h1{{font-size:44px;font-weight:600;color:#0b0b0b;margin:0 0 8px}}
.sub{{font-size:24px;color:#52514e;margin:0 0 44px}}.bar{{display:flex;gap:6px;height:150px}}
.seg{{min-width:96px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:38px;
font-weight:600;white-space:nowrap}}
.legend{{display:grid;grid-template-columns:repeat({len(shown)},1fr);gap:16px;margin-top:30px}}
.li{{display:flex;gap:12px;align-items:flex-start;font-size:23px;color:#52514e;line-height:1.35}}
.li i{{flex:none;width:20px;height:20px;border-radius:4px;margin-top:5px}}.li b{{color:#0b0b0b;font-weight:600}}
.li span{{display:block;color:#898781}}
</style></head><body><div class="card"><h1>Qualified Targets</h1>
<div class="sub">{subtitle}</div>
<div class="bar">{bands}</div><div class="legend">{legend}</div></div></body></html>"""


def render(browser, html, out_png, tmp):
    page = tmp / (out_png.stem + ".html")
    page.write_text(html, encoding="utf-8")
    shot = tmp / (out_png.stem + ".png")
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    f"--user-data-dir={tmp / 'profile'}", f"--force-device-scale-factor={SCALE}",
                    f"--window-size={W},{H}", f"--screenshot={shot}", page.as_uri()],
                   check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # On Windows the Edge launcher can return before the headless process writes the file: wait for it.
    for _ in range(120):
        if shot.exists() and shot.stat().st_size > 0:
            time.sleep(0.5)  # let the write finish
            break
        time.sleep(0.5)
    if not shot.exists() or shot.stat().st_size == 0:  # an empty file is a failed render, not an image
        raise SystemExit(f"The browser did not write {shot.name}" + (" (the file is empty)" if shot.exists() else ""))
    shutil.move(str(shot), str(out_png))


def grade_counts(P):
    """Current jobs per grade band, leaving out phone-triage saves (metrics.totals leaves them out of the funnel too,
    so the grade image keeps splitting the funnel's own qualified targets)."""
    t = metrics.totals(P)
    phone = set(t["phone_ids"]) if t else set()
    jobs = [j for j in (read_json(f) for f in P.jobs.glob("*.json"))
            if j.get("job_id") not in phone and not (j.get("review") or {}).get("held")]  # held: off the ranked list
    counts = collections.Counter((j.get("review") or {}).get("tier") for j in jobs)
    return {g: counts.get(g, 0) for g, *_ in TIERS}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=round_number, default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--raw", action="store_true", help="real counts instead of per 100 listings processed")
    ap.add_argument("--grades", help="a chosen split for the grade image, e.g. A=2,B=3,C=3,D=1 (per-100 images only; "
                                     "linkedin_project.py passes the override recorded in linkedin-project.json)")
    a = ap.parse_args(argv)
    P = Paths(a.data)
    t = metrics.totals(P)
    if not t:
        raise SystemExit("No recorded rounds: run engine/metrics.py --round N first.")
    # The images always show the totals up to the latest recorded round, so no other round can be asked for: an
    # older number would only relabel today's totals as that round's.
    if a.round is not None and a.round != t["round"]:
        raise SystemExit(f"The images show the totals up to the latest recorded round ({t['round']}); "
                         f"--round {a.round} isn't available. Leave --round out.")
    rnd = t["round"]
    counts = grade_counts(P)
    if a.raw:
        shown, shown_g, kind = {k: t[k] for k in FUNNEL_KEYS}, counts, ""
        f_sub, g_sub = "", f"{sum(counts.values())} jobs under consideration after round {rnd}"
    else:
        shown, shown_g = per100(t, counts)
        if a.grades:  # the user's chosen split for the marketing image, recorded where it comes from
            shown_g = parse_grades(a.grades)
            note = grades_note(shown_g, shown["ranked"])
            if note:
                print(note)
        kind = "per100-"
        f_sub = "Per 100 job listings processed"
        g_sub = f"{sum(shown_g.values())} qualified targets per 100 job listings processed"
    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        raise SystemExit("No Edge or Chrome found to render the images.")
    out_dir = P.linkedin_dir / "project-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {"funnel": out_dir / f"job-search-funnel-{kind}round-{rnd:02d}.png",
               "grades": out_dir / f"job-search-grade-bands-{kind}round-{rnd:02d}.png"}
    # Outside the project (folder hygiene). The headless browser can still hold a profile file when the block ends,
    # so a cleanup error must not undo a finished render.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        # Both images are rendered before anything in the folder changes: the two go live together, so a failed
        # second render must leave the previous pair in place, not one new image beside an archived old pair.
        staged = tmp / "staged"
        staged.mkdir()
        html = {"funnel": funnel_html(shown, f_sub), "grades": grades_html(shown_g, g_sub)}
        for k, p in targets.items():
            render(browser, html[k], staged / p.name, tmp)
        # A re-render of the same round (e.g. a layout change) must not overwrite the images that are live on
        # LinkedIn: the existing files move to archive/ with their date first (2026-11-19).
        for p in targets.values():
            if p.exists():
                (out_dir / "archive").mkdir(exist_ok=True)
                stamp = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(p.stat().st_mtime))  # unique per render
                shutil.move(str(p), str(out_dir / "archive" / f"{p.stem}-{stamp}{p.suffix}"))
        for p in targets.values():
            shutil.move(str(staged / p.name), str(p))
    # Older rounds' images go to archive/.
    # Only images of the same kind: a raw-count render must not archive the per-100 pair that is live on
    # LinkedIn (linkedin-project.json points at those files), and the other way round.
    for old in out_dir.glob("job-search-*-round-*.png"):
        if old not in targets.values() and ("-per100-round-" in old.name) == bool(kind):
            (out_dir / "archive").mkdir(exist_ok=True)
            shutil.move(str(old), str(out_dir / "archive" / old.name))
    print(f"Funnel{'' if a.raw else ' (per 100)'}: " + " / ".join(str(shown[k]) for k in FUNNEL_KEYS) +
          "   Grades: " + ", ".join(f"{g} {c}" for g, c in shown_g.items()))
    for p in targets.values():
        print(f"Wrote {P.rel(p)}")
    return {"round": rnd, "funnel": shown, "grades": shown_g, "per100": not a.raw,
            "files": [P.rel(p) for p in targets.values()]}


if __name__ == "__main__":
    main()
