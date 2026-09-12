#!/usr/bin/env python3
"""List the APPLICABLE jobs that carry NO functional category — the dashboard's
"uncategorized" alert, broken out so they can be reviewed and either accepted as-is
or used to extend normalize/category.py's CATEGORY_PATTERNS.

Reads out/applicable.jsonl (analyze/report.py output). No network.

  python -m analyze.uncategorized
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPLICABLE = os.path.join(ROOT, "out", "applicable.jsonl")


def main():
    if not os.path.exists(APPLICABLE):
        sys.exit("no out/applicable.jsonl — run `python -m analyze.report` first")
    recs = [json.loads(l) for l in open(APPLICABLE, encoding="utf-8") if l.strip()]
    unc = [r for r in recs if not (r.get("category") or [])]
    pct = (100 * len(unc) / len(recs)) if recs else 0
    print(f"UNCATEGORIZED APPLICABLE JOBS: {len(unc)} of {len(recs)} ({pct:.1f}%)")
    print("Applicable jobs no title pattern in normalize/category.py matched.")
    print("Review to accept as-is, or add a pattern to CATEGORY_PATTERNS.\n")

    by_emp = defaultdict(list)
    for r in unc:
        by_emp[r.get("company_name") or "?"].append(r)

    for emp in sorted(by_emp, key=lambda e: (-len(by_emp[e]), e)):
        rows = by_emp[emp]
        print(f"{emp}  ({len(rows)})")
        for r in sorted(rows, key=lambda x: (x.get("title") or "").lower()):
            loc = ", ".join(x for x in (r.get("city"), r.get("state")) if x)
            title = (r.get("title") or "")[:62]
            print(f"    {title:<62}  {loc}")
        print()

    print(f"— {len(unc)} uncategorized across {len(by_emp)} employers —")
    return 0


if __name__ == "__main__":
    sys.exit(main())
