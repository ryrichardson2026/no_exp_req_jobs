"""
Reporting, querying, and the /add-tenant handoff.

Discovery ends at a report; a human approves; only then does /add-tenant run.
Dispositions are queryable so "show everything that failed on volume" is a lookup,
not a re-run — candidates rejected on fixable grounds (volume, needs_review) are
worth revisiting; those rejected on permanent grounds never are.

Unknown platforms accumulate: a landing host seen three times across batches is
the next adapter to build, and that recommendation gets STATED, not left in a
column.
"""
from collections import Counter, defaultdict

from .record import (
    Candidate,
    ADD_TENANT_INPUTS,
    DISPOSITION_CANDIDATE,
    DISPOSITION_QUALIFIED,
    DISPOSITION_NEEDS_REVIEW,
    DISPOSITION_EXCLUDED,
    DISPOSITION_DEPRIORITIZED,
    DISPOSITION_RULED_OUT,
    PERMANENT_DISPOSITIONS,
)

# Recommend building an adapter once a platform is seen at least this many times.
ADAPTER_RECO_THRESHOLD = 3


def query(cands, disposition=None, tier=None, segment=None, platform=None,
          failed_on=None, revisitable=None):
    """Filter stored candidates.

    disposition   exact disposition
    tier          exact tier (int)
    segment       exact segment
    platform      exact platform key
    failed_on     substring match against the rationale (e.g. "volume")
    revisitable   True  -> only FIXABLE dispositions (worth revisiting)
                  False -> only PERMANENT dispositions (never revisit)
    """
    out = []
    for c in cands:
        if disposition is not None and c.disposition != disposition:
            continue
        if tier is not None and c.tier != tier:
            continue
        if segment is not None and (c.segment or "").lower() != segment.lower():
            continue
        if platform is not None and (c.platform or "").lower() != platform.lower():
            continue
        if failed_on is not None and failed_on.lower() not in (c.rationale or "").lower():
            continue
        if revisitable is True and c.disposition in PERMANENT_DISPOSITIONS:
            continue
        if revisitable is False and c.disposition not in PERMANENT_DISPOSITIONS:
            continue
        out.append(c)
    return out


def unknown_platforms(cands):
    """Tally platforms with no existing adapter, most-seen first.

    Returns [{platform, count, employers:[...], build_now:bool}]. A platform at or
    over ADAPTER_RECO_THRESHOLD is flagged build_now — that is the next adapter.
    """
    seen = defaultdict(list)
    for c in cands:
        # A permanently-rejected employer (excluded/ruled_out) must NOT drive an
        # adapter-build recommendation — we vetoed it, so it does not count toward
        # "the next adapter to build."
        if c.disposition in PERMANENT_DISPOSITIONS:
            continue
        if c.platform and c.adapter_exists is False:
            seen[c.platform].append(c.company)
    rows = [
        {"platform": p, "count": len(emps), "employers": emps,
         "build_now": len(emps) >= ADAPTER_RECO_THRESHOLD}
        for p, emps in seen.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["platform"]))
    return rows


def handoff_record(cand):
    """The exact dict /add-tenant consumes — the /add-tenant inputs and nothing else.

    No translation layer: keys are lifted straight off the candidate record. The
    decision-only fields (tier, disposition, sampled_applicable, ...) are dropped.
    """
    d = cand.to_dict()
    return {k: d[k] for k in ADD_TENANT_INPUTS}


def handoff_records(cand, rules=None):
    """One /add-tenant record PER market — the 'second scoped config' made concrete.

    Each record is exactly the /add-tenant inputs with `market` set to that market
    and `scope_params` pinned to that market's scope. When per-market scope was
    captured, only markets that CLEAR the gates are emitted (the rest still need
    review); each record is independently runnable (per the run-both flexibility),
    and `combined_market_search` records whether one query could also carry both.
    """
    from . import rules as R, evaluate as E
    base = handoff_record(cand)
    ms = cand.market_scope or {}
    if not ms:
        markets = cand.target_markets or ([cand.market] if cand.market else [""])
        return [{"market": (m or cand.market), "cleared": None,
                 "combined_market_search": cand.combined_market_search,
                 "record": {**base, "market": (m or cand.market)}} for m in markets]
    th = R.thresholds(rules or R.load_rules())
    out = []
    for m, s in ms.items():
        rec = {**base, "market": m, "scope_params": s.get("scope_params") or {"state": m}}
        out.append({"market": m, "cleared": not E._market_problems(m, s, th),
                    "combined_market_search": cand.combined_market_search, "record": rec})
    return out


def ready_for_handoff(cands, rules=None):
    """Qualified candidates, priority order, with a scoped /add-tenant record per
    CLEARED market (a thin market is held back, not handed off)."""
    q = [c for c in cands if c.disposition == DISPOSITION_QUALIFIED]
    q.sort(key=lambda c: (c.tier or 99, c.company.lower()))
    out = []
    for c in q:
        recs = [r for r in handoff_records(c, rules) if r["cleared"] in (True, None)]
        out.append({"company": c.company, "scoped_configs": recs})
    return out


_ORDER = [
    (DISPOSITION_QUALIFIED, "QUALIFIED - ready to hand to /add-tenant"),
    (DISPOSITION_CANDIDATE, "CANDIDATE - cleared Stage 1, awaiting an approved browser pass"),
    (DISPOSITION_NEEDS_REVIEW, "NEEDS REVIEW - fixable; a human decides"),
    (DISPOSITION_DEPRIORITIZED, "DEPRIORITIZED - classified and held"),
    (DISPOSITION_RULED_OUT, "RULED OUT - non-frontline segment (permanent)"),
    (DISPOSITION_EXCLUDED, "EXCLUDED - permanent (never open a browser)"),
]


def render_report(cands):
    """A human-readable approval report grouped by disposition, tiers within."""
    by_disp = defaultdict(list)
    for c in cands:
        by_disp[c.disposition].append(c)

    lines = []
    counts = Counter(c.disposition for c in cands)
    lines.append(f"# Discovery report - {len(cands)} candidate(s)")
    lines.append("")
    summary = ", ".join(f"{counts[d]} {d}" for d, _ in _ORDER if counts.get(d))
    lines.append(summary or "(no candidates)")
    lines.append("")

    for disp, header in _ORDER:
        group = by_disp.get(disp, [])
        if not group:
            continue
        group.sort(key=lambda c: (c.tier or 99, c.company.lower()))
        lines.append(f"## {header}  ({len(group)})")
        for c in group:
            tier = f"T{c.tier}" if c.tier else "T-"
            plat = c.platform or "?"
            adp = "existing-adapter" if c.adapter_exists else ("NEW-platform" if c.platform else "")
            head = f"  [{tier}] {c.company}  <{c.domain}>  {c.segment or '?'}  {plat} {adp}".rstrip()
            lines.append(head)
            if c.rationale:
                lines.append(f"        {c.rationale}")
        lines.append("")

    ups = unknown_platforms(cands)
    if ups:
        lines.append("## Unknown platforms (adapter-build candidates)")
        for u in ups:
            flag = "  <-- BUILD NEXT (seen %dx)" % u["count"] if u["build_now"] else ""
            lines.append(f"  {u['platform']}: {u['count']} - {', '.join(u['employers'])}{flag}")
        lines.append("")

    return "\n".join(lines)
