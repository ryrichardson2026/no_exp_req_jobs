#!/usr/bin/env python3
"""
Experience-disclosure classifier — No-Experience Job Network

Three levers, plus the thing they leave out:

  1. EXPLICIT_NONE   — the JD says it hires without experience or trains you
  2. ENTRY_LEVEL     — the JD says entry level
  3. REQUIREMENT     — the JD states an experience requirement (years, prior
                       experience, "experience required/preferred")
  4. NOT_DISCLOSED   — the JD says nothing about experience either way

(4) is an ABSENCE test, not a phrase test. It cannot be regexed for directly;
it is what remains when no experience-related language of any kind is found.
That makes it the least reliable of the four and the one most sensitive to the
phrase lists below — a missed pattern silently inflates NOT_DISCLOSED.

Precedence for the single `class` label is 1 > 2 > 3 > 4. Precedence loses
information, so the raw flags are reported alongside it and written to the CSV
independently. A posting can say "entry level" and "2+ years preferred" in the
same breath; the flags keep that visible, the label does not.

Education is tracked on a SEPARATE axis. A degree gate is not an experience
statement, and the master doc excludes degree-gated postings on their own terms.

Run standalone against one or more captures:
    python3 experience_classifier.py pull_2026-08-25 pull_entry_level --csv classified.csv
"""

import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

import analyze_pull as ap

# --- Lever 1: hires without experience / trains -----------------------------
P_NONE = re.compile(
    r"(no experience (is )?(required|necessary|needed|expected)|"
    r"no prior experience|no previous experience|without (any )?experience|"
    r"experience (is )?not (required|necessary|needed)|"
    r"we (will|'ll) train|willing to train|will train you|"
    r"training (is )?provided|paid training|we provide (full |complete )?training|"
    r"on[- ]the[- ]job training|all experience levels|"
    r"regardless of (your )?experience|even if you (have no|lack))"
)

# --- Lever 2: entry level ---------------------------------------------------
P_ENTRY = re.compile(r"(entry[\s-]?level|entry level position|no[\s-]?experience role)")

# --- Lever 3: an experience requirement is stated ---------------------------
P_REQUIRE = re.compile(
    r"(\d+\s*\+?\s*(-\s*\d+\s*)?(years?|yrs?)[^.]{0,30}experience|"
    r"experience (is )?(required|preferred|a plus|necessary|essential)|"
    r"(prior|previous|relevant|related|proven|demonstrated)\s+experience|"
    r"minimum (of )?\d+\s*(years?|yrs?)|at least \d+\s*(years?|yrs?)|"
    r"must have.{0,20}experience|requires? .{0,20}experience|"
    r"experienced (candidate|professional|technician|driver|operator))"
)

# --- Separate axis: education ----------------------------------------------
P_DEGREE = re.compile(
    r"(bachelor'?s?|master'?s?|associate'?s? degree|b\.?s\.?\b|b\.?a\.?\b|"
    r"college degree|degree (is )?(required|preferred)|four[- ]year degree)"
)
P_HS = re.compile(r"(high school (diploma|degree)|hs diploma|\bged\b|"
                  r"high school (or )?equivalent)")


def classify(record):
    """Returns (label, flags dict). Flags are independent; the label applies precedence."""
    t = ap.body(record)
    f = {
        "says_no_experience": bool(P_NONE.search(t)),
        "says_entry_level": bool(P_ENTRY.search(t)),
        "states_requirement": bool(P_REQUIRE.search(t)),
        "degree_language": bool(P_DEGREE.search(t)),
        "hs_ged_language": bool(P_HS.search(t)),
    }
    if f["says_no_experience"]:
        label = "1 EXPLICIT_NONE"
    elif f["says_entry_level"]:
        label = "2 ENTRY_LEVEL"
    elif f["states_requirement"]:
        label = "3 REQUIREMENT"
    else:
        label = "4 NOT_DISCLOSED"
    return label, f


def load_capture(indir):
    """Handles both flat captures (raw/<market>) and grid captures (<term>/raw/<market>)."""
    recs = []
    patterns = [os.path.join(indir, "raw", "*", "page_*.json"),
                os.path.join(indir, "*", "raw", "*", "page_*.json")]
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            with open(path) as f:
                blob = json.load(f)
            prov = blob.get("_provenance", {})
            for job in (blob.get("response", {}).get("jobs") or []):
                job["_market"] = prov.get("market")
                job["_page"] = prov.get("page")
                job["_query"] = prov.get("query")
                job["_term"] = prov.get("query_term") or prov.get("query")
                job["_capture"] = os.path.basename(indir.rstrip("/\\"))
                recs.append(job)
        if recs:
            break
    return recs


def report(name, recs, clean_only=True):
    """Returns markdown lines for one capture."""
    L = []
    pool = [r for r in recs
            if ap.geo_class(r).startswith("in-")
            and not ap.LEADGEN.search(ap.body(r))] if clean_only else recs
    L.append(f"\n### {name}\n")
    if not pool:
        L.append("No records survive the geo and lead-gen filters — "
                 "experience classification would describe nothing.\n")
        return L, pool
    L.append(f"Classified over the **{len(pool)}** records that are in the "
             f"requested state and not lead-gen (of {len(recs)} raw).\n")

    labels = Counter(classify(r)[0] for r in pool)
    L.append("\n" + ap.table(
        [[k, labels.get(k, 0), ap.pct(labels.get(k, 0), len(pool))]
         for k in ["1 EXPLICIT_NONE", "2 ENTRY_LEVEL", "3 REQUIREMENT", "4 NOT_DISCLOSED"]],
        ["Lever (precedence applied)", "Jobs", "Share"]))

    flags = defaultdict(int)
    for r in pool:
        for k, v in classify(r)[1].items():
            flags[k] += bool(v)
    L.append("\n**Independent flags — a posting can trip several:**\n")
    L.append(ap.table([[k.replace("_", " "), v, ap.pct(v, len(pool))]
                       for k, v in sorted(flags.items(), key=lambda x: -x[1])],
                      ["Flag", "Jobs", "Share"]))

    # The contradiction case
    contra = [r for r in pool
              if classify(r)[1]["says_no_experience"] and classify(r)[1]["states_requirement"]]
    contra2 = [r for r in pool
               if classify(r)[1]["says_entry_level"] and classify(r)[1]["states_requirement"]]
    L.append(f"\nPostings claiming no experience **and** stating a requirement: "
             f"{len(contra)} ({ap.pct(len(contra), len(pool))}). "
             f"Claiming entry level and stating a requirement: {len(contra2)} "
             f"({ap.pct(len(contra2), len(pool))}). These are the postings where "
             "precedence hides a conflict, and they are worth reading directly.\n")

    # Google's own absence signal, for comparison with lever 4
    nd = sum(1 for r in pool if (r.get("detected_extensions") or {}).get("no_degree_mentioned"))
    L.append(f"\nGoogle's `no_degree_mentioned` flag: {nd} ({ap.pct(nd, len(pool))}). "
             "That is an education-absence signal, not an experience-absence signal — "
             "it does not substitute for lever 4.\n")

    # What NOT_DISCLOSED actually looks like
    nds = [r for r in pool if classify(r)[0] == "4 NOT_DISCLOSED"]
    if nds:
        cats = Counter()
        for r in nds:
            for c in ap.categorize(r.get("title")):
                cats[c] += 1
        L.append("\n**NOT_DISCLOSED by category (HEURISTIC):**\n")
        L.append(ap.table([[k, v, ap.pct(v, len(nds))] for k, v in cats.most_common()],
                          ["Category", "Jobs", "Share of not-disclosed"]))
        lens = sorted(len(ap.strip_html(r.get("description")) or "") for r in nds)
        med = lens[len(lens) // 2] if lens else 0
        allen = sorted(len(ap.strip_html(r.get("description")) or "") for r in pool)
        L.append(f"\nMedian description length: **{med}** chars, against {allen[len(allen)//2]} "
                 "for the pool overall. A shorter median means not-disclosed is partly "
                 "a thin-posting artifact rather than a deliberate omission.\n")
        L.append("\n**Sample titles:** " +
                 "; ".join(sorted({(r.get("title") or "").strip() for r in nds})[:12]) + "\n")
    return L, pool


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_out = None
    if "--csv" in sys.argv:
        csv_out = sys.argv[sys.argv.index("--csv") + 1]
    if not args:
        sys.exit("Usage: experience_classifier.py <capture_dir> [more...] [--csv out.csv]")

    L = ["# Experience disclosure — three levers plus the omission\n",
         "Levers 1–3 are phrase tests. Lever 4 is an absence test and inherits "
         "every gap in the other three: a pattern the lists miss lands in "
         "NOT_DISCLOSED silently. Treat lever 4 as an upper bound.\n"]
    rows = []
    for d in args:
        recs = load_capture(d)
        if not recs:
            L.append(f"\n### {d}\n\nNo job records found under this path.\n")
            continue
        lines, pool = report(d, recs)
        L += lines
        for r in pool:
            lab, f = classify(r)
            rows.append([d, r.get("_term") or "", r.get("_market"), r.get("title"),
                         r.get("company_name"), r.get("location"), lab,
                         *["YES" if f[k] else "" for k in
                           ["says_no_experience", "says_entry_level", "states_requirement",
                            "degree_language", "hs_ged_language"]],
                         (r.get("detected_extensions") or {}).get("no_degree_mentioned"),
                         len(ap.strip_html(r.get("description")) or ""),
                         r.get("via"), r.get("apply_link")])

    out = "\n".join(L)
    print(out)
    if csv_out and rows:
        with open(csv_out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["capture", "query_term", "market", "title", "company", "location",
                        "lever", "says_no_experience", "says_entry_level",
                        "states_requirement", "degree_language", "hs_ged_language",
                        "google_no_degree_mentioned", "desc_chars", "via", "apply_link"])
            w.writerows(rows)
        print(f"\n[written] {csv_out}")


if __name__ == "__main__":
    main()
