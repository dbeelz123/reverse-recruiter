"""Offline distance check for hybrid/on-site locations. No external geocoding service is called.

within_radius(location_text, center, radius_miles, home_state) returns True, False, or None (city not in the
table: flag for a manual check). Remote locations are handled by the caller.
The city table is the user's own: <data>/5-criteria/places.json, loaded with load_places(P). Add cities there as
new ones appear (lat, lon from any map).
"""
import json
import math
import re

from paths import read_json

# (city, state) -> (lat, lon), filled by load_places() from the user's places.json.
CITIES = {}


def load_places(P):
    """Load the user's gazetteer (5-criteria/places.json) into CITIES. Missing file: every city is 'unknown'."""
    CITIES.clear()
    if P.places.exists():
        for c in read_json(P.places).get("cities", []):
            CITIES[(c["city"].lower(), c["state"].upper())] = (c["lat"], c["lon"])
    return CITIES


def home_state_of(center_name):
    """'Springfield, IL' -> 'IL' (the state of the radius center), or None."""
    m = re.search(r",\s*([A-Za-z]{2})\b", center_name or "")
    return m.group(1).upper() if m else None


def miles(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def lookup(location_text):
    """'Springfield, IL (Hybrid)' / 'Greater Springfield (On-site)' / 'Columbus, OH' -> (lat, lon) or None."""
    text = re.sub(r"\(.*?\)", "", location_text).strip().lower()
    m = re.match(r"([a-z .'-]+?)(?:,\s*([a-z]{2}))?(?:,|$)", text)
    if not m:
        return None
    city, state = m.group(1).strip(), (m.group(2) or "").upper()
    # A state written in full ("Jacksonville, Florida, United States") is a state too: without this the city was
    # looked up by name alone and matched the same-named city in the user's table.
    state = state or state_of(location_text) or ""
    if state:
        return CITIES.get((city, state))
    hits = [v for (c, _), v in CITIES.items() if c == city]
    return hits[0] if len(hits) == 1 else None


def state_of(location_text):
    """The state named right after the city: 'Dallas, TX (On-site)' -> 'TX', 'Jacksonville, Florida, United States'
    -> 'FL'; None when the text has no such part ('Greater Springfield', 'Springfield, United States')."""
    parts = [p.strip() for p in re.sub(r"\(.*?\)", "", location_text or "").split(",")]
    if len(parts) < 2:
        return None
    if re.fullmatch(r"[A-Z]{2}", parts[1]):
        return parts[1]
    return STATE_ABBR.get(parts[1].lower())


US_STATES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
             "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
             "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
             "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland", "MA": "massachusetts",
             "MI": "michigan", "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana",
             "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico",
             "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
             "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
             "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
             "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming"}
STATE_ABBR = {name: abbr for abbr, name in US_STATES.items()}


def within_radius(location_text, center, radius_miles, home_state=None):
    """True/False when decidable; None when the place can't be placed (flag for a manual check).
    Assumes the radius is small next to the home state (about 50 miles from a center well inside it), so a city
    in any other state is out of range. With no home_state, an unknown city in a named state stays None.
    Deliberate (code reviews, 2026-11-25): for a center near a state line, add the nearby out-of-state cities to
    5-criteria/places.json; a listed city is always measured, never assumed."""
    pt = lookup(location_text)
    if pt is not None:
        return miles(pt, center) <= radius_miles
    text = re.sub(r"\(.*?\)", "", location_text).strip()
    # The state right after the city decides, abbreviated or in full, so "Huntington, West Virginia" isn't read as
    # Virginia and a city named like a state ("Oregon, Illinois") isn't read as that state.
    named = state_of(location_text)
    if named:
        return None if not home_state or named == home_state else False
    m = re.search(r",\s*([A-Z]{2})\b", text)
    if m:
        return None if not home_state or m.group(1) == home_state else False
    low = text.lower()
    others = [n for a, n in US_STATES.items() if a != home_state]
    if home_state and any(re.search(rf"\b{s}\b", low) for s in others):
        return False
    return None


def distance(location_text, center):
    pt = lookup(location_text)
    return None if pt is None else round(miles(pt, center))
