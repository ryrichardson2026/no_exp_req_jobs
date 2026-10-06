#!/usr/bin/env python3
"""
analyze/pay_dryrun.py - READ-ONLY dry run of the description pay parser.

Writes NOTHING. Reads every out/*/*/normalized.jsonl, and for each record whose
STRUCTURED pay is empty (salary_is_stated=False) runs normalize/pay.py against the
description. Reports:

  * how many records have no structured pay, and how many the parser would FILL,
    broken down by tenant (employer/source);
  * records flagged for review (TJX-style dual range) and ambiguous;
  * a sample of filled matches with the source sentence beside the parsed values;
  * a sample of dollar amounts found but REJECTED (non-wage / no period / out of band).

    python -m analyze.pay_dryrun               # full report
    python -m analyze.pay_dryrun --samples 20  # N filled samples (default 20)
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import pay as P                                  # noqa: E402
from normalize.enrich import load_pay_settings, pay_text, pay_allowed  # noqa: E402  same config/text/gate the apply uses


def tenant_of(path):
    return path.replace("\\", "/").split("/")[-2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=20)
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(ROOT, "out", "*", "*", "normalized.jsonl")))
    total = 0
    no_struct = 0
    per = {}          # tenant -> {empty, fill, floor, review, ambiguous, held}
    filled_samples = []
    rejected_samples = []
    review_samples = []

    for path in paths:
        tenant = tenant_of(path)
        cfg = load_pay_settings(tenant)
        d = per.setdefault(tenant, {"empty": 0, "fill": 0, "floor": 0,
                                    "review": 0, "ambiguous": 0, "held_oom": 0,
                                    "held": cfg["exclude"]})
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            total += 1
            if r.get("salary_is_stated"):
                continue
            no_struct += 1
            d["empty"] += 1
            if not pay_allowed(r, cfg):        # held tenant (BWW) or out-of-market posting
                d["held_oom"] += 1
                continue
            fill, review, pr = P.fill_from_text(pay_text(r),
                                                default_period=cfg["default_period"])
            if fill:
                d["fill"] += 1
                if fill["salary_max"] is None:
                    d["floor"] += 1
                if len(filled_samples) < 10_000:
                    filled_samples.append((tenant, r.get("company_name"),
                                           r.get("title"), fill))
            elif review:
                tag = "review" if "dual-range" in review else "ambiguous"
                d[tag] += 1
                review_samples.append((tenant, r.get("company_name"),
                                       r.get("title"), review))
            for rj in pr["rejected"]:
                if len(rejected_samples) < 60:
                    rejected_samples.append((tenant, r.get("title"), rj))

    # ---- summary ----
    print("=" * 84)
    print("PAY-FROM-DESCRIPTION DRY RUN  (writes nothing)")
    print("=" * 84)
    tot_fill = sum(d["fill"] for d in per.values())
    tot_floor = sum(d["floor"] for d in per.values())
    tot_amb = sum(d["ambiguous"] for d in per.values())
    held_oom = sum(d["held_oom"] for d in per.values())
    print(f"total records ................ {total}")
    print(f"no structured pay ............ {no_struct}  ({no_struct/total*100:.1f}% of corpus)")
    print(f"  parser WOULD FILL .......... {tot_fill}  ({tot_fill/no_struct*100:.1f}% of empties)"
          f"   [of which floors 'From $X': {tot_floor}]")
    print(f"  ambiguous (left empty) ..... {tot_amb}")
    print(f"  not run — out-of-market/held {held_oom}  (non-launched-state posting or pay_exclude)")
    print(f"  still empty (no stated pay)  {no_struct - tot_fill - tot_amb - held_oom}")

    print("\n" + "-" * 84)
    print("BY TENANT (only tenants with at least one empty-pay record)")
    print(f"{'tenant':30} {'empty':>6} {'fill':>6} {'floor':>6} {'ambig':>6}  note")
    print("-" * 84)
    for tenant, d in sorted(per.items(), key=lambda x: -x[1]["fill"]):
        if d["empty"] == 0:
            continue
        note = "HELD (pay_exclude)" if d["held"] else ""
        print(f"{tenant:30} {d['empty']:>6} {d['fill']:>6} {d['floor']:>6} "
              f"{d['ambiguous']:>6}  {note}")

    # ---- filled samples (mix of employers) ----
    print("\n" + "=" * 84)
    print(f"SAMPLE FILLED MATCHES (up to {a.samples}, spread across employers)")
    print("=" * 84)
    by_t = {}
    for s in filled_samples:
        by_t.setdefault(s[0], []).append(s)
    spread = []
    # round-robin across tenants so the sample is a mix, not one employer
    while len(spread) < a.samples and any(by_t.values()):
        for t in list(by_t):
            if by_t[t]:
                spread.append(by_t[t].pop(0))
                if len(spread) >= a.samples:
                    break
    for tenant, co, title, fill in spread:
        lo, hi, per_ = fill["salary_min"], fill["salary_max"], fill["pay_period"]
        if hi is None:
            rng = f"From ${lo:,.2f}"
        elif lo == hi:
            rng = f"${lo:,.2f}"
        else:
            rng = f"${lo:,.2f}-${hi:,.2f}"
        print(f"\n  {tenant} | {co} | {(title or '')[:52]}")
        print(f"    PARSED: {rng} {per_}")
        print(f"    FROM:   \"{fill['pay_evidence'][:120]}\"")

    # ---- ambiguous (left empty) samples ----
    if review_samples:
        print("\n" + "=" * 84)
        print(f"AMBIGUOUS — LEFT EMPTY ({len(review_samples)} total; showing up to 12)")
        print("=" * 84)
        for tenant, co, title, review in review_samples[:12]:
            print(f"\n  {tenant} | {co} | {(title or '')[:52]}")
            print(f"    {review}")

    # ---- rejected samples ----
    if rejected_samples:
        print("\n" + "=" * 84)
        print(f"DOLLAR AMOUNTS FOUND BUT REJECTED (showing up to 30)")
        print("=" * 84)
        for tenant, title, rj in rejected_samples[:30]:
            amt = f"${rj['lo']:,.2f}" if rj["lo"] == rj["hi"] else f"${rj['lo']:,.2f}-${rj['hi']:,.2f}"
            print(f"\n  {tenant} | {(title or '')[:48]}")
            print(f"    {amt} [{rj['period']}] -> {rj['reason']}")
            print(f"    \"{rj['text'][:100]}\"")


if __name__ == "__main__":
    main()
