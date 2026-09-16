#!/usr/bin/env python3
"""analyze/freshness.py — THE one call site of the recency rule.

Computes the per-card "New" badge (normalize/model.effective_new_date + is_new_within)
for every applicable record and writes out/freshness.json {internal_id -> is_new}. The
static bake (prerender/build.mjs) merges that onto each record; the card reads r.is_new.
Nothing else computes recency — one function, one call site, so the four-definition
drift that this replaces cannot recur.

  python -m analyze.freshness            # writes out/freshness.json, prints the count

No network. Reads out/applicable.jsonl (which carries first_seen/last_seen/posted_at/
employer_domain) + config/tenant_first_pull.json (explicit per-tenant onboarding dates,
the backfill cutoff) + config/freshness.json (the card window). The clock is the PULL
DATE (max last_seen — set for every record every pull), never now(): the output is
baked and must hold until the next bake regenerates it.
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

APPLICABLE = os.path.join(ROOT, "out", "applicable.jsonl")
OUT = os.path.join(ROOT, "out", "freshness.json")
FIRST_PULL_CFG = os.path.join(ROOT, "config", "tenant_first_pull.json")
FRESHNESS_CFG = os.path.join(ROOT, "config", "freshness.json")


def _load_first_pull(records):
    """{employer_domain -> first-pull date}. Explicit config is authoritative (set once at
    onboarding); a domain absent from it falls back to min(first_seen) over the data — the
    drift-prone fallback (min moves later as a tenant's earliest backfill retires)."""
    cfg = json.load(open(FIRST_PULL_CFG, encoding="utf-8")).get("first_pull", {})
    fp = {d: model.as_date(v) for d, v in cfg.items()}
    derived = defaultdict(list)
    for r in records:
        d = r.get("employer_domain")
        fs = model.as_date(r.get("first_seen"))
        if d and fs:
            derived[d].append(fs)
    for d, seen in derived.items():
        fp.setdefault(d, min(seen))     # fallback only where config is silent
    return fp


def main():
    if not os.path.exists(APPLICABLE):
        sys.exit("no out/applicable.jsonl — run `python -m analyze.report` first")
    records = [json.loads(l) for l in open(APPLICABLE, encoding="utf-8") if l.strip()]

    fresh_cfg = json.load(open(FRESHNESS_CFG, encoding="utf-8"))
    card_window = fresh_cfg.get("card_window_days", model.NEW_WINDOW_DAYS)

    # Pull date = the clock. max(last_seen) is set for EVERY record on EVERY pull, so it is
    # always this pull's moment (max(first_seen) would lag on a pull that found nothing new).
    pull_date = max((model.as_date(r.get("last_seen")) for r in records
                     if r.get("last_seen")), default=None)
    if pull_date is None:
        sys.exit("no last_seen on any record — cannot establish the pull date")

    first_pull = _load_first_pull(records)

    flags = {}
    for r in records:
        iid = r.get("internal_id")
        if not iid:
            continue
        eff = model.effective_new_date(r, first_pull)
        flags[iid] = model.is_new_within(eff, pull_date, card_window)

    n_new = sum(1 for v in flags.values() if v)
    payload = {"pull_date": pull_date.isoformat(), "card_window_days": card_window,
               "is_new": flags}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    print(f"freshness: {n_new} of {len(flags)} cards carry the New badge "
          f"(card window {card_window}d, pull date {pull_date.isoformat()}) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
