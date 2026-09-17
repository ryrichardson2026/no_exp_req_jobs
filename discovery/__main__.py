"""
Discovery CLI.

  python -m discovery classify <input.json|.jsonl>   Stage 1 over a list -> store
  python -m discovery report                          approval report from the store
  python -m discovery query [filters]                 queryable dispositions
  python -m discovery reeval [--all]                  re-dispose vs current rules, no re-fetch
  python -m discovery ingest <probe.json>             merge Stage-2 browser findings
  python -m discovery handoff [--key K]               /add-tenant record(s) for qualified
  python -m discovery show <key>                      dump one candidate

Input list rows are objects with the Stage-1 fields (company, domain, segment,
size_band, footprint, input_class, careers_url, ...). Unknown fields are ignored.
Stage 1 makes NO network calls.
"""
import argparse
import json
import sys

from . import rules as R
from . import store as S
from . import report as RP
from .record import Candidate


def _load_input(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return []
    if path.endswith(".jsonl"):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def cmd_classify(args):
    rules = R.load_rules()
    rows = _load_input(args.input)
    cands = []
    for row in rows:
        cand = Candidate.from_dict(row)
        cand = S.upsert_classified(cand, rules, force=args.force)
        cands.append(cand)
    print(RP.render_report(S.load_all()))
    return 0


def cmd_report(args):
    print(RP.render_report(S.load_all()))
    return 0


def cmd_query(args):
    cands = S.load_all()
    res = RP.query(
        cands,
        disposition=args.disposition,
        tier=args.tier,
        segment=args.segment,
        platform=args.platform,
        failed_on=args.failed_on,
        revisitable=(True if args.revisitable else (False if args.permanent else None)),
    )
    for c in res:
        print(f"[{('T%d' % c.tier) if c.tier else 'T-'}] {c.disposition:14} {c.company:28} {c.rationale}")
    print(f"\n{len(res)} match(es)")
    return 0


def cmd_reeval(args):
    rules = R.load_rules()
    changes = S.reevaluate_all(rules, only_stale=not args.all)
    if not changes:
        print("No dispositions changed.")
        return 0
    print(f"{len(changes)} disposition(s) changed:")
    for ch in changes:
        print(f"  {ch['company']:28} {ch['old']} -> {ch['new']}")
        print(f"        {ch['rationale']}")
    return 0


def cmd_ingest(args):
    rules = R.load_rules()
    patch = _load_input(args.probe)
    patch = patch[0] if isinstance(patch, list) else patch
    key = patch.get("domain") or patch.get("company") or args.key
    if not key:
        print("ingest: probe needs a domain/company, or pass --key", file=sys.stderr)
        return 2
    cand = S.apply_probe(str(key).strip().lower(), patch, rules)
    if cand is None:
        print(f"ingest: no stored candidate for key {key!r} — classify it first", file=sys.stderr)
        return 2
    print(f"{cand.company}: {cand.disposition}\n  {cand.rationale}")
    return 0


def cmd_handoff(args):
    rules = R.load_rules()
    if args.key:
        c = S.load(args.key)
        if not c:
            print(f"no candidate {args.key!r}", file=sys.stderr)
            return 2
        # Per-market scoped /add-tenant records (one config per market).
        print(json.dumps(RP.handoff_records(c, rules), indent=2, ensure_ascii=False))
        return 0
    ready = RP.ready_for_handoff(S.load_all(), rules)
    if not ready:
        print("No qualified candidates ready for /add-tenant.")
        return 0
    print(json.dumps(ready, indent=2, ensure_ascii=False))
    return 0


def cmd_show(args):
    c = S.load(args.key)
    if not c:
        print(f"no candidate {args.key!r}", file=sys.stderr)
        return 2
    print(json.dumps(c.to_dict(), indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="discovery")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("classify"); sp.add_argument("input"); sp.add_argument("--force", action="store_true"); sp.set_defaults(fn=cmd_classify)
    sp = sub.add_parser("report"); sp.set_defaults(fn=cmd_report)
    sp = sub.add_parser("query")
    sp.add_argument("--disposition"); sp.add_argument("--tier", type=int); sp.add_argument("--segment")
    sp.add_argument("--platform"); sp.add_argument("--failed-on", dest="failed_on")
    sp.add_argument("--revisitable", action="store_true"); sp.add_argument("--permanent", action="store_true")
    sp.set_defaults(fn=cmd_query)
    sp = sub.add_parser("reeval"); sp.add_argument("--all", action="store_true"); sp.set_defaults(fn=cmd_reeval)
    sp = sub.add_parser("ingest"); sp.add_argument("probe"); sp.add_argument("--key"); sp.set_defaults(fn=cmd_ingest)
    sp = sub.add_parser("handoff"); sp.add_argument("--key"); sp.set_defaults(fn=cmd_handoff)
    sp = sub.add_parser("show"); sp.add_argument("key"); sp.set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
