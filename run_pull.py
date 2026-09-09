#!/usr/bin/env python3
"""run_pull.py - one command for the recurring pull across onboarded tenants.

    python run_pull.py --all --publish     # the normal run: pull -> gate -> publish
    python run_pull.py --all               # pull -> gate -> stop at the table, no publish
    python run_pull.py --tenant kroger     # one tenant, re-run after a fix
    python run_pull.py --all --dry-run     # index/discovery only, no normalize, no downstream
    python run_pull.py --plan              # print the resolved run plan and exit (no network)
    python run_pull.py --update-baseline   # after a COMPLETE run: promote its numbers to baseline

SCOPE. This automates the RECURRING pull only. Tenant onboarding (read-surface id,
call-shape capture, --probe / --inspect, opener derivation) stays manual and stays a
gate; a new tenant is onboarded by hand and then added to config/tenants.json (+ a
platform entry in config/pull.json if it is a new code path).

It SHELLS OUT to what already exists and modifies no adapter, nothing in normalize/,
and not analyze/report.py. The platform key names the code path (python -m
adapters.<platform>); there is no tenant branching in this runner - the target/workday
split is expressed as data in config/pull.json, not as code here.

PIPELINE (two operator-visible deviations from the original step-8 sketch, both forced
by the data flow and flagged in the run output):
  * analyze/report.py runs at CONSOLIDATION - before the movement audit and before the
    push - because it PRODUCES out/applicable.jsonl, which is exactly what the push
    (analyze/supabase_sink.py) consumes. It is not a post-push step.
  * analyze/site_data.py (-> noprobjobs/data/jobs.js) is OMITTED. That generator is dead:
    the runtime SPA (data/supabase.js) and the static bake (prerender/build.mjs) both read
    Supabase directly; jobs.js is orphaned and supabase_sink.py's own docstring says it
    replaces it. Kept out of the publish path on purpose.

A PARTIAL run (any halt condition below) does NO push, NO bake, NO deploy - the prior
production build keeps serving. Publish is structurally reachable only when the computed
COMPLETE flag is true AND --publish is set AND this is not a dry run.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config")
OUT = os.path.join(ROOT, "out")
PRERENDER = os.path.join(ROOT, "prerender")
DEPLOY_DIR = os.path.join(PRERENDER, "out")
APPLICABLE = os.path.join(OUT, "applicable.jsonl")
REPORT_TXT = os.path.join(OUT, "applicable_report.txt")

# Halt thresholds (spec steps 6 + 7). Fixed policy, not per-run.
MIN_RECORD_FRACTION = 0.50      # a tenant under 50% of baseline records -> PARTIAL
MAX_DENSITY_MOVE = 15.0         # density more than 15 points off baseline -> PARTIAL
MAX_SET_MOVEMENT_PCT = 2.0      # more than 2% of the applicable set moves -> PARTIAL
MAX_EMPLOYER_MOVEMENT_PCT = 5.0 # any single employer over 5% movement -> PARTIAL


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_units(only_tenant):
    """Turn config/pull.json + config/tenants.json into an ordered work list of
    (platform, tenant, modes). Tenant identities come from tenants.json; the platform
    -> module + modes + section mapping comes from pull.json. No hardcoded tenants."""
    plan = load_json(os.path.join(CONFIG_DIR, "pull.json"))
    tenants_cfg = load_json(os.path.join(CONFIG_DIR, "tenants.json"))
    units = []
    for entry in plan["platforms"]:
        platform = entry["platform"]
        section = entry.get("section", platform)          # target borrows the workday section
        section_cfg = tenants_cfg.get(section, {})
        if entry.get("tenants"):
            keys = list(entry["tenants"])
        else:
            keys = [k for k in section_cfg if not k.startswith("_")]
        for key in keys:
            if key not in section_cfg:
                sys.exit(f"config error: tenant '{key}' not found under '{section}' in tenants.json")
            units.append({"platform": platform, "tenant": key, "modes": list(entry["modes"])})
    if only_tenant:
        units = [u for u in units if u["tenant"] == only_tenant]
        if not units:
            known = ", ".join(u["tenant"] for u in resolve_units(None))
            sys.exit(f"unknown tenant '{only_tenant}'. Known: {known}")
    return units


def normalized_path(platform, tenant):
    return os.path.join(OUT, platform, tenant, "normalized.jsonl")


def wc_l(path):
    if not os.path.exists(path):
        return None
    n = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


# --------------------------------------------------------------------------
# subprocess (sequential, never parallel - these sit behind Cloudflare)
# --------------------------------------------------------------------------

def run(cmd, cwd=ROOT, capture=False):
    """Run a child command, streaming its output. Returns (returncode, stdout_or_None)."""
    print(f"    $ {' '.join(cmd)}", flush=True)
    if capture:
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        if p.stdout:
            print(p.stdout, flush=True)
        if p.stderr:
            print(p.stderr, file=sys.stderr, flush=True)
        return p.returncode, p.stdout
    return subprocess.run(cmd, cwd=cwd).returncode, None


def adapter_cmd(platform, tenant, mode):
    # sys.executable, not "python3": use the same interpreter the runner runs under.
    return [sys.executable, "-m", f"adapters.{platform}", "--tenant", tenant, f"--{mode}"]


# --------------------------------------------------------------------------
# report.py per-tenant table parse (records / applicable / density)
# --------------------------------------------------------------------------

ROW_RX = re.compile(r"^\s+(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)%")


def parse_report_table(text):
    """Read the '### PER EMPLOYER' table analyze/report.py writes to applicable_report.txt.
    Returns {tenant: {records, applicable, density}}. report.py is not modified; this reads
    its output. The density column there is applicable/records*100 over the deduped kept set."""
    out = {}
    in_table = False
    for line in text.splitlines():
        if "### PER EMPLOYER" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if "records" in line and "applicable" in line:   # header row
            continue
        m = ROW_RX.match(line)
        if m:
            out[m.group(1)] = {"records": int(m.group(2)),
                               "applicable": int(m.group(3)),
                               "density": float(m.group(4))}
        elif out and not line.strip():                    # blank line after rows ends the table
            break
    return out


# --------------------------------------------------------------------------
# movement audit (spec step 7) - the guard, written to disk every run
# --------------------------------------------------------------------------

def read_applicable(path):
    if not os.path.exists(path):
        return None
    recs = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            recs[r.get("internal_id") or (r.get("source_id"), r.get("source_job_id"))] = r
    return recs


def _canon(lst):
    # category is a list of strings; credentials is a list of dicts. Canonicalize both to a
    # sorted tuple of stable strings so a set-equality diff works regardless of element type.
    out = []
    for x in (lst or []):
        out.append(x if isinstance(x, str) else json.dumps(x, sort_keys=True, ensure_ascii=False))
    return tuple(sorted(out))


def _cat(r):
    return _canon(r.get("category"))


def _cred(r):
    return _canon(r.get("credentials"))


def _exp(r):
    return r.get("experience_condition")


def movement_audit(prior, new, stamp):
    """Diff the new consolidated applicable set against the prior one, keyed on the stable
    internal_id, attributing every move to category / experience-verdict / credential-verdict
    by title and employer. Writes the full diff to out/movement/<stamp>.txt on EVERY run and
    returns (overall_pct, worst_employer, worst_employer_pct, halt, path)."""
    os.makedirs(os.path.join(OUT, "movement"), exist_ok=True)
    path = os.path.join(OUT, "movement", f"movement_{stamp}.txt")
    L = []

    def emp(r):
        return r.get("company_name") or r.get("source_id") or "(unknown)"

    def title(r):
        return r.get("title") or "(untitled)"

    if prior is None:
        L.append("FIRST RUN - no prior out/applicable.jsonl to diff against.")
        L.append(f"new applicable set: {len(new)} records. Movement threshold not applied.")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(L) + "\n")
        return 0.0, None, 0.0, False, path

    prior_ids, new_ids = set(prior), set(new)
    entered = new_ids - prior_ids
    left = prior_ids - new_ids
    both = prior_ids & new_ids

    changes = []   # (employer, title, field, old, new)
    for k in both:
        a, b = prior[k], new[k]
        if _cat(a) != _cat(b):
            changes.append((emp(b), title(b), "category", ",".join(_cat(a)) or "-", ",".join(_cat(b)) or "-"))
        if _exp(a) != _exp(b):
            changes.append((emp(b), title(b), "experience", _exp(a) or "-", _exp(b) or "-"))
        if _cred(a) != _cred(b):
            changes.append((emp(b), title(b), "credential", ",".join(_cred(a)) or "-", ",".join(_cred(b)) or "-"))

    moved_ids = entered | left | {k for k in both
                                  if _cat(prior[k]) != _cat(new[k])
                                  or _exp(prior[k]) != _exp(new[k])
                                  or _cred(prior[k]) != _cred(new[k])}
    denom = max(len(new_ids), len(prior_ids), 1)
    overall_pct = len(moved_ids) / denom * 100.0

    # per-employer movement over the union of that employer's ids
    union_by_emp = defaultdict(set)
    for k in new_ids:
        union_by_emp[emp(new[k])].add(k)
    for k in prior_ids:
        union_by_emp[emp(prior[k])].add(k)
    emp_pct = {}
    for e, ids in union_by_emp.items():
        moved_e = len(ids & moved_ids)
        emp_pct[e] = moved_e / max(len(ids), 1) * 100.0
    worst_emp, worst_pct = (None, 0.0)
    if emp_pct:
        worst_emp = max(emp_pct, key=emp_pct.get)
        worst_pct = emp_pct[worst_emp]

    halt = overall_pct > MAX_SET_MOVEMENT_PCT or worst_pct > MAX_EMPLOYER_MOVEMENT_PCT

    L.append(f"MOVEMENT AUDIT  {stamp}")
    L.append(f"prior set {len(prior_ids)}   new set {len(new_ids)}   moved {len(moved_ids)}"
             f"   ({overall_pct:.2f}% of the set)")
    L.append(f"entered {len(entered)}   left {len(left)}   verdict/category changes {len(changes)}")
    L.append(f"thresholds: set>{MAX_SET_MOVEMENT_PCT}% OR any employer>{MAX_EMPLOYER_MOVEMENT_PCT}%"
             f"  ->  {'HALT' if halt else 'within threshold'}")
    L.append("")
    L.append("PER-EMPLOYER MOVEMENT (union-of-ids basis):")
    for e in sorted(emp_pct, key=emp_pct.get, reverse=True):
        flag = "  <-- OVER" if emp_pct[e] > MAX_EMPLOYER_MOVEMENT_PCT else ""
        L.append(f"  {emp_pct[e]:6.2f}%  {len(union_by_emp[e]):>4}  {e}{flag}")
    L.append("")
    L.append("FIELD CHANGES (in both sets, verdict/category moved):")
    for e, t, f, a, b in sorted(changes):
        L.append(f"  [{f}] {e} | {t} : {a} -> {b}")
    L.append("")
    L.append("ENTERED (new to the applicable set):")
    for k in sorted(entered, key=lambda k: (emp(new[k]), title(new[k]))):
        L.append(f"  + {emp(new[k])} | {title(new[k])}")
    L.append("")
    L.append("LEFT (dropped from the applicable set):")
    for k in sorted(left, key=lambda k: (emp(prior[k]), title(prior[k]))):
        L.append(f"  - {emp(prior[k])} | {title(prior[k])}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return overall_pct, worst_emp, worst_pct, halt, path


# --------------------------------------------------------------------------
# baseline
# --------------------------------------------------------------------------

def load_baseline():
    return load_json(os.path.join(CONFIG_DIR, "baseline.json"))


def update_baseline(new_rows):
    path = os.path.join(CONFIG_DIR, "baseline.json")
    data = load_baseline()
    for tenant, row in new_rows.items():
        data["tenants"][tenant] = {"records": row["records"],
                                   "applicable": row["applicable"],
                                   "density": round(row["density"], 1)}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"updated baseline for: {', '.join(sorted(new_rows))}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description="Recurring pull orchestrator (config-driven).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="run every tenant in config/pull.json")
    g.add_argument("--tenant", metavar="KEY", help="run one tenant (re-run after a fix)")
    g.add_argument("--plan", action="store_true", help="print the resolved run plan and exit (no network)")
    g.add_argument("--update-baseline", action="store_true",
                   help="promote the last run's on-disk numbers into config/baseline.json")
    ap.add_argument("--publish", action="store_true", help="on a COMPLETE run, push+bake+deploy")
    ap.add_argument("--dry-run", action="store_true",
                    help="index/discovery only: no normalize, no consolidation, no downstream")
    a = ap.parse_args(argv)

    if a.publish and a.dry_run:
        sys.exit("--publish never runs from --dry-run.")

    # ---- --plan : prove the wiring, touch nothing ----
    if a.plan:
        units = resolve_units(None)
        print("RESOLVED RUN PLAN (config/pull.json x config/tenants.json)\n")
        print(f"  {'tenant':<16}{'module (python -m ...)':<26}{'section':<12}{'modes'}")
        for u in units:
            plan = load_json(os.path.join(CONFIG_DIR, "pull.json"))
            entry = next(e for e in plan["platforms"] if e["platform"] == u["platform"])
            section = entry.get("section", u["platform"])
            print(f"  {u['tenant']:<16}adapters.{u['platform']:<16}{section:<12}{' -> '.join(u['modes'])}")
            print(f"  {'':<16}out/{u['platform']}/{u['tenant']}/normalized.jsonl")
        return 0

    if a.update_baseline:
        # Read the latest report table off disk and promote it. Manual, explicit - never automatic.
        if not os.path.exists(REPORT_TXT):
            sys.exit(f"no {REPORT_TXT}; run a pull first, inspect it, then --update-baseline.")
        table = parse_report_table(open(REPORT_TXT, encoding="utf-8").read())
        if not table:
            sys.exit("could not parse a per-tenant table from the last report.")
        update_baseline(table)
        return 0

    units = resolve_units(a.tenant)
    baseline = load_baseline()["tenants"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("=" * 78)
    print(f"RECURRING PULL   {stamp}   {'DRY-RUN' if a.dry_run else ('PUBLISH' if a.publish else 'no-publish')}")
    print(f"tenants: {', '.join(u['tenant'] for u in units)}")
    print("=" * 78)

    # Step 4: capture prior record counts BEFORE normalize overwrites them.
    prior_counts = {u["tenant"]: wc_l(normalized_path(u["platform"], u["tenant"])) for u in units}

    # ---- run each tenant's mode sequence, sequential, never parallel ----
    results = {}   # tenant -> {platform, modes: {mode: ok/FAIL/skip}, failed_mode}
    any_mode_failed = False
    for u in units:
        platform, tenant = u["platform"], u["tenant"]
        modes = [u["modes"][0]] if a.dry_run else u["modes"]   # dry-run = enumerate step only
        print(f"\n--- {tenant} ({platform}) : {' -> '.join(modes)}"
              + ("   [dry-run: index/discovery only]" if a.dry_run else "") + " ---")
        mres, failed_mode = {}, None
        for mode in u["modes"]:
            if mode not in modes:
                mres[mode] = "skip"
                continue
            rc, _ = run(adapter_cmd(platform, tenant, mode))
            if rc != 0:
                mres[mode] = "FAIL"
                failed_mode = mode
                any_mode_failed = True
                print(f"    !! {tenant} {mode} exited {rc} - stopping this tenant, continuing to next")
                # mark remaining modes skipped
                for later in u["modes"][u["modes"].index(mode) + 1:]:
                    mres[later] = "skip"
                break
            mres[mode] = "ok"
        results[tenant] = {"platform": platform, "modes": mres, "failed_mode": failed_mode}

    if a.dry_run:
        print("\nDRY-RUN complete: index/discovery only, nothing normalized, no downstream.")
        for u in units:
            print(f"  {u['tenant']:<16} {results[u['tenant']]['modes']}")
        return 0

    # ---- consolidate: report.py -> out/applicable.jsonl (BEFORE audit + push) ----
    # Snapshot the prior applicable set in memory first, then let report.py overwrite it.
    prior_applicable = read_applicable(APPLICABLE)
    print("\n--- consolidate: analyze/report.py (all tenants on disk) ---")
    rc, _ = run([sys.executable, "-m", "analyze.report"])
    if rc != 0:
        print("!! report.py failed - cannot consolidate. Run is PARTIAL.")
        return _finish(units, results, prior_counts, baseline, None, None, partial=True,
                       publish=a.publish, complete=False, movement=None)

    table = parse_report_table(open(REPORT_TXT, encoding="utf-8").read())
    new_applicable = read_applicable(APPLICABLE)

    # ---- movement audit (always written to disk) ----
    mv_pct, worst_emp, worst_pct, mv_halt, mv_path = movement_audit(prior_applicable, new_applicable, stamp)
    print(f"\nmovement: {mv_pct:.2f}% of the set moved; worst employer "
          f"{worst_emp} {worst_pct:.2f}%  ->  {mv_path}")

    # ---- halt conditions (step 6) ----
    halts = []
    if any_mode_failed:
        for t, r in results.items():
            if r["failed_mode"]:
                halts.append(f"{t}: adapter mode '{r['failed_mode']}' exited non-zero")
    for u in units:
        t = u["tenant"]
        row = table.get(t)
        base = baseline.get(t)
        if row is None:
            halts.append(f"{t}: no rows in consolidated report (zero records?)")
            continue
        if row["records"] == 0:
            halts.append(f"{t}: zero records")
        elif base and row["records"] < MIN_RECORD_FRACTION * base["records"]:
            halts.append(f"{t}: {row['records']} records < 50% of baseline {base['records']}")
        if base and abs(row["density"] - base["density"]) > MAX_DENSITY_MOVE:
            halts.append(f"{t}: density {row['density']:.1f}% moved >15pts from baseline {base['density']:.1f}%")
    if mv_halt:
        halts.append(f"movement {mv_pct:.2f}% of set / worst employer {worst_emp} {worst_pct:.2f}% over threshold")

    complete = not halts
    return _finish(units, results, prior_counts, baseline, table, (mv_pct, worst_emp, worst_pct, mv_path),
                   partial=not complete, publish=a.publish, complete=complete, movement=halts)


def _finish(units, results, prior_counts, baseline, table, mv, partial, publish, complete, movement):
    # ---- output table (step 9) ----
    print("\n" + "=" * 78)
    print("RUN TABLE")
    print("=" * 78)
    hdr = f"{'tenant':<16}{'platform':<12}{'modes':<22}{'recs':>6}{'delta':>7}{'appl':>6}{'dens':>7}{'d-dens':>8}  flag"
    print(hdr)
    print("-" * len(hdr))
    total_appl = 0
    base_total_appl = 0
    for u in units:
        t, plat = u["tenant"], u["platform"]
        mres = results[t]["modes"]
        modestr = ",".join(m[0] + ("!" if mres.get(m) == "FAIL" else "" if mres.get(m) == "ok" else "-")
                           for m in u["modes"])
        row = (table or {}).get(t)
        base = baseline.get(t)
        recs = row["records"] if row else (prior_counts.get(t) or 0)
        appl = row["applicable"] if row else 0
        dens = row["density"] if row else 0.0
        d_recs = (recs - base["records"]) if base else 0
        d_dens = (dens - base["density"]) if base else 0.0
        total_appl += appl
        base_total_appl += base["applicable"] if base else 0
        flag = "clear"
        if results[t]["failed_mode"]:
            flag = f"FAIL:{results[t]['failed_mode']}"
        elif base and (recs == 0 or recs < 0.5 * base["records"] or abs(d_dens) > MAX_DENSITY_MOVE):
            flag = "FLAG"
        print(f"{t:<16}{plat:<12}{modestr:<22}{recs:>6}{d_recs:>+7}{appl:>6}{dens:>6.1f}%{d_dens:>+7.1f}  {flag}")

    print("-" * len(hdr))
    print(f"total applicable: {total_appl}   (baseline {base_total_appl}, delta {total_appl - base_total_appl:+d})")
    if mv:
        print(f"movement: {mv[0]:.2f}% of set; worst employer {mv[1]} {mv[2]:.2f}%   record: {mv[3]}")
    status = "COMPLETE" if complete else "PARTIAL"
    print(f"\nSTATUS: {status}")
    if partial:
        print("PARTIAL -> no push, no bake, no deploy. Prior production build keeps serving.")
        if movement:
            print("halt reasons:")
            for h in movement:
                print(f"  - {h}")

    # ---- downstream: only on COMPLETE + --publish (structurally gated) ----
    if complete and publish:
        return _publish()
    if publish and not complete:
        print("\n--publish requested but run is PARTIAL - publish withheld.")
    elif not publish:
        print("\n(no --publish: stopped at the table.)")
    return 0 if complete else 1


def _publish():
    """In order, halting immediately on any non-zero exit. report.py already ran at
    consolidation (it produces the applicable.jsonl the push consumes); site_data.py/jobs.js
    is intentionally omitted (dead - Supabase is the source of truth). A halt here leaves the
    prior production build serving."""
    print("\n" + "=" * 78)
    print("PUBLISH (COMPLETE)")
    print("=" * 78)

    steps = [
        ("push to Supabase", [sys.executable, "-m", "analyze.supabase_sink"], ROOT, False),
        ("bake (prerender build)", ["node", "build.mjs"], PRERENDER, False),
        ("retire", ["node", "retire.mjs"], PRERENDER, False),
    ]
    for name, cmd, cwd, cap in steps:
        print(f"\n--- {name} ---")
        rc, _ = run(cmd, cwd=cwd, capture=cap)
        if rc != 0:
            print(f"!! {name} exited {rc} - halting publish. Prior production build keeps serving.")
            return 1

    print("\n--- deploy (vercel --prod) ---")
    rc, out = run(["vercel", "deploy", "--prod", "--yes"], cwd=DEPLOY_DIR, capture=True)
    if rc != 0:
        print("!! deploy exited non-zero - halting. Prior production build keeps serving.")
        return 1
    url = ""
    for m in re.finditer(r"https://\S+\.vercel\.app", out or ""):
        url = m.group(0)
    print(f"\nSTATUS: COMPLETE + PUBLISHED   deploy: {url or '(url not captured - check vercel output)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
