"""LinkedIn recommendations: which 1st-degree connections have given the user a recommendation, or received one.

A connection who has vouched for the user in public (or whom the user has vouched for) is a stronger entry point than
a plain 1st-degree connection, so a job where one of them works scores higher: spec.json -> scoring.network ->
recommendation_points (instead of the plain connection bonus, never on top of it; either direction counts the same).

Data: 7-recommendations/<first-last>/, one folder per person (docs: "Recommendations"):
  received/recommendation.md   their recommendation for the user
  given/final.md               the user's recommendation for them, as posted
The folder name is the person's name in lowercase with hyphens; it is matched against the names on a job's
connections list the same way. A folder with neither file (a request still pending) doesn't count yet.

Usage:  python engine/recommendations.py [--data DATA]      lists the people and the current jobs they work at
"""
import argparse
import re
import unicodedata

from paths import Paths, read_json


def slug(name):
    """'Pat O'Example' -> 'pat-o-example': lowercase ASCII words joined by hyphens (folder names use the same form)."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return "-".join(w for w in re.split(r"[^a-z0-9]+", s) if w)


def load(P):
    """{slug: 'received' | 'given' | 'both'} for every person folder with at least one recommendation."""
    out = {}
    root = P.recommendations
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name == "archive":
            continue
        received = (d / "received" / "recommendation.md").is_file()
        given = (d / "given" / "final.md").is_file()
        if received or given:
            out[slug(d.name)] = "both" if received and given else "received" if received else "given"
    return out


def matches(job, recs):
    """[(name, direction)] for the job's 1st-degree connections who have a recommendation either way."""
    return [(c["name"], recs[slug(c["name"])]) for c in job.get("connections_1st", []) or []
            if isinstance(c, dict) and c.get("name") and slug(c["name"]) in recs]


def network_points(spec, review_bonus, job, recs):
    """The network bonus to use: the review's own bonus, raised to recommendation_points when a connection at the
    company has a recommendation. Without that setting in spec.json the review's bonus stands."""
    pts = ((spec.get("scoring") or {}).get("network") or {}).get("recommendation_points")
    if isinstance(pts, (int, float)) and matches(job, recs):
        return max(review_bonus or 0, pts)
    return review_bonus or 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data")
    a = ap.parse_args()
    P = Paths(a.data)
    recs = load(P)
    if not recs:
        print(f"No recommendations yet in {P.recommendations}.")
        return
    print(f"{len(recs)} people with a recommendation:")
    for s, d in recs.items():
        print(f"  {s}: {d}")
    hits = []
    for f in sorted(P.jobs.glob("*.json")):
        j = read_json(f, {}, expect=dict)
        for name, d in matches(j, recs):
            hits.append(f"  {name} ({d}): {j.get('company')} - {j.get('title')}")
    print("Current jobs where one of them is a 1st-degree connection:" if hits else
          "None of them is a 1st-degree connection on a current job.")
    for h in hits:
        print(h)


if __name__ == "__main__":
    main()
