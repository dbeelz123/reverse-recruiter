"""Connection strength: how much a 1st-degree connection at a company is worth to a job's score.

Three levels (spec.json -> scoring.network), the best one at the company counts, never added together:
  recommendation  recommendation_points  the connection has given the user a LinkedIn recommendation or received one
                                         (7-recommendations/, engine/recommendations.py); always counts
  plus            plus_points            someone the user would ask for a referral
  neutral         neutral_points         someone the user wouldn't ask; still worth something, because a recruiter who
                                         sees the connection may ask them, or weigh it, on their own
A connection the user hasn't classified yet scores at the level named by "unclassified" (default "plus", the old
flat bonus), and the report lists them so the next calibration can ask.

The user's calls live in 5-criteria/connections.json:
  {"people": {"<first-last>": {"name": "First Last", "strength": "plus" | "neutral", "decided": "YYYY-MM-DD",
                               "job_ids": ["..."], "note": "..."}}}
The key is the name in lowercase with hyphens, matched against a job's connections list (as recommendations are).
"job_ids" ties a person to jobs whose connection list wasn't captured (only the posting's teaser named them).

Without neutral_points in spec.json the older rule stands: the review's bonus, raised to recommendation_points for a
recommendation (recommendations.network_points). A job with no named connection keeps the review's own bonus (for
example a referral recorded by hand).

Usage:  python engine/connections.py [--data DATA]      every connection on a current job, with its level and points
"""
import argparse
import re

import recommendations
from paths import Paths, read_json

LEVELS = ("recommendation", "plus", "neutral")


def settings(spec):
    """The network settings, or None when spec.json doesn't use the three levels."""
    net = (spec.get("scoring") or {}).get("network") or {}
    if not isinstance(net.get("neutral_points"), (int, float)):
        return None
    plus = net.get("plus_points", net.get("points", 8))
    pts = {"recommendation": net.get("recommendation_points", plus), "plus": plus, "neutral": net["neutral_points"]}
    unc = net.get("unclassified", "plus")
    if unc not in pts:
        raise SystemExit(f"spec.json scoring.network.unclassified must be one of {', '.join(pts)}; got {unc!r}")
    return pts, unc


def load(P):
    """{slug: entry} from 5-criteria/connections.json; each entry has name, strength and job_ids."""
    data = read_json(P.connections, {}, expect=dict)
    people = data.get("people")
    if people is None:
        people = {}
    if not isinstance(people, dict):  # e.g. a hand-edited "people": [] (empty lists are falsy, so test the type)
        raise SystemExit(f"{P.connections.name}: \"people\" must be an object keyed by first-last name")
    out = {}
    for key, e in people.items():
        if not isinstance(e, dict) or e.get("strength") not in ("plus", "neutral"):
            raise SystemExit(f"{P.connections.name}: '{key}' needs \"strength\": \"plus\" or \"neutral\"")
        out[recommendations.slug(key)] = {"name": e.get("name") or key, "strength": e["strength"],
                                          "job_ids": job_ids(P, key, e.get("job_ids"))}
    return out


def job_ids(P, key, value):
    """A person's job_ids as strings. Must be a list of job IDs (digits): "42" or 42 alone would otherwise turn into
    the wrong IDs (a string iterates as "4", "2")."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(i, (str, int)) and not isinstance(i, bool)
                                              and str(i).strip().isdigit() for i in value):
        raise SystemExit(f"{P.connections.name}: '{key}' \"job_ids\" must be a list of job IDs, "
                         f"e.g. [\"4482029334\"]; got {value!r}")
    return [str(i).strip() for i in value]


def people_at(job, recs, people):
    """[(name, level)] for the job's connections: its named list plus anyone tied to it by job_ids. Level is
    'recommendation', 'plus', 'neutral' or 'unclassified'."""
    found, seen = [], set()

    def add(name, s):
        if s in seen:
            return
        seen.add(s)
        level = "recommendation" if s in recs else people[s]["strength"] if s in people else "unclassified"
        found.append((name, level))
    for c in job.get("connections_1st") or []:
        if isinstance(c, dict) and c.get("name"):
            add(c["name"], recommendations.slug(c["name"]))
    jid = str(job.get("job_id", ""))
    for s, e in people.items():
        if jid and jid in e["job_ids"]:
            add(e["name"], s)
    return found


def teaser_hints(job):
    """The lines of the posting's "People you can reach out to" teaser that point to a 1st-degree connection:
    "<first name> and others in your network", or a person marked "• 1st". Alumni lines and 2nd/3rd-degree people
    don't count. A hint is not a named connection (the teaser gives a first name at most), so it never scores; it
    only keeps a job from being removed without the user's word (remove_job.py)."""
    teaser = job.get("network_teaser")
    return [t.strip() for t in (teaser if isinstance(teaser, list) else [])
            if isinstance(t, str) and re.search(r"\bin your network\b|•\s*1st\b", t, re.I)]


def network_points(spec, review_bonus, job, recs, people):
    """-> (points, [(name, level)]). The best connection at the company sets the points."""
    cfg = settings(spec)
    if cfg is None:
        # The older rule: the review's bonus, raised for a recommendation. A recommender tied to the job only by
        # job_ids (named in the posting's teaser) counts too.
        found = people_at(job, recs, people)
        bonus = recommendations.network_points(spec, review_bonus, job, recs)
        rp = ((spec.get("scoring") or {}).get("network") or {}).get("recommendation_points")
        if isinstance(rp, (int, float)) and any(lv == "recommendation" for _, lv in found):
            bonus = max(bonus, rp)
        return bonus, found
    pts, unc = cfg
    found = people_at(job, recs, people)
    if not found:
        return review_bonus or 0, []
    return max(pts[unc if lv == "unclassified" else lv] for _, lv in found), found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data")
    a = ap.parse_args()
    P = Paths(a.data)
    spec = read_json(P.spec, {}, expect=dict)
    cfg = settings(spec)
    recs, people = recommendations.load(P), load(P)
    rows = []
    for f in sorted(P.jobs.glob("*.json")):
        j = read_json(f, {}, expect=dict)
        bonus, found = network_points(spec, (j.get("review") or {}).get("network_bonus", 0), j, recs, people)
        for name, lv in found:
            rows.append((lv, name, j.get("company"), j.get("title"), j.get("job_id"), bonus))
    if not rows:
        print("No named 1st-degree connections on current jobs.")
        return
    if cfg is None:
        print("spec.json has no neutral_points: the three connection levels are off.")
    for lv, name, company, title, jid, bonus in sorted(rows, key=lambda r: (LEVELS + ("unclassified",)).index(r[0])):
        print(f"  {lv:<14} {name}: {company} - {title} ({jid}) -> +{bonus}")
    unc = sorted({r[1] for r in rows if r[0] == "unclassified"})
    if unc:
        print(f"Not yet classified (ask: would you ask them for a referral?): {', '.join(unc)}")


if __name__ == "__main__":
    main()
