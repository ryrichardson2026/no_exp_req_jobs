#!/usr/bin/env python3
"""
First-pull analyzer — No-Experience Job Network

Reads the raw capture written by pull_no_experience.py and answers the
questions the first pull exists to answer:

  1. Does "no experience" return real inventory, per market, and how deep?
  2. Did the provider return the market we asked for? (geo drift check)
  3. Which fields actually arrive, and how often are they populated?
  4. How much duplication is in the raw set, within and across markets?
  5. Who is supplying the apply link — employer-direct or aggregator?
  6. Do the descriptions actually carry no-experience / training language?
  7. Does the unfiltered pull spread across the eight categories?

Discovery over assumption: field names are read from the data, not assumed.
Anything heuristic is labelled HEURISTIC in the output.

Stdlib only. Run:
    python3 analyze_pull.py --in ./pull_2026-08-25 --report report.md --csv jobs.csv
"""

import argparse
import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# PROVISIONAL tier phrases. These are a starting scaffold, NOT the BBJ brief
# rules — those aren't in this environment and are not guessed at here.
# Confirm or replace before any number from section G is treated as measured.
# ---------------------------------------------------------------------------
STRONG = [
    "no experience required", "no experience necessary", "no prior experience",
    "no experience needed", "entry level, no experience", "we will train",
    "we'll train", "will train", "paid training provided", "no résumé",
    "no resume required",
]
MEDIUM = [
    "training provided", "paid training", "on the job training",
    "on-the-job training", "willing to train", "experience preferred but not required",
    "no experience", "entry level", "entry-level",
]
WEAK = [
    "training", "we train", "learn on the job", "all experience levels",
]

# HEURISTIC title -> category map, nine categories per the master doc §4.
CATEGORY_PATTERNS = {
    # Vocab extended 2026-09-02 from the audit of applicable-but-UNCLASSIFIED
    # titles (grocery-store dept format, Target inbound, healthcare-support admin,
    # the housekeep* regex fix). Category is additive and ungated - it labels, it
    # does not gate - so these move no verdict.
    "Administrative": r"\b(admin|administrative|clerk|clerical|receptionist|data entry|office assistant|front desk|scheduler|scheduling coord\w*|bookkeeper|human resources|\bhr\b|payroll|patient financial|revenue cycle|patient service[s]? (representative|coordinator)|registrar|registration|health information|\bhim\b|medical records)\b",
    "Customer Service": r"\b(customer service|call center|call centre|csr|customer support|contact center|dispatcher)\b",
    "Sales": r"\b(sales|account executive|canvasser|telesales|inside sales|outside sales|business development)\b",
    "Retail": r"\b(retail|cashier|store associate|sales associate|stocker|merchandiser|barista|shift lead|store manager|store mgr|asst store mgr|assistant store manager|dept leader|department leader|person in charge|\bpic\b|th person|rd person|nd person|team lead\w*|general merchandise|grocery|produce|meat|seafood|floral|apparel|garden ctr|dairy|starbucks|bakery|courtesy|bagger|checkout)\b",
    "Warehouse": r"\b(warehouse|forklift|picker|packer|material handler|order selector|loader|shipping|receiving|fulfillment|inbound|outbound|logistics|inventory|materials|supply chain|stocking|replenish)\b",
    "Construction": r"\b(construction|laborer|labourer|carpenter|roofer|framer|concrete|apprentice|helper|demolition)\b",
    "Security": r"\b(security|guard|patrol|loss prevention|surveillance|unarmed|armed officer)\b",
    "Facilities": r"\b(janitor|custodian|cleaner|housekeep\w*|facilities|maintenance|groundskeep|porter|environmental service|\bevs\b|engineer|journeyman)\b",
    # Ninth category. Patterns DERIVED from the captured corpus (Compass food-service
    # board + Providence dietary/nutrition titles), not guessed.
    # Grocery FOOD departments dual-tag Food Services AND Retail (a meat wrapper
    # works with food and is in-store) - additive, so both lanes. Pure retail
    # (cashier, courtesy, bagger) stays Retail-only; 'grocery'/center-store aisle
    # stocking stays Retail (not food-handling).
    "Food Services": r"\b(cook|baker|barista|bartender|chef|dishwasher|busser|server|waiter|waitress|catering|culinary|kitchen|cafeteria|concession|dietary|dining|nutrition|food service|foodservice|food worker|food prep|food transporter|banquet|deli|meat|seafood|produce|bakery|dairy|starbucks|order builder|general utility|food unit|\bfoh\b|\bfsw\b|food and beverage|meat cutter|meat wrapper)\b",
}

SHIFT_HINT = r"\b(1st shift|2nd shift|3rd shift|first shift|second shift|third shift|overnight|graveyard|swing shift|night shift|weekend)\b"

# HEURISTIC: hosts that indicate an aggregator rather than an employer/ATS.
AGGREGATOR_HOSTS = [
    "indeed.", "ziprecruiter.", "linkedin.", "jooble.", "lensa.", "talent.com",
    "simplyhired.", "glassdoor.", "monster.", "snagajob.", "jobget.",
    "careerbuilder.", "adzuna.", "trabajo.", "jobrapido.", "recruit.net",
]
ATS_HOSTS = [
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday", "icims.com",
    "taleo.net", "brassring", "ultipro", "paylocity", "paycom", "adp.com",
    "workforcenow", "smartrecruiters.com", "jobvite.com", "bamboohr.com",
    "ashbyhq.com", "successfactors",
]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load(indir):
    records = []
    runs = defaultdict(lambda: {"pages": 0, "location_used": set(),
                                "detected_location": set(), "errors": 0})
    for path in sorted(glob.glob(os.path.join(indir, "raw", "*", "page_*.json"))):
        with open(path) as f:
            blob = json.load(f)
        prov = blob.get("_provenance", {})
        resp = blob.get("response", {})
        market = prov.get("market") or os.path.basename(os.path.dirname(path))

        runs[market]["pages"] += 1
        runs[market]["location_requested"] = prov.get("location_requested")
        lu = (resp.get("search_parameters") or {}).get("location_used")
        dl = (resp.get("search_information") or {}).get("detected_location")
        if lu:
            runs[market]["location_used"].add(lu)
        if dl:
            runs[market]["detected_location"].add(dl)

        for job in (resp.get("jobs") or []):
            job["_market"] = market
            job["_retrieved_at"] = prov.get("retrieved_at")
            job["_page"] = prov.get("page")
            records.append(job)
    return records, runs


def tier(text):
    t = norm(text)
    if any(p in t for p in STRONG):
        return "STRONG"
    if any(p in t for p in MEDIUM):
        return "MEDIUM"
    if any(p in t for p in WEAK):
        return "WEAK"
    return "NONE"


def categorize(title):
    t = norm(title)
    hits = [c for c, pat in CATEGORY_PATTERNS.items() if re.search(pat, t)]
    return hits or ["UNCLASSIFIED"]


def apply_hosts(job):
    links = []
    if job.get("apply_link"):
        links.append(job["apply_link"])
    for al in (job.get("apply_links") or []):
        if isinstance(al, dict) and al.get("link"):
            links.append(al["link"])
    hosts = []
    for l in links:
        m = re.match(r"https?://([^/]+)", l)
        if m:
            hosts.append(m.group(1).lower())
    return hosts


def classify_hosts(hosts):
    joined = " ".join(hosts)
    if any(h in joined for h in ATS_HOSTS):
        return "ATS/employer-direct"
    if any(h in joined for h in AGGREGATOR_HOSTS):
        return "aggregator"
    return "other/unknown"


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def analyze(records, runs):
    L = []
    total = len(records)
    L.append("# First pull — analysis\n")
    L.append(f"Raw records: **{total}** across **{len(runs)}** markets. "
             "No deduplication applied before section D.\n")

    if not total:
        L.append("No job records found. Check the raw directory and manifest.")
        return "\n".join(L)

    # A — volume and depth
    L.append("\n## A. Volume and inventory depth\n")
    per_market = Counter(r["_market"] for r in records)
    rows = []
    for m, meta in runs.items():
        rows.append([m, per_market.get(m, 0), meta["pages"],
                     round(per_market.get(m, 0) / meta["pages"], 1) if meta["pages"] else 0])
    L.append(table(rows, ["Market", "Jobs", "Pages fetched", "Jobs/page"]))
    L.append("\nA market that stopped short of the page cap exhausted Google's "
             "pagination — that is the depth signal. A market that hit the cap "
             "has more inventory than was pulled.\n")

    # B — geo integrity
    L.append("\n## B. Geo integrity\n")
    rows = []
    for m, meta in runs.items():
        rows.append([m, meta.get("location_requested"),
                     "; ".join(sorted(meta["location_used"])) or "—",
                     "; ".join(sorted(meta["detected_location"])) or "—"])
    L.append(table(rows, ["Market", "Requested", "location_used (echoed)", "detected_location"]))

    state_of = {"seattle": ["WA", "Washington"], "tacoma": ["WA", "Washington"],
                "dallas": ["TX", "Texas"], "chicago": ["IL", "Illinois"]}
    rows = []
    for m in sorted(per_market):
        want = state_of.get(m, [])
        jobs = [r for r in records if r["_market"] == m]
        off = [r for r in jobs if want and not any(w.lower() in norm(r.get("location")) for w in want)]
        rows.append([m, len(jobs), len(off), pct(len(off), len(jobs))])
    L.append("\n" + table(rows, ["Market", "Jobs", "Out-of-state location", "Rate"]))
    L.append("\nOut-of-state results include legitimate remote postings as well as "
             "geo drift. The two are separated by reading the flagged rows in the CSV, "
             "not by this count alone.\n")
    offenders = Counter(norm(r.get("location")) for r in records
                        if state_of.get(r["_market"]) and
                        not any(w.lower() in norm(r.get("location"))
                                for w in state_of[r["_market"]]))
    if offenders:
        L.append("\nMost common off-market location strings: " +
                 ", ".join(f"`{k}` ({v})" for k, v in offenders.most_common(10)) + "\n")

    # C — field inventory
    L.append("\n## C. Field inventory and fill rate\n")
    L.append("Read from the data, not assumed. This is the input to the "
             "normalized job model (Immediate item 4).\n")
    keys = Counter()
    for r in records:
        for k, v in r.items():
            if k.startswith("_"):
                continue
            if v not in (None, "", [], {}):
                keys[k] += 1
    L.append(table([[f"`{k}`", n, pct(n, total)] for k, n in keys.most_common()],
                   ["Field", "Populated", "Fill rate"]))

    dkeys = Counter()
    for r in records:
        for k, v in (r.get("detected_extensions") or {}).items():
            if v not in (None, "", [], {}):
                dkeys[k] += 1
    if dkeys:
        L.append("\n**`detected_extensions` — the only structured sub-fields Google returns:**\n")
        L.append(table([[f"`{k}`", n, pct(n, total)] for k, n in dkeys.most_common()],
                       ["Sub-field", "Populated", "Fill rate"]))

    # description depth — the primary matching lever
    lens = sorted(len(r.get("description") or "") for r in records)
    def q(p):
        return lens[int(p * (len(lens) - 1))] if lens else 0
    L.append(f"\n**Description length (chars):** min {q(0)} · p25 {q(.25)} · median {q(.5)} · "
             f"p75 {q(.75)} · max {q(1)}. Records with no description: "
             f"{sum(1 for x in lens if x == 0)}.\n")
    L.append("Description depth is the primary matching lever. Thin descriptions "
             "cap what any matching layer can do, regardless of model quality.\n")

    # D — duplication
    L.append("\n## D. Duplication\n")
    def key(r):
        return (norm(r.get("company_name")), norm(r.get("title")), norm(r.get("location")))
    seen = Counter(key(r) for r in records)
    dupes = sum(v - 1 for v in seen.values() if v > 1)
    L.append(f"Dedupe rule: company + title + location. Unique: **{len(seen)}** of {total} "
             f"raw ({dupes} duplicate rows, {pct(dupes, total)}).\n")
    rows = []
    markets = sorted(per_market)
    for i, a in enumerate(markets):
        for b in markets[i + 1:]:
            ka = {key(r) for r in records if r["_market"] == a}
            kb = {key(r) for r in records if r["_market"] == b}
            rows.append([f"{a} ∩ {b}", len(ka & kb),
                         pct(len(ka & kb), min(len(ka), len(kb)))])
    if rows:
        L.append("\n" + table(rows, ["Market pair", "Shared jobs", "% of smaller set"]))
    L.append("\nRaw pull volume is not market size. Read the deduplicated number.\n")

    # E — source composition
    L.append("\n## E. Who supplies the posting and the apply link\n")
    via = Counter(norm(r.get("via")).replace("via ", "") for r in records if r.get("via"))
    L.append("**`via` (Google's stated source):**\n")
    L.append(table([[k or "—", v, pct(v, total)] for k, v in via.most_common(15)],
                   ["Source", "Jobs", "Share"]))
    cls = Counter(classify_hosts(apply_hosts(r)) for r in records)
    L.append("\n**Apply-link destination — HEURISTIC host match:**\n")
    L.append(table([[k, v, pct(v, total)] for k, v in cls.most_common()],
                   ["Classification", "Jobs", "Share"]))
    L.append("\nThe ATS/employer-direct share is the employer-discovery yield: every "
             "distinct ATS host here is a candidate for the direct-adapter list, "
             "which is the second purpose of the pull.\n")
    ats_hosts = Counter()
    for r in records:
        for h in apply_hosts(r):
            if any(a in h for a in ATS_HOSTS):
                ats_hosts[h] += 1
    if ats_hosts:
        L.append("\n**Distinct ATS hosts observed (candidate adapters):**\n")
        L.append(table([[f"`{h}`", n] for h, n in ats_hosts.most_common(25)],
                       ["Host", "Jobs"]))

    # F — structure vs free text
    L.append("\n## F. Structured vs. free text\n")
    sched = sum(1 for r in records if (r.get("detected_extensions") or {}).get("schedule"))
    posted = sum(1 for r in records if (r.get("detected_extensions") or {}).get("posted_at"))
    shift_txt = sum(1 for r in records if re.search(SHIFT_HINT, norm(r.get("description"))))
    shift_struct = sum(1 for r in records
                       if re.search(SHIFT_HINT, " ".join(str(v) for v in
                                    (r.get("detected_extensions") or {}).values()).lower()))
    L.append(table([
        ["Employment type (`schedule`)", sched, pct(sched, total), "structured"],
        ["Posted date (`posted_at`)", posted, pct(posted, total), "structured, relative"],
        ["Shift — in description text", shift_txt, pct(shift_txt, total), "FREE TEXT"],
        ["Shift — in a structured field", shift_struct, pct(shift_struct, total), "structured"],
    ], ["Attribute", "Jobs", "Rate", "Where it lives"]))
    L.append("\nThe gap between the last two rows is the parsing burden the doc "
             "already predicted for shift. This measures it.\n")

    # G — no-experience language
    L.append("\n## G. No-experience language — PROVISIONAL tiering\n")
    L.append("**These phrase lists are a scaffold, not the BBJ brief's tier rules.** "
             "Confirm or replace them before treating this distribution as measured.\n")
    tiers = Counter(tier((r.get("title") or "") + " " + (r.get("description") or ""))
                    for r in records)
    L.append(table([[t, tiers.get(t, 0), pct(tiers.get(t, 0), total)]
                    for t in ["STRONG", "MEDIUM", "WEAK", "NONE"]],
                   ["Tier", "Jobs", "Share"]))
    L.append("\nA high NONE share means the `q` string surfaced jobs whose text "
             "never actually claims to hire without experience — which is a finding "
             "about the query, not about the market.\n")

    # H — category spread
    L.append("\n## H. Category spread — HEURISTIC title match\n")
    cat = Counter()
    multi = 0
    for r in records:
        hits = categorize(r.get("title"))
        if len(hits) > 1:
            multi += 1
        for h in hits:
            cat[h] += 1
    L.append(table([[c, cat.get(c, 0), pct(cat.get(c, 0), total)]
                    for c in list(CATEGORY_PATTERNS) + ["UNCLASSIFIED"]],
                   ["Category", "Jobs", "Share of records"]))
    L.append(f"\nTitles matching more than one category: {multi} ({pct(multi, total)}). "
             "Shares sum above 100% because matching is additive, as category "
             "selection is.\n")
    L.append("A category with near-zero volume across all four markets is a "
             "category the unfiltered pull does not support yet. That is a "
             "configuration observation, not a decision.\n")

    return "\n".join(L)


def write_csv(records, path):
    cols = ["_market", "title", "company_name", "location", "via",
            "detected_schedule", "detected_posted_at", "salary",
            "desc_chars", "tier", "categories", "apply_class", "apply_link",
            "_retrieved_at"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in records:
            de = r.get("detected_extensions") or {}
            w.writerow([
                r.get("_market"), r.get("title"), r.get("company_name"),
                r.get("location"), r.get("via"),
                de.get("schedule"), de.get("posted_at"),
                de.get("salary") or r.get("salary"),
                len(r.get("description") or ""),
                tier((r.get("title") or "") + " " + (r.get("description") or "")),
                "|".join(categorize(r.get("title"))),
                classify_hosts(apply_hosts(r)),
                r.get("apply_link"), r.get("_retrieved_at"),
            ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", required=True)
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--csv", default="jobs.csv")
    args = ap.parse_args()

    records, runs = load(args.indir)
    report = analyze(records, runs)
    with open(args.report, "w") as f:
        f.write(report)
    if records:
        write_csv(records, args.csv)
    print(report)
    print(f"\n[written] {args.report}" + (f" · {args.csv}" if records else ""))


if __name__ == "__main__":
    main()
