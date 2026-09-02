#!/usr/bin/env python3
"""
Grid summary — No-Experience Job Network

Reads a pull_grid.py capture and answers the test's actual question:
does sourcing by function + geo return local employer inventory, and how much
of it survives a POST-INGESTION filter for no-experience / entry-level language?

Sourcing and filtering are measured separately and in that order, which is the
whole point of the test.

Reuses analyze_pull.py for geo classification, lead-gen markers, HTML stripping
and category matching, so both scripts must sit in the same folder.

    python3 summarize_grid.py --in ./grid_seattle --report grid_summary.md --csv grid_jobs.csv
"""

import argparse
import csv
import glob
import json
import os
import re
from collections import Counter

import analyze_pull as ap
import experience_classifier as ec

# Post-ingestion experience filters, applied to title + description AFTER the
# occupation query has already sourced the inventory.
NO_EXP = re.compile(
    r"(no experience (required|necessary|needed)|no prior experience|"
    r"without experience|we will train|we'll train|will train|"
    r"training (is )?provided|paid training|on[- ]the[- ]job training|"
    r"willing to train|no experience)"
)
ENTRY = re.compile(r"(entry[- ]level|entry level)")
# Disqualifiers the master doc excludes outright.
EXCLUDE = re.compile(
    r"(bachelor'?s? degree|master'?s? degree|degree required|"
    r"\d+\+?\s*years of (relevant |related |prior )?experience|"
    r"minimum of \d+ years|at least \d+ years)"
)


def load(indir):
    """query_slug -> list of records"""
    out = {}
    for qdir in sorted(d for d in glob.glob(os.path.join(indir, "*"))
                       if os.path.isdir(d)):
        recs = []
        for path in sorted(glob.glob(os.path.join(qdir, "raw", "*", "page_*.json"))):
            with open(path) as f:
                blob = json.load(f)
            prov = blob.get("_provenance", {})
            for job in (blob.get("response", {}).get("jobs") or []):
                job["_market"] = prov.get("market")
                job["_page"] = prov.get("page")
                job["_term"] = prov.get("query_term") or os.path.basename(qdir)
                job["_q"] = prov.get("query")
                recs.append(job)
        if recs:
            out[os.path.basename(qdir)] = recs
    return out


def key(r):
    return (ap.norm(r.get("company_name")), ap.norm(r.get("title")),
            ap.norm(r.get("location")))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="indir", required=True)
    p.add_argument("--report", default="grid_summary.md")
    p.add_argument("--csv", default="grid_jobs.csv")
    args = p.parse_args()

    grid = load(args.indir)
    if not grid:
        raise SystemExit(f"No capture directories with job records found under '{args.indir}'.")

    L = ["# Function + geo query grid — summary\n",
         "Sourcing is measured first, experience filtering second. "
         "The occupation query does the sourcing; the experience test is applied "
         "to title + description after ingestion, never in `q`.\n"]

    # Stage 1 — sourcing quality per query
    L.append("\n## Stage 1 — sourcing: does the occupation query return local inventory?\n")
    rows = []
    for s, recs in grid.items():
        n = len(recs)
        inm = sum(1 for r in recs if ap.geo_class(r) == "in-metro")
        ins = sum(1 for r in recs if ap.geo_class(r).startswith("in-"))
        lg = sum(1 for r in recs if ap.LEADGEN.search(ap.body(r)))
        rows.append([recs[0]["_term"], n, f"{inm} ({ap.pct(inm, n)})",
                     ap.pct(ins, n), f"{lg} ({ap.pct(lg, n)})", len({key(r) for r in recs})])
    L.append(ap.table(rows, ["Query term", "Raw", "In metro", "In state",
                             "Lead-gen", "Unique"]))
    L.append("\nA term returning few in-metro records is a term Google does not "
             "localize well — that is a query finding, separate from whether the "
             "category has volume.\n")

    # Stage 2 — post-ingestion experience filter
    L.append("\n## Stage 2 — filtering: three levers plus the omission\n")
    L.append("Applied only to records that are in the requested state and not "
             "lead-gen. Levers 1-3 are phrase tests; lever 4 is what remains when "
             "a posting says nothing about experience either way. **This grid is "
             "the only capture that can size lever 4** — a pull sourced on an "
             "experience phrase contains that phrase by construction and reports "
             "NOT_DISCLOSED at or near zero.\n")
    rows = []
    allkeep = []
    for s, recs in grid.items():
        keep = [r for r in recs
                if ap.geo_class(r).startswith("in-")
                and not ap.LEADGEN.search(ap.body(r))]
        allkeep += keep
        if not keep:
            rows.append([recs[0]["_term"], 0, "—", "—", "—", "—", "—"])
            continue
        lab = Counter(ec.classify(r)[0] for r in keep)
        f = lambda k: f"{lab.get(k, 0)} ({ap.pct(lab.get(k, 0), len(keep))})"
        contra = sum(1 for r in keep
                     if ec.classify(r)[1]["states_requirement"]
                     and (ec.classify(r)[1]["says_no_experience"]
                          or ec.classify(r)[1]["says_entry_level"]))
        rows.append([recs[0]["_term"], len(keep),
                     f("1 EXPLICIT_NONE"), f("2 ENTRY_LEVEL"),
                     f("3 REQUIREMENT"), f("4 NOT_DISCLOSED"),
                     f"{contra} ({ap.pct(contra, len(keep))})"])
    L.append(ap.table(rows, ["Query term", "Sourced clean", "1 No experience",
                             "2 Entry level", "3 Requirement stated",
                             "4 Not disclosed", "Claims + contradicts"]))
    L.append("\nThe last column counts postings that claim no experience or entry "
             "level while also stating a requirement. Precedence assigns them to "
             "lever 1 or 2; the contradiction is the reason to read them.\n")

    if allkeep:
        L.append("\n### Lever 4 in detail — not disclosed\n")
        nds = [r for r in allkeep if ec.classify(r)[0] == "4 NOT_DISCLOSED"]
        L.append(f"**{len(nds)}** of {len(allkeep)} clean records "
                 f"({ap.pct(len(nds), len(allkeep))}) state nothing about "
                 "experience in either direction.\n")
        if nds:
            c = Counter(r["_term"] for r in nds)
            L.append("\n" + ap.table([[k, v, ap.pct(v, len(nds))] for k, v in c.most_common()],
                                     ["Query term", "Not disclosed", "Share of lever 4"]))
            lens = sorted(len(ap.strip_html(r.get("description")) or "") for r in nds)
            allen = sorted(len(ap.strip_html(r.get("description")) or "") for r in allkeep)
            L.append(f"\nMedian description length: **{lens[len(lens)//2]}** chars against "
                     f"{allen[len(allen)//2]} for the clean pool. A materially shorter "
                     "median means part of lever 4 is thin postings rather than "
                     "deliberate omission, and thin postings are the ones the "
                     "matching layer can do least with.\n")
            nd = sum(1 for r in nds if (r.get("detected_extensions") or {}).get("no_degree_mentioned"))
            L.append(f"\nCarrying Google's `no_degree_mentioned`: {nd} "
                     f"({ap.pct(nd, len(nds))}). Education absence is a separate axis "
                     "from experience absence and does not stand in for it.\n")

    # Overlap across the grid
    L.append("\n## Cross-query duplication\n")
    seen = Counter(key(r) for r in allkeep)
    dup = sum(v - 1 for v in seen.values() if v > 1)
    L.append(f"Clean records across all queries: **{len(allkeep)}**, "
             f"unique: **{len(seen)}** ({dup} duplicate rows, "
             f"{ap.pct(dup, len(allkeep))}).\n")
    L.append("\nDuplication here is a job matching more than one occupation term, "
             "which is expected and harmless while category selection is additive.\n")

    # Structured field availability on the clean set
    if allkeep:
        L.append("\n## Structured signal on the clean set\n")
        de = lambda r, k: (r.get("detected_extensions") or {}).get(k)
        rows = [
            ["`schedule`", sum(1 for r in allkeep if de(r, "schedule"))],
            ["`no_degree_mentioned`", sum(1 for r in allkeep if de(r, "no_degree_mentioned"))],
            ["`posted_at`", sum(1 for r in allkeep if de(r, "posted_at"))],
            ["`salary`", sum(1 for r in allkeep if de(r, "salary"))],
        ]
        L.append(ap.table([[k, v, ap.pct(v, len(allkeep))] for k, v in rows],
                          ["Field", "Populated", "Fill rate"]))
        L.append("\n**Source mix on the clean set:**\n")
        c = Counter(ap.norm(r.get("via")).replace("via ", "") for r in allkeep)
        L.append(ap.table([[k or "—", v, ap.pct(v, len(allkeep))]
                           for k, v in c.most_common(15)], ["Source", "Jobs", "Share"]))
        ats = Counter()
        for r in allkeep:
            for h in ap.apply_hosts(r):
                if any(a in h for a in ap.ATS_HOSTS):
                    ats[h] += 1
        if ats:
            L.append("\n**Distinct ATS hosts — candidate direct adapters:**\n")
            L.append(ap.table([[f"`{h}`", n] for h, n in ats.most_common(30)],
                              ["Host", "Jobs"]))

    out = "\n".join(L)
    with open(args.report, "w") as f:
        f.write(out)

    with open(args.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["query_term", "title", "company_name", "location", "via",
                    "geo_class", "leadgen", "lever", "no_exp_match",
                    "entry_level_match", "degree_or_years", "schedule",
                    "no_degree_mentioned", "posted_at", "categories", "apply_link"])
        for s, recs in grid.items():
            for r in recs:
                de = r.get("detected_extensions") or {}
                t = ap.body(r)
                w.writerow([r["_term"], r.get("title"), r.get("company_name"),
                            r.get("location"), r.get("via"), ap.geo_class(r),
                            "YES" if ap.LEADGEN.search(t) else "",
                            ec.classify(r)[0],
                            "YES" if NO_EXP.search(t) else "",
                            "YES" if ENTRY.search(t) else "",
                            "YES" if EXCLUDE.search(t) else "",
                            de.get("schedule"), de.get("no_degree_mentioned"),
                            de.get("posted_at"),
                            "|".join(ap.categorize(r.get("title"))),
                            r.get("apply_link")])

    print(out)
    print(f"\n[written] {args.report} · {args.csv}")


if __name__ == "__main__":
    main()
