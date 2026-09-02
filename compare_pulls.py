#!/usr/bin/env python3
"""
Compare two pull captures — No-Experience Job Network

Answers the question two query phrases across the same geos exist to answer:
does "entry level" reach inventory that "no experience" does not, and vice versa?

Reads the raw captures written by pull_no_experience.py. Reads only; changes
nothing. Dedupe key is the project rule: company + title + location.

    python3 compare_pulls.py --a ./pull_no_experience --b ./pull_entry_level \
        --label-a "no experience" --label-b "entry level" --report compare.md
"""

import argparse
import glob
import json
import os
import re
from collections import Counter, defaultdict

import analyze_pull as ap  # reuse tier(), categorize(), norm(), table(), pct()


def load(indir):
    """market -> {key: record}, keeping the first occurrence."""
    by_market = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(indir, "raw", "*", "page_*.json"))):
        with open(path) as f:
            blob = json.load(f)
        prov = blob.get("_provenance", {})
        market = prov.get("market") or os.path.basename(os.path.dirname(path))
        for job in (blob.get("response", {}).get("jobs") or []):
            key = (ap.norm(job.get("company_name")),
                   ap.norm(job.get("title")),
                   ap.norm(job.get("location")))
            by_market[market].setdefault(key, job)
    return by_market


def dist(records, fn):
    c = Counter()
    for r in records:
        for v in (fn(r) if isinstance(fn(r), list) else [fn(r)]):
            c[v] += 1
    return c


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, help="first capture directory")
    p.add_argument("--b", required=True, help="second capture directory")
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.add_argument("--report", default="compare.md")
    args = p.parse_args()

    A, B = load(args.a), load(args.b)
    la, lb = args.label_a, args.label_b
    markets = sorted(set(A) | set(B))

    L = [f"# Query comparison — \"{la}\" vs \"{lb}\"\n",
         "Deduplicated within each capture on company + title + location "
         "before any comparison. Counts are unique jobs, not raw rows.\n"]

    # Per-market overlap
    rows = []
    tot_a = tot_b = tot_both = 0
    for m in markets:
        ka, kb = set(A.get(m, {})), set(B.get(m, {}))
        both = ka & kb
        tot_a += len(ka); tot_b += len(kb); tot_both += len(both)
        union = len(ka | kb)
        rows.append([m, len(ka), len(kb), len(both),
                     ap.pct(len(both), union), len(ka - kb), len(kb - ka)])
    rows.append(["**all**", tot_a, tot_b, tot_both, "—", "—", "—"])
    L.append("\n## Overlap by market\n")
    L.append(ap.table(rows, ["Market", f"{la} unique", f"{lb} unique", "In both",
                             "Overlap (of union)", f"Only {la}", f"Only {lb}"]))
    L.append("\nHigh overlap means the two phrases reach the same inventory and "
             "the second query buys little. Low overlap means each phrase reaches "
             "jobs the other misses, and the sourcing question is separate from "
             "the positioning question.\n")

    # What is unique to each
    only_a = [r for m in markets for k, r in A.get(m, {}).items() if k not in B.get(m, {})]
    only_b = [r for m in markets for k, r in B.get(m, {}).items() if k not in A.get(m, {})]
    both_r = [r for m in markets for k, r in A.get(m, {}).items() if k in B.get(m, {})]

    for name, recs in ((f"Only in \"{la}\"", only_a),
                       (f"Only in \"{lb}\"", only_b),
                       ("In both", both_r)):
        if not recs:
            continue
        L.append(f"\n## {name} — {len(recs)} jobs\n")
        t = dist(recs, lambda r: ap.tier((r.get("title") or "") + " " + (r.get("description") or "")))
        L.append("**Tier (PROVISIONAL phrase list):** " +
                 " · ".join(f"{k} {v} ({ap.pct(v, len(recs))})"
                            for k, v in [(x, t.get(x, 0)) for x in
                                         ["STRONG", "MEDIUM", "WEAK", "NONE"]]) + "\n")
        c = dist(recs, lambda r: ap.categorize(r.get("title")))
        L.append("\n**Categories (HEURISTIC):**\n")
        L.append(ap.table([[k, v, ap.pct(v, len(recs))] for k, v in c.most_common()],
                          ["Category", "Jobs", "Share"]))
        L.append("\n**Sample titles:** " +
                 "; ".join(sorted({(r.get("title") or "").strip() for r in recs})[:15]) + "\n")

    # Degree / experience gating in the unique-to-B set — the thing that decides
    # whether "entry level" inventory belongs in this product at all.
    gate = re.compile(r"\b(bachelor|master|degree required|b\.?s\.?\s|b\.?a\.?\s|"
                      r"\d\+?\s*years|minimum of \d|at least \d years)\b")
    for name, recs in ((la, only_a), (lb, only_b)):
        if not recs:
            continue
        n = sum(1 for r in recs if gate.search(ap.norm(r.get("description"))))
        L.append(f"\n**Degree or years-of-experience language in \"{name}\"-only "
                 f"descriptions:** {n} of {len(recs)} ({ap.pct(n, len(recs))}) — "
                 "HEURISTIC regex, read the flagged rows before acting on it.\n")

    out = "\n".join(L)
    with open(args.report, "w") as f:
        f.write(out)
    print(out)
    print(f"\n[written] {args.report}")


if __name__ == "__main__":
    main()
