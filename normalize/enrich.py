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
    category                the title -> category table (normalize/category.py),
                            additive; unmatched stores [] (never "UNCLASSIFIED")

Every other field is preserved value-for-value: the record is mutated in place,
existing keys keep their position and value, `credentials` (a new contract field)
is appended. No adapter is imported. One DELIBERATE tenant branch exists: a
tenant-assigned category (config/tenant_category.json, e.g. kroger.com -> Grocery),
applied to `category` AFTER the title table. It keys off employer_domain (already on
the record) - no adapter, no per-tenant vocabulary beyond that config map - so the
source-independence report.py holds everywhere except this one config-driven relabel.

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
from normalize import pay as PAY           # noqa: E402  the description pay parser
from normalize.category import categorize  # noqa: E402  the shared title->category table

OUT_GLOB = os.path.join(ROOT, "out", "*", "*", "normalized.jsonl")
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")

DERIVED = ("experience_condition", "evidence_clauses", "credentials")

_TAG = __import__("re").compile(r"<[^>]+>")
_WS = __import__("re").compile(r"\s+")


def pay_text(r):
    """The prose the pay parser reads: the record's own description_text, falling
    back to a tag-stripped description_html. Nothing else — pay is read from the
    description, never from a title or a sibling record."""
    t = r.get("description_text")
    if t:
        return t
    return _WS.sub(" ", _TAG.sub(" ", r.get("description_html") or "")).strip()


# The board publishes one state (the bake's launched-state allowlist, LAUNCHED_STATES
# in prerender/build.mjs). The description pay parser reads the pay stated on THIS
# record's posting; for an out-of-market posting that is out-of-market pay (measured:
# 100% of sub-WA-minimum description fills were Texas postings, e.g. a $10-16/hr TX
# abm/BWW row). Since those records can still reach jobs_list, we do NOT fill pay from
# a non-launched-state posting. A null state is tolerated (kept), matching the rest of
# the pipeline. Mirror the bake's allowlist here; keep in sync if a state launches.
LAUNCHED_STATES = frozenset({"WA"})


def pay_allowed(rec, cfg):
    """Whether the description pay parser may run for this record: tenant not held
    (pay_exclude) AND the posting is in a launched state (or stateless)."""
    if cfg.get("exclude"):
        return False
    st = rec.get("state")
    return (not st) or (st in LAUNCHED_STATES)


def load_pay_settings(tenant):
    """Per-tenant pay config from config/tenants.json -> extraction. Returns
    {default_period, exclude}. Both OFF unless a tenant opts in, so a lever is
    scoped to exactly the tenant that set it (same discipline as load_openers):

      pay_period_when_unstated : period to read a period-LESS figure at (Chipotle,
                                 owner-verified hourly). Still subject to the sane band.
      pay_exclude              : suppress the description pay parser for this tenant
                                 entirely (BWW, held pending owner confirmation)."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return {"default_period": None, "exclude": False}
    for _platform, tenants in cfg.items():
        if isinstance(tenants, dict) and isinstance(tenants.get(tenant), dict):
            ext = tenants[tenant].get("extraction") or {}
            return {"default_period": ext.get("pay_period_when_unstated"),
                    "exclude": bool(ext.get("pay_exclude"))}
    return {"default_period": None, "exclude": False}


def _load_tenant_category():
    """employer_domain -> single tenant-assigned category (e.g. {"kroger.com": "Grocery"}),
    plus the exception set that survives the shift as a SECOND tag. Read once at import.
    Assigned by TENANT, not title, so it never breaks when a source retitles its jobs."""
    path = os.path.join(ROOT, "config", "tenant_category.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return {}, ()
    return (cfg.get("map", {}), tuple(cfg.get("keep_categories", [])),
            {k: v for k, v in cfg.get("add", {}).items() if not k.startswith("_")})


TENANT_CATEGORY, KEEP_CATEGORIES, TENANT_CATEGORY_ADD = _load_tenant_category()


def tenant_of(path):
    return path.replace("\\", "/").split("/")[-2]   # out/<platform>/<tenant>/...


def enrich_records(recs, openers, pay_cfg=None):
    """Mutate each record in place with the extractor's output. Returns per-field
    populated counts (null/''/[] = unpopulated), plus section-found count."""
    pay_cfg = pay_cfg or {"default_period": None, "exclude": False}
    counts = {f: 0 for f in DERIVED}
    counts["section_found"] = 0
    counts["pay_from_description"] = 0
    counts["pay_review"] = 0
    for r in recs:
        xo = X.extract(r.get("description_html") or "",
                       r.get("description_text") or "",
                       r.get("qualifications_html") or "", openers)
        r["experience_condition"] = xo["experience_condition"]
        r["evidence_clauses"] = xo["evidence_clauses"]
        r["credentials"] = xo["credentials"]
        # Land the title -> category table. ADDITIVE: every matching category is
        # kept (a grocery meat cutter carries both Food Services and Retail).
        # LABELS ONLY - category moves no verdict; applicability is untouched.
        # An unmatched title stores [] (the categoryless state), NOT the analysis
        # layer's "UNCLASSIFIED" sentinel - that value looks like a category and
        # would eventually be treated as one. Empty means no category, which is true.
        cats = categorize(r.get("title"))
        cats = [] if cats == ["UNCLASSIFIED"] else cats
        # Tenant-assigned category (config/tenant_category.json), e.g. kroger.com -> Grocery: a
        # store's jobs ARE that store's category, regardless of department. Assigned by TENANT,
        # not title. Single-tag by design; only a genuine Warehouse/Security tag (KEEP_CATEGORIES),
        # detected by the title table above, survives the shift as a second category.
        forced = TENANT_CATEGORY.get(r.get("employer_domain"))
        if forced:
            keep = [c for c in cats if c in KEEP_CATEGORIES]
            cats = [forced] + keep
        # Additive SECTOR tag (config/tenant_category.json "add"), e.g. a healthcare employer:
        # keeps ALL the title/functional categories and appends the sector as a SECOND tag (a
        # MultiCare cafeteria cook -> Food Services + Healthcare). A title with no functional match
        # (PCT, patient transporter) already collapsed to [], so it gets Healthcare alone.
        add = TENANT_CATEGORY_ADD.get(r.get("employer_domain"))
        if add and add not in cats:
            cats = cats + [add]
        r["category"] = cats
        if xo["section_found"]:
            counts["section_found"] += 1

        # PAY. Structured always wins (rule 2): if an adapter already stated pay,
        # only stamp its provenance and leave the numbers untouched. Otherwise fall
        # back to the description parser — unless this tenant is held (pay_exclude).
        if r.get("salary_is_stated"):
            if not r.get("pay_source"):
                r["pay_source"] = "structured"
        elif pay_allowed(r, pay_cfg):
            fill, review, _pr = PAY.fill_from_text(
                pay_text(r), default_period=pay_cfg["default_period"])
            if fill:
                r["salary_min"] = fill["salary_min"]
                r["salary_max"] = fill["salary_max"]
                r["pay_period"] = fill["pay_period"]
                r["salary_is_stated"] = True
                r["pay_source"] = "description"
                r["pay_evidence"] = fill["pay_evidence"]
                counts["pay_from_description"] += 1
            elif review:
                r["pay_review"] = review
                counts["pay_review"] += 1

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
        pay_cfg = load_pay_settings(tenant)
        with open(path, "r", encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        counts = enrich_records(recs, openers, pay_cfg)
        n = len(recs)
        grand[tenant] = (n, counts)

        if not a.check:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tmp, path)

        # A seasonal/dormant tenant (allow_zero_records) can legitimately have 0 records
        # out of season - guard the percentage divisions so it prints 0.0% instead of crashing.
        pct = (lambda c: c / n * 100 if n else 0.0)
        print(f"\n{tenant}  ({n} records)  {path}")
        print(f"  section found        {counts['section_found']:>5}/{n}  "
              f"{pct(counts['section_found']):5.1f}%")
        for f in DERIVED:
            print(f"  {f:<20} {counts[f]:>5}/{n}  {pct(counts[f]):5.1f}%")
        if counts["pay_from_description"] or counts["pay_review"]:
            print(f"  pay from description {counts['pay_from_description']:>5}/{n}  "
                  f"{pct(counts['pay_from_description']):5.1f}%"
                  f"   (review: {counts['pay_review']})")

    total = sum(n for n, _ in grand.values())
    print("\n" + "-" * 78)
    print(f"TOTAL {total} records across {len(grand)} tenants")
    for f in ("experience_condition", "evidence_clauses", "credentials"):
        filled = sum(c[f] for _, c in grand.values())
        print(f"  {f:<20} {filled:>5}/{total}  {filled/total*100:5.1f}%")


if __name__ == "__main__":
    main()
