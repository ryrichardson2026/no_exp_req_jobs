#!/usr/bin/env python3
"""
analyze/city_index.py - the city picker's data, built from the inventory itself.

READ-ONLY. Reads out/applicable.jsonl and writes analyze/out/city_index.json.
Regenerate on every ingest run. No external data - a city with no applicable job
never appears, so the picker cannot return an empty result.

NORMALIZATION IS DELIBERATELY MINIMAL: casing and whitespace on the city name,
nothing else. Case/whitespace variants of one name merge (SEATTLE == Seattle).
Anything else - punctuation, spelling, abbreviation, neighborhood-vs-parent - is
NOT merged: both spellings are reported and near-duplicates are FLAGGED for a
human to decide. The code never decides two names are the same place.

Run:  python -m analyze.city_index
"""

import datetime
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPLICABLE = os.path.join(ROOT, "out", "applicable.jsonl")
OUT_DIR = os.path.join(HERE, "out")
OUT_JSON = os.path.join(OUT_DIR, "city_index.json")

# For labelling unplaceable records only (not used to alter any value).
DOMAIN_MAP = {
    "providence.org": "Providence", "kroger.com": "Kroger",
    "multicare.org": "MultiCare", "target.com": "Target",
    "aus.com": "Allied Universal", "dollargeneral.com": "Dollar General",
    "compass-usa.com": "Compass Group",
}


def norm_ws(s):
    return " ".join((s or "").split())


def alnum(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def lev(a, b):
    """Levenshtein distance, stdlib only. Used ONLY to flag near-duplicates for a
    human - never to merge."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main():
    if not os.path.exists(APPLICABLE):
        sys.exit(f"no applicable set at {APPLICABLE} - run analyze.report first")
    recs = [json.loads(l) for l in open(APPLICABLE, encoding="utf-8") if l.strip()]

    # group key: (casefolded city, upper state). Merges case/whitespace only.
    groups = defaultdict(lambda: {"count": 0, "variants": Counter()})
    unplaceable = []
    blank_state = []
    for r in recs:
        city = norm_ws(r.get("city"))
        state = norm_ws(r.get("state")).upper()
        if not city:
            jid = r.get("source_job_id") or r.get("internal_id")
            emp = DOMAIN_MAP.get((r.get("employer_domain") or "").lower(),
                                 r.get("company_name") or r.get("source_id"))
            unplaceable.append((jid, emp, repr(r.get("city")), repr(r.get("state"))))
            continue
        key = (city.casefold(), state)
        groups[key]["count"] += 1
        groups[key]["variants"][city] += 1
        if not state:
            blank_state.append((r.get("source_job_id"), city))

    # display name: title-cased normalized form (casing normalization). Where the
    # source variants disagree only on case, this is the single normalized display.
    cities = []
    for (ckey, state), g in groups.items():
        cities.append({"city": ckey.title(), "state": state, "count": g["count"],
                       "_variants": sorted(g["variants"])})
    cities.sort(key=lambda x: (x["city"], x["state"]))

    # near-duplicate flag: only NEAR-CERTAIN same-place variants, to avoid flagging
    # distinct WA cities that are merely similar (Edmonds/Redmond, North Bend/South
    # Bend are all real, separate places). Two precise signals: a single-character
    # difference (typo, e.g. Tukwila/Tukwilla), or a Ft./Mt./St. place-prefix form
    # of another city (the directive's "Ft. Vancouver" vs "Vancouver" case).
    # Directional prefixes (North/South/East/West) are NOT treated as variants -
    # they name distinct incorporated cities here. Truly a human decision; the code
    # only surfaces the strongest candidates and merges nothing.
    PLACE_PREFIX = {"ft", "fort", "mt", "mount", "st", "saint"}

    def strip_place_prefix(name):
        toks = name.split()
        if toks and toks[0].lower().rstrip(".") in PLACE_PREFIX:
            return alnum(" ".join(toks[1:]))
        return None

    by_state = defaultdict(list)
    for c in cities:
        by_state[c["state"]].append(c["city"])
    near_dups = []
    for state, names in by_state.items():
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                aa, bb = alnum(a), alnum(b)
                if aa == bb:
                    continue
                reason = None
                if lev(aa, bb) == 1 and min(len(aa), len(bb)) >= 5:
                    reason = "one-character difference (likely typo)"
                elif strip_place_prefix(a) == bb or strip_place_prefix(b) == aa:
                    reason = "Ft./Mt./St. place-prefix variant"
                if reason:
                    near_dups.append((state, a, b, reason))

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "cities": [{"city": c["city"], "state": c["state"], "count": c["count"]}
                   for c in cities],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    # ---- stdout report ----
    placed = sum(c["count"] for c in cities)
    print(f"city index: {len(cities)} distinct (city, state) groups, "
          f"{placed} records placed, {len(unplaceable)} unplaceable")
    print(f"wrote {OUT_JSON}")

    print("\nTOP 15 CITIES:")
    for c in sorted(cities, key=lambda x: -x["count"])[:15]:
        print(f"  {c['count']:>4}  {c['city']}, {c['state']}")

    print(f"\nUNPLACEABLE (blank / unparseable city) - {len(unplaceable)}, NOT dropped:")
    if not unplaceable:
        print("  none")
    for jid, emp, city_raw, state_raw in unplaceable:
        print(f"  {jid}  [{emp}]  city={city_raw} state={state_raw}")

    if blank_state:
        print(f"\nNOTE: {len(blank_state)} placed record(s) have a city but BLANK state "
              f"(grouped under state ''): {blank_state[:10]}")

    print(f"\nNEAR-DUPLICATE FLAGS (report only, NOT merged) - {len(near_dups)}:")
    if not near_dups:
        print("  none")
    for state, a, b, reason in near_dups:
        print(f"  {state}: '{a}'  vs  '{b}'  ({reason}) - you decide if same place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
