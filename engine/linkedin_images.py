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
- Funnel: main title, four stat cards with a small % of job listings, and bars with counts only (the bar length
  already shows the share). Grade bands: main title, a subtitle, one bar split into A/B/C/D with counts, and a
  label + share under each band.
Rendering uses headless Microsoft Edge (or Chrome) to screenshot an HTML page; the page is written to a temp folder
outside the project.

Per 100 (decided 2026-11-18): the public images show the funnel scaled to 100 job listings processed, with a
"Per 100 job listings processed" subtitle and no round text, because raw volume read to an outside reviewer as a dire
lead rate. Grade bands are scaled to the per-100 target count (largest-remainder rounding). --raw renders real counts.
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
from paths import Paths, read_json

W, H, SCALE = 1088, 707, 3
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
TIERS = [("A", "strong fit", "#0C447C", "#fff"), ("B", "good fit", "#378ADD", "#fff"),
         ("C", "possible", "#85B7EB", "#0C447C"), ("D", "weak", "#B5D4F4", "#0C447C")]
BASE = (f'html,body{{margin:0;background:#fff;font-family:"Segoe UI",Helvetica,Arial,sans-serif;width:{W}px;'
        f'height:{H}px;overflow:hidden}}.card{{width:1040px;height:{H - 48}px;margin:24px;box-sizing:border-box;'
        'border:1px solid #e3e2dc;border-radius:16px;display:flex;flex-direction:column;justify-content:center}')


def pct(a, b):
    return f"{round(100 * a / b)}%" if b else ""


FUNNEL_KEYS = ("processed", "decided", "pdfs", "ranked")


def per100(t, counts):
    """Scale the funnel to 100 listings processed and the grade bands to the scaled target count."""
    top = t["processed"] or 1
    f = {k: round(100 * t[k] / top) for k in FUNNEL_KEYS}
    n = sum(counts.values()) or 1
    raw = {g: f["ranked"] * c / n for g, c in counts.items()}
    g = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - int(raw[k]), reverse=True)[: f["ranked"] - sum(g.values())]:
        g[k] += 1
    return f, g


def funnel_html(t, subtitle=""):
    vals = [t["processed"], t["decided"], t["pdfs"], t["ranked"]]
    colors = ["#B5D4F4", "#378ADD", "#185FA5", "#0C447C"]
    top = vals[0] or 1
    cards = "".join(f'<div class="k"><div class="t">{lab}</div><div class="v">{v}<small>{pct(v, top)}</small></div></div>'
                    for lab, v in zip(metrics.LABELS, vals))
    rows = "".join(f'<div class="row"><b>{lab}</b><div class="fill" style="width:{100 * v / top:.1f}%;'
                   f'background:{c}"></div><em>{v}</em></div>' for lab, v, c in zip(metrics.LABELS, vals, colors))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.card{{padding:28px 32px 36px}}h1{{font-size:32px;font-weight:600;color:#0b0b0b;margin:4px 0 22px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:34px}}
.k{{background:#f7f6f2;border-radius:12px;padding:20px 22px}}.k .t{{font-size:17px;color:#52514e}}
.k .v{{white-space:nowrap;font-size:38px;font-weight:600;color:#0b0b0b;margin-top:6px}}
.k .v small{{font-size:17px;font-weight:600;color:#898781;margin-left:6px}}
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
    bands = "".join(f'<div class="seg" style="flex:{counts[g]};background:{bg};color:{ink}">{g} {counts[g]}</div>'
                    for g, _, bg, ink in shown)
    labels = "".join(f'<div style="flex:{counts[g]}">{name}<span>{pct(counts[g], n)}</span></div>'
                     for g, name, _, _ in shown)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.card{{padding:40px 48px}}h1{{font-size:44px;font-weight:600;color:#0b0b0b;margin:0 0 8px}}
.sub{{font-size:24px;color:#52514e;margin:0 0 48px}}.bar{{display:flex;gap:6px;height:160px}}
.seg{{border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:600;white-space:nowrap}}
.lab{{display:flex;gap:6px;margin-top:24px}}.lab div{{font-size:24px;color:#52514e;line-height:1.35}}
.lab span{{display:block;color:#898781}}
</style></head><body><div class="card"><h1>Qualified Targets</h1>
<div class="sub">{subtitle}</div>
<div class="bar">{bands}</div><div class="lab">{labels}</div></div></body></html>"""


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
    if not shot.exists():
        raise SystemExit(f"The browser did not write {shot.name}")
    shutil.move(str(shot), str(out_png))


def grade_counts(P):
    jobs = [read_json(f) for f in P.jobs.glob("*.json")]
    counts = collections.Counter((j.get("review") or {}).get("tier") for j in jobs)
    return {g: counts.get(g, 0) for g, *_ in TIERS}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--raw", action="store_true", help="real counts instead of per 100 listings processed")
    a = ap.parse_args(argv)
    P = Paths(a.data)
    t = metrics.totals(P)
    if not t:
        raise SystemExit("No recorded rounds: run engine/metrics.py --round N first.")
    rnd = a.round or t["round"]
    counts = grade_counts(P)
    if a.raw:
        shown, shown_g, kind = {k: t[k] for k in FUNNEL_KEYS}, counts, ""
        f_sub, g_sub = "", f"{sum(counts.values())} jobs under consideration after round {rnd}"
    else:
        shown, shown_g = per100(t, counts)
        kind = "per100-"
        f_sub = "Per 100 job listings processed"
        g_sub = f"{shown['ranked']} qualified targets per 100 job listings processed"
    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        raise SystemExit("No Edge or Chrome found to render the images.")
    out_dir = P.linkedin_dir / "project-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {"funnel": out_dir / f"job-search-funnel-{kind}round-{rnd:02d}.png",
               "grades": out_dir / f"job-search-grade-bands-{kind}round-{rnd:02d}.png"}
    with tempfile.TemporaryDirectory() as td:  # outside the project (folder hygiene)
        tmp = Path(td)
        render(browser, funnel_html(shown, f_sub), targets["funnel"], tmp)
        render(browser, grades_html(shown_g, g_sub), targets["grades"], tmp)
    # Older rounds' images go to archive/.
    for old in out_dir.glob("job-search-*-round-*.png"):
        if old not in targets.values():
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
