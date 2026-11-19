"""Turn <data>/5-criteria/searches.json into ready-to-use LinkedIn job-search links and Boolean keyword strings.

Usage:  python engine/searches.py [--data my-data]
Writes  <data>/2-reports/search-links.md (locations: engine/paths.py)

Only builds URLs; it never opens or queries LinkedIn. You click the links yourself (Manual mode).
LinkedIn URL parameters used: keywords, location, geoId, distance, f_WT (1 on-site, 2 remote, 3 hybrid),
f_TPR (posted within: r86400 day, r604800 week, r2592000 month), f_E (4 mid-senior, 5 director), sortBy=DD.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

from locations import US_STATES, home_state_of
from paths import Paths, read_json
from urllib.parse import urlencode

POSTED = {"day": "r86400", "week": "r604800", "month": "r2592000"}
LEVEL = {"internship": "1", "entry": "2", "associate": "3", "mid-senior": "4", "director": "5", "executive": "6"}
US_GEO_ID = "103644278"


def keywords(s, exclude):
    titles = " OR ".join(s["titles"])
    q = f"({titles})" if len(s["titles"]) > 1 else titles
    if s.get("any_of"):
        q += " AND (" + " OR ".join(s["any_of"]) + ")"
    if s.get("all_of"):  # a second required group, e.g. an infrastructure anchor
        q += " AND (" + " OR ".join(s["all_of"]) + ")"
    if exclude:
        q += " NOT (" + " OR ".join(exclude) + ")"
    return q


def window(s, d, md=None):
    """(f_TPR value or None, label) for a search under the current triage mode (docs/PLAN.md -> Triage modes).

    Catch-up: the setup interview's lookback (week, month, any, <N>d) if one is set, otherwise each search's own
    posted_within (the behaviour before triage modes). Keep-up: the cadence interval plus one day of overlap.
    Custom day counts use LinkedIn's r<seconds> URL value, which the site's filter menu doesn't offer."""
    md = md or {}
    if md.get("mode") == "keep-up" and md.get("cadence"):
        import modes
        n = modes.window_days(md["cadence"])
        return f"r{n * 86400}", f"Past {n} days (Keep-up, {md['cadence']} + 1 day overlap)"
    look = md.get("lookback") if md.get("mode", "catch-up") == "catch-up" else None
    if look == "any":
        return None, "Any time (Catch-up lookback)"
    if look and look.endswith("d"):
        n = int(look[:-1])
        return f"r{n * 86400}", f"Past {n} days (Catch-up lookback)"
    key_ = look or s.get("posted_within", d["posted_within"])
    label = {"day": "Past 24 hours", "week": "Past week", "month": "Past month"}[key_]
    return POSTED[key_], label + (" (Catch-up lookback)" if look else "")


LINKEDIN_DISTANCES = (5, 10, 25, 50, 75, 100)  # the radius values LinkedIn's distance filter accepts


def link_distance(radius_miles):
    """The smallest LinkedIn distance that covers the spec's radius, so a link never hides a job inside it."""
    return next((x for x in LINKEDIN_DISTANCES if x >= radius_miles), LINKEDIN_DISTANCES[-1])


def url(s, d, center_name, center_geo=None, md=None, radius=50):
    tpr, _ = window(s, d, md)
    p = {"keywords": keywords(s, d["exclude"] + s.get("exclude_extra", [])), **({"f_TPR": tpr} if tpr else {}),
         "sortBy": "DD"}
    if d.get("experience") and s["where"] != "local":
        p["f_E"] = ",".join(LEVEL[e] for e in d["experience"])
    if s["where"] == "remote":
        p.update({"location": "United States", "geoId": US_GEO_ID, "f_WT": "2"})
    else:
        # LinkedIn ignores distance unless the location carries its geoId (S7's first run, 2026-11-17).
        if not center_geo:
            raise SystemExit("Local search needs spec.json -> hybrid_onsite_center.linkedin_geo_id "
                             "(pick the town from LinkedIn's location dropdown and copy geoId from the URL).")
        p.update({"location": center_name, "geoId": center_geo, "distance": str(link_distance(radius)), "f_WT": "1,3"})
    return "https://www.linkedin.com/jobs/search/?" + urlencode(p)


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    P = Paths(args.data)
    cfg = read_json(P.searches)
    spec = read_json(P.spec)
    c = spec["work_arrangement"]["machine_rule"]["hybrid_onsite_center"]
    st = home_state_of(c["name"])  # LinkedIn's location box wants the full state name: "Springfield, Illinois"
    center = re.sub(rf",\s*{st}\b", ", " + US_STATES[st].title(), c["name"]) if st in US_STATES else c["name"]
    center_geo = c.get("linkedin_geo_id")
    radius = spec["work_arrangement"]["machine_rule"].get("radius_miles", 50)
    d = cfg["defaults"]
    md = cfg.get("mode") or {}
    keep_up = md.get("mode") == "keep-up" and md.get("cadence")
    look = md.get("lookback") if not keep_up else None
    if keep_up or look:  # e.g. "Past 8 days (Keep-up, ...)" -> "in the past 8 days"; "Any time (...)" -> "any time"
        label = window({}, d, md)[1].split(" (")[0].lower()
        posted = label if label == "any time" else "in the " + label
    else:
        posted = f"in the past {d['posted_within']}"  # unchanged from before triage modes
    out = [f"# LinkedIn search suggestions ({dt.date.today().isoformat()})\n",
           *([f"**Triage mode: Keep-up, {md['cadence']}.** Every link is set to posted {posted} "
              "(your check-in interval plus a day of overlap). LinkedIn alerts on these searches can replace "
              "running them by hand; set each alert's frequency to match.\n"] if keep_up else []),
           *([f"**Triage mode: Catch-up, lookback {look}.** Every link uses that window instead of the search's "
              "usual one.\n"] if look else []),
           "Built from your top-ranked saved jobs and your confirmed spec. Each link opens a LinkedIn job search "
           f"with filters already set: remote US (or within {radius} miles of {center} for local), posted "
           f"{posted}, newest first, excluding {', '.join(x.strip(chr(34)) for x in d['exclude'])}.\n",
           "## Your LinkedIn searches: what to do with each\n",
           "| Search | Name | Status | Action on LinkedIn |\n|---|---|---|---|\n"
           + "\n".join(f"| {s['id']} | {s['name']} | {s.get('status', 'proposed')} | {s.get('linkedin_action', '')} |"
                       for s in cfg["searches"]) + "\n",
           "**To make one a job alert:** open the link, check the results look right, then switch on "
           "**Set alert** at the top of the results. Alert emails become the input for Phase 2.\n",
           *(["**Before every run (check this first):**\n\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(d["pre_run_checklist"], 1)) + "\n"]
             if d.get("pre_run_checklist") else []),
           *(["**While triaging (tips):**\n\n" + "\n".join(f"- {t}" for t in d["triage_tips"]) + "\n"]
             if d.get("triage_tips") else []),
           *([f"**Other ways to capture results:** {d['alternative_capture_note']}\n"] if d.get("alternative_capture_note") else []),
           "**Why sales/marketing aren't excluded:** LinkedIn matches keywords against the whole description, and "
           "nearly every PM posting mentions sales and marketing teams. Role type is filtered by the scoring step instead.\n",
           "**What happens next:** jobs you find through these searches go into `1-inbox/job-pdfs/` like any other. "
           "Each search keeps a yield record (jobs found, scored high, saved) so weak searches can be tuned or retired.\n"]
    for cluster, label in (("core", "Core (60% weight)"), ("platform", "Platform"), ("ai_stretch", "Stretch (40% weight)"), ("local", "Local")):
        group = [s for s in cfg["searches"] if s["cluster"] == cluster and s.get("status") != "retired"]
        if not group:
            continue
        out.append(f"## {label}\n")
        for s in group:
            out.append(f"### {s['id']} - {s['name']}\n")
            out.append(f"{s['why']}  \n*Built from:* {', '.join(s['seed_jobs'])}\n")
            status = f"*Status:* {s.get('status', 'proposed')} · *Window:* {window(s, d, md)[1]}"
            if s.get("run_note"):
                status += f" · {s['run_note']}"
            out.append(status + "\n")
            out.append(f"**[Open search on LinkedIn]({url(s, d, center, center_geo, md, radius)})**\n")
            out.append("Keywords (to paste or edit by hand):\n")
            out.append(f"```\n{keywords(s, d['exclude'] + s.get('exclude_extra', []))}\n```\n")
    path = P.search_links
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path} ({len(cfg['searches'])} searches)")


if __name__ == "__main__":
    main()
