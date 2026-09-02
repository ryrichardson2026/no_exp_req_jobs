#!/usr/bin/env python3
"""
normalize/enrich.py - run the shared extractor and PERSIST its output.

THE MISSING LAYER. Adapters map raw -> normalized.jsonl and leave the derived
fields empty by construction ("null by design - those are the extractor's job,
not the adapter's"). report.py re-ran the extractor at consolidation time and
threw the result away except for the gate. So experience_condition, evidence_clauses
and credentials read 0% on disk - the clause that makes a label auditable never
reached the record. This pass closes that gap.

CONTRACT ONLY, ADDITIVE ONLY. Reads each out/*/*/normalized.jsonl, runs the SAME
extractor report.py runs (X.extract with that tenant's forked openers - identical
call), and writes back ONLY the derived fields:

    experience_condition   the verdict
    evidence_clauses        the clauses behind it
    credentials             every named credential, its modality, its timeframe
    category                left as-is (empty []) - shape exists before the table

Every other field is preserved value-for-value: the record is mutated in place,
existing keys keep their position and value, `credentials` (a new contract field)
is appended. No adapter is imported, no tenant is branched on beyond loading that
tenant's vocabulary from config - the same source-independence report.py holds.

Run:  python -m normalize.enrich          # all tenants, in place
      python -m normalize.enrich --check  # report fill, write nothing
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import experience as X   # noqa: E402  the shared extractor

OUT_GLOB = os.path.join(ROOT, "out", "*", "*", "normalized.jsonl")

DERIVED = ("experience_condition", "evidence_clauses", "credentials")


def tenant_of(path):
    return path.replace("\\", "/").split("/")[-2]   # out/<platform>/<tenant>/...


def enrich_records(recs, openers):
    """Mutate each record in place with the extractor's output. Returns per-field
    populated counts (null/''/[] = unpopulated), plus section-found count."""
    counts = {f: 0 for f in DERIVED}
    counts["section_found"] = 0
    for r in recs:
        xo = X.extract(r.get("description_html") or "",
                       r.get("description_text") or "",
                       r.get("qualifications_html") or "", openers)
        r["experience_condition"] = xo["experience_condition"]
        r["evidence_clauses"] = xo["evidence_clauses"]
        r["credentials"] = xo["credentials"]
        if "category" not in r:
            r["category"] = []          # shape must exist before the table lands
        if xo["section_found"]:
            counts["section_found"] += 1
        for f in DERIVED:
            v = r.get(f)
            if v not in (None, "", [], {}):
                counts[f] += 1
    return counts


def main():
    ap = argparse.ArgumentParser(description="Persist extractor output into normalized.jsonl")
    ap.add_argument("--check", action="store_true",
                    help="report fill, write nothing")
    a = ap.parse_args()

    paths = sorted(glob.glob(OUT_GLOB))
    if not paths:
        sys.exit(f"no normalized.jsonl under {OUT_GLOB}")

    print("=" * 78)
    print("ENRICH - persist experience_condition / evidence_clauses / credentials")
    print("Same extractor report.py runs; forked openers per tenant; contract only.")
    if a.check:
        print("--check: reporting fill, writing nothing.")
    print("=" * 78)

    grand = {}
    for path in paths:
        tenant = tenant_of(path)
        openers = X.load_openers(tenant)
        with open(path, "r", encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        counts = enrich_records(recs, openers)
        n = len(recs)
        grand[tenant] = (n, counts)

        if not a.check:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tmp, path)

        print(f"\n{tenant}  ({n} records)  {path}")
        print(f"  section found        {counts['section_found']:>5}/{n}  "
              f"{counts['section_found']/n*100:5.1f}%")
        for f in DERIVED:
            print(f"  {f:<20} {counts[f]:>5}/{n}  {counts[f]/n*100:5.1f}%")

    total = sum(n for n, _ in grand.values())
    print("\n" + "-" * 78)
    print(f"TOTAL {total} records across {len(grand)} tenants")
    for f in ("experience_condition", "evidence_clauses", "credentials"):
        filled = sum(c[f] for _, c in grand.values())
        print(f"  {f:<20} {filled:>5}/{total}  {filled/total*100:5.1f}%")


if __name__ == "__main__":
    main()
