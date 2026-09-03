#!/usr/bin/env python3
"""
location/resolve.py - resolve a "city or zip" query to a visible set of cities.

The location filter is ONE field. A five-digit zip resolves, through Census
centroid data, to the nearby cities the person can see and adjust; anything else
matches a city name (exact or prefix, for type-ahead). Either way the output is
the same thing: a list of cities, each with its applicable-job count, that the
interface renders as removable chips.

WHAT THIS IS NOT:
  - Not a radius slider, not a map.
  - NEVER a per-job distance. The inventory has city-level geography only: a city
    centroid represents every job in that city as one point (Seattle alone is ~84
    sq mi), so a per-job distance would be precise-looking and wrong. Distance is
    used ONLY to order and threshold the city list and is never returned - there
    is deliberately no distance field in the response.

KNOWN LIMITATIONS (do not paper over):
  - ZCTAs are not USPS ZIP codes. The Census builds ZCTAs because ZIP-code land
    area is hard to define, and does not distribute USPS ZIP products. Some zips
    have no ZCTA - handled as kind="unmatched", NEVER by guessing the nearest zip.
  - Centroid-to-centroid distance is approximate, worse for large cities. This is
    acceptable ONLY because the output is a city list, not a mileage. Surfacing a
    mileage number would need a better method and a new decision.
  - Place-name matching between the inventory and the Places file is not clean.
    Unmatched inventory cities are reported at build time and are NOT fuzzy-matched
    into place; they stay selectable by name and are simply unreachable by zip.

READ-ONLY. Reads analyze/out/city_index.json and data/gazetteer/*.txt. Modifies
nothing. Python stdlib only.

Run:  python -m location.resolve      # prints the threshold table + build report
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CITY_INDEX = os.path.join(ROOT, "analyze", "out", "city_index.json")
GAZ = os.path.join(ROOT, "data", "gazetteer")
ZCTA_FILE = os.path.join(GAZ, "2025_Gaz_zcta_national.txt")
PLACE_FILE = os.path.join(GAZ, "2025_Gaz_place_national.txt")

# Radius is a CALLER parameter, not a constant. Settled, CLOSED set: 10 / 15 / 25,
# default 15 (from the threshold table - 15 keeps Seattle at 19 cities not 33; 25 is
# the ceiling for thin markets; 40 was dropped because Seattle then pulls ~half the
# state, which stops being a location filter). Anything outside the set is a caller
# bug and is REJECTED, not clamped. No wider option, no custom value, no slider.
VALID_RADII = (10, 15, 25)
DEFAULT_RADIUS = 15

# LSAD type words that trail a Census place NAME ("Seattle city", "Silverdale CDP").
_LSAD_SUFFIX = {"city", "town", "cdp", "village", "borough", "municipality"}


def _strip_place_type(name):
    """'Spokane Valley city' -> 'Spokane Valley'; 'Walla Walla East CDP' -> 'Walla
    Walla East'. Strips only a trailing known LSAD word - never alters the name."""
    toks = name.split()
    if toks and toks[-1].lower() in _LSAD_SUFFIX:
        toks = toks[:-1]
    return " ".join(toks)


# ---- lazy-loaded, parsed once ---------------------------------------------

_cache = {}


def _rows(path):
    # utf-8 with latin-1 fallback; pipe-delimited per the 2025 files.
    try:
        fh = open(path, "r", encoding="utf-8", newline="")
        return list(csv.DictReader(fh, delimiter="|"))
    except UnicodeDecodeError:
        fh = open(path, "r", encoding="latin-1", newline="")
        return list(csv.DictReader(fh, delimiter="|"))


def _clean(k):
    return (k or "").strip()


def city_index():
    if "cities" not in _cache:
        with open(CITY_INDEX, "r", encoding="utf-8") as fh:
            _cache["cities"] = json.load(fh)["cities"]
    return _cache["cities"]


def places():
    """{(name_casefold, state): (lat, lng)} from the Places file."""
    if "places" not in _cache:
        out = {}
        for r in _rows(PLACE_FILE):
            state = _clean(r.get("USPS"))
            name = _strip_place_type(_clean(r.get("NAME")))
            try:
                lat = float(_clean(r.get("INTPTLAT")))
                lng = float(_clean(r.get("INTPTLONG")))
            except (TypeError, ValueError):
                continue
            out[(name.casefold(), state)] = (lat, lng)
        _cache["places"] = out
    return _cache["places"]


def zctas():
    """{zcta5: (lat, lng)} from the ZCTA file."""
    if "zctas" not in _cache:
        out = {}
        for r in _rows(ZCTA_FILE):
            z = _clean(r.get("GEOID"))
            try:
                out[z] = (float(_clean(r.get("INTPTLAT"))),
                          float(_clean(r.get("INTPTLONG"))))
            except (TypeError, ValueError):
                continue
        _cache["zctas"] = out
    return _cache["zctas"]


def city_centroids():
    """Inventory cities joined to Places centroids: list of
    (city_dict, (lat,lng) or None). None = name-reachable, zip-unreachable."""
    if "centroids" not in _cache:
        p = places()
        out = []
        for c in city_index():
            out.append((c, p.get((c["city"].casefold(), c["state"]))))
        _cache["centroids"] = out
    return _cache["centroids"]


def _haversine(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    r = 3958.7613  # earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ---- the resolver ----------------------------------------------------------

def resolve(query, radius_miles=DEFAULT_RADIUS):
    """See module docstring. Returns the resolution dict. Never guesses a nearest
    zip; an unrecognized zip returns kind='unmatched'. radius_miles must be one of
    VALID_RADII - anything else is rejected (a caller bug), not clamped."""
    if radius_miles not in VALID_RADII:
        raise ValueError(f"radius_miles must be one of {VALID_RADII}, got {radius_miles!r}")
    q = (query or "").strip()

    # zip: exactly five digits
    if len(q) == 5 and q.isdigit():
        centroid = zctas().get(q)
        if centroid is None:
            return {"kind": "unmatched", "query": q, "cities": [], "job_count": 0,
                    "note": f"ZIP {q} has no Census ZCTA (ZCTAs are not USPS ZIP codes) "
                            f"and is not recognized - pick a city instead."}
        scored = []
        for c, cc in city_centroids():
            if cc is None:
                continue
            d = _haversine(centroid, cc)
            if d <= radius_miles:
                scored.append((d, c))
        scored.sort(key=lambda x: x[0])
        cities = [{"city": c["city"], "state": c["state"], "count": c["count"]}
                  for _d, c in scored]
        return {"kind": "zip", "query": q, "radius_miles": radius_miles,
                "resolved_zip": q, "cities": cities,
                "job_count": sum(c["count"] for c in cities)}

    # city-name match: exact or prefix (case-insensitive, trimmed), for type-ahead.
    # Ignores radius_miles entirely - a named city is the filter, not a distance.
    ql = q.casefold()
    if ql:
        exact, prefix = [], []
        for c in city_index():
            name = c["city"].casefold()
            if name == ql:
                exact.append(c)
            elif name.startswith(ql):
                prefix.append(c)
        hits = exact + sorted(prefix, key=lambda c: (c["city"], c["state"]))
        if hits:
            cities = [{"city": c["city"], "state": c["state"], "count": c["count"]}
                      for c in hits]
            return {"kind": "city", "query": q, "cities": cities,
                    "job_count": sum(c["count"] for c in cities)}
    return {"kind": "unmatched", "query": q, "cities": [], "job_count": 0,
            "note": f"no city in the inventory matches {q!r}."}


# ---- build report + threshold table ---------------------------------------

def main():
    for f in (CITY_INDEX, ZCTA_FILE, PLACE_FILE):
        if not os.path.exists(f):
            sys.exit(f"missing input: {f}")

    cc = city_centroids()
    matched = [(c, xy) for c, xy in cc if xy is not None]
    unmatched = [c for c, xy in cc if xy is None]

    print(f"city index: {len(cc)} cities   matched to Places centroid: {len(matched)}"
          f"   unmatched (name-reachable, zip-unreachable): {len(unmatched)}")
    print(f"ZCTAs loaded: {len(zctas())}   Places loaded: {len(places())}")
    if unmatched:
        print("\nUNMATCHED inventory cities (NOT fuzzy-matched; stay selectable by name):")
        for c in unmatched:
            print(f"  {c['city']}, {c['state']}  (jobs: {c['count']})")

    print(f"\n\nRESOLVE DEMO - settled radii {VALID_RADII} (default {DEFAULT_RADIUS}); "
          f"cities / jobs, city-list only, no distance returned")
    zips = [("98661", "Vancouver"), ("98101", "Seattle"), ("99201", "Spokane"),
            ("98371", "Puyallup"), ("98801", "Wenatchee")]
    print(f"\n  {'zip':<8}{'area':<12}" + "".join(f"{str(r)+'mi':>14}" for r in VALID_RADII))
    print("  " + "-" * (20 + 14 * len(VALID_RADII)))
    for z, label in zips:
        if zctas().get(z) is None:
            print(f"  {z:<8}{label:<12}  ZIP not recognized (no ZCTA)")
            continue
        cells = []
        for r in VALID_RADII:
            res = resolve(z, radius_miles=r)
            cells.append(f"{len(res['cities'])}c / {res['job_count']}j")
        print(f"  {z:<8}{label:<12}" + "".join(f"{c:>14}" for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
