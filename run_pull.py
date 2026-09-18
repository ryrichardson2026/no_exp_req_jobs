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
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

import runlog          # durable per-run record + local dashboard (additive; never fatal)

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config")
OUT = os.path.join(ROOT, "out")
RAW = os.path.join(ROOT, "raw")
PRERENDER = os.path.join(ROOT, "prerender")
DEPLOY_DIR = os.path.join(PRERENDER, "out")
APPLICABLE = os.path.join(OUT, "applicable.jsonl")
REPORT_TXT = os.path.join(OUT, "applicable_report.txt")

# Preflight ("prep") green-path checks (see preflight()). The publishable key + REST base ping
# Supabase read-only; CHROME is where the bake launches headless Chrome (mirrors prerender/build.mjs).
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://eyatyzatcmjnmazmaghd.supabase.co").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# The stamp of the run in progress — set as early as possible so the top-level crash handler can
# record a FAILED run under the SAME stamp if anything below throws before the record is emitted.
_CURRENT_STAMP = None

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
    # Windows: npm-installed CLIs (vercel) are .CMD/.ps1 shims with no .exe. CreateProcess
    # (shell=False) only appends .exe, so a bare "vercel" raises FileNotFoundError and sinks
    # the whole publish. Resolve the real path via PATHEXT-aware which() so node/python/vercel
    # all launch uniformly (no-op when cmd[0] is already an absolute/.exe path).
    exe = shutil.which(cmd[0])
    if exe:
        cmd = [exe, *cmd[1:]]
    if capture:
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        if p.stdout:
            print(p.stdout, flush=True)
        if p.stderr:
            # Fold the child's stderr into the tee'd stdout stream. Node (build.mjs,
            # retire.mjs) writes ALL its progress to stderr; routed to sys.stderr it
            # bypasses the per-stage tee and the stage logs empty (the bug this fixes).
            print(p.stderr, flush=True)
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

    # The movement guard gates on VERDICT/CATEGORY CHANGES to jobs present in BOTH pulls
    # (the "36 demoted" / "2 guards mistagged" cases the guard exists for). Jobs entering or
    # leaving is normal board turnover: a collapse is already caught by the record-floor halt
    # (step 6) and growth is never bad, so entered/left are REPORTED but do NOT gate the
    # publish - otherwise ordinary daily churn would halt every run and nothing could ship.
    changed_ids = {k for k in both
                   if _cat(prior[k]) != _cat(new[k])
                   or _exp(prior[k]) != _exp(new[k])
                   or _cred(prior[k]) != _cred(new[k])}
    denom = max(len(both), 1)                         # changes measured against the shared set
    overall_pct = len(changed_ids) / denom * 100.0

    # per-employer CHANGE rate over that employer's shared (present-in-both) set
    both_by_emp = defaultdict(set)
    for k in both:
        both_by_emp[emp(new[k])].add(k)
    emp_pct = {}
    for e, ids in both_by_emp.items():
        emp_pct[e] = len(ids & changed_ids) / max(len(ids), 1) * 100.0
    worst_emp, worst_pct = (None, 0.0)
    if emp_pct:
        worst_emp = max(emp_pct, key=emp_pct.get)
        worst_pct = emp_pct[worst_emp]

    halt = overall_pct > MAX_SET_MOVEMENT_PCT or worst_pct > MAX_EMPLOYER_MOVEMENT_PCT

    L.append(f"MOVEMENT AUDIT  {stamp}")
    L.append(f"prior set {len(prior_ids)}   new set {len(new_ids)}   shared {len(both)}")
    L.append(f"verdict/category CHANGES {len(changed_ids)} of shared ({overall_pct:.2f}%)  [gates publish]")
    L.append(f"entered {len(entered)}   left {len(left)}   [board turnover - reported, does NOT gate]")
    L.append(f"thresholds: changes >{MAX_SET_MOVEMENT_PCT}% of shared OR any employer >{MAX_EMPLOYER_MOVEMENT_PCT}%"
             f"  ->  {'HALT' if halt else 'within threshold'}")
    L.append("")
    L.append("PER-EMPLOYER CHANGE RATE (verdict/category flips over the shared set):")
    for e in sorted(emp_pct, key=emp_pct.get, reverse=True):
        if not emp_pct[e]:
            continue    # only list employers with an actual change; keeps the file readable
        flag = "  <-- OVER" if emp_pct[e] > MAX_EMPLOYER_MOVEMENT_PCT else ""
        L.append(f"  {emp_pct[e]:6.2f}%  {len(both_by_emp[e]):>4}  {e}{flag}")
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

# ---------------------------------------------------------------------------
# clean-capture: fresh enumerate + reconcile the detail cache to today's live set
# ---------------------------------------------------------------------------
# Correctness rule (settled with the operator): a job is LIVE iff its URL/id came back in
# THIS pull's listing (the index). The adapters, built for one-shot onboarding, fetch detail
# incrementally and never prune, and normalize reads the whole detail cache - so a job that
# left the board keeps a cached detail file, is re-emitted, and gets last_seen refreshed (a
# zombie). Fixed WITHOUT touching the adapters: before each pull, clear the enumerate output
# so the in-scope set is exactly this pull's, then reconcile the detail cache against that
# fresh in-scope set. A guard aborts the purge if the reconstructed live set doesn't reproduce
# the cache, so a scheme change can never delete live jobs. first_seen survives (seen_state
# lives in out/, not raw/).

# Enumerate output cleared before the enumerate mode (the detail cache is kept + reconciled,
# never wiped). (name, is_dir) under raw/<platform>/<tenant>/.
_ENUMERATE_ARTIFACT = {
    "oracle_orc": ("index", True), "workday": ("index", True),
    "radancy_tb": ("rows.jsonl", False), "target": ("discovery", True),
    "jibe_api": ("pages", True), "compass_api": ("pages", True),
    "phenom": ("records.jsonl", False),
    "ultipro": ("index.jsonl", False),
    "appcast": ("index.jsonl", False),
    "avature": ("index.jsonl", False),
    "paradox": ("records.jsonl", False),   # single-pass: records.jsonl carries descriptions inline
}


def clean_enumerate(platform, tenant):
    name, is_dir = _ENUMERATE_ARTIFACT.get(platform, (None, None))
    if not name:
        return
    path = os.path.join(RAW, platform, tenant, name)
    try:
        if is_dir and os.path.isdir(path):
            shutil.rmtree(path)
        elif not is_dir and os.path.isfile(path):
            os.remove(path)
    except OSError as e:
        print(f"    reconcile: could not clear {path}: {e}")


def _live_detail_names(platform, tenant_key):
    """Detail filenames implied by TODAY's in-scope index (+ extension), computed with the
    adapter's OWN load/in_scope so 'live' matches the adapter's own definition. Returns
    (set, ext), or (None, None) for platforms with no detail cache."""
    mod = importlib.import_module(f"adapters.{platform}")
    t = mod.load_tenant(tenant_key)
    if platform == "oracle_orc":
        return {f"{mod.job_id(j)}.json" for j in mod.load_index(t) if mod.in_scope(j, t) and mod.job_id(j)}, ".json"
    if platform == "workday":
        return {f"{mod.safe_name(mod.req_id(j))}.json" for j in mod.load_index(t) if mod.in_scope(j, t) and mod.req_id(j)}, ".json"
    if platform == "radancy_tb":
        return {f"{r['internal_id']}.html" for r in mod.load_rows(t) if mod.in_scope(r, t) and r.get("internal_id")}, ".html"
    if platform == "target":
        # discovery IS the live WA set; a superset of what detail holds, so it is purge-safe.
        return {f"{mod.safe_name(d.get('requisitionid'))}.json" for d in mod.load_discovery(t) if d.get("requisitionid")}, ".json"
    if platform == "phenom":
        # detail files are {job_id}.html for each in-scope index record (mode_detail's scheme).
        return {f"{mod.job_id(j)}.html" for j in mod.load_records(t) if mod.in_scope(j, t) and mod.job_id(j)}, ".html"
    if platform == "ultipro":
        # index.jsonl is ALREADY the in-scope set; detail files are {opportunityId}.json.
        return {f"{mod.opp_id(o)}.json" for o in mod.load_index(t) if mod.opp_id(o)}, ".json"
    if platform == "appcast":
        # index.jsonl is ALREADY the in-scope set; detail files are {jobid}.json.
        return {f"{c['jobid']}.json" for c in mod.load_index(t) if c.get("jobid")}, ".json"
    if platform == "avature":
        # index.jsonl is ALREADY the in-scope set (server-side state facet); detail = {id}.json.
        return {f"{c['id']}.json" for c in mod.load_index(t) if c.get("id")}, ".json"
    return None, None


def reconcile_detail(platform, tenant):
    """Drop detail files whose URL/id isn't in today's live index. Guarded and reversible:
    dead files move to raw/<platform>/<tenant>/_purged/ (cleared each run), never deleted."""
    detdir = os.path.join(RAW, platform, tenant, "detail")
    if not os.path.isdir(detdir):
        return
    try:
        live, ext = _live_detail_names(platform, tenant)
    except Exception as e:
        print(f"    reconcile {tenant}: SKIP - could not compute live set ({type(e).__name__}: {e}); nothing purged")
        return
    if live is None:
        return
    ondisk = [f for f in os.listdir(detdir) if f.endswith(ext)]
    dead = [f for f in ondisk if f not in live]
    kept = len(ondisk) - len(dead)
    if not dead:
        print(f"    reconcile {tenant}: {len(ondisk)} detail files, all live")
        return
    # Guard: the live set must reproduce the cache. If it doesn't (scheme drift), kept
    # collapses and we must NOT purge - leave the zombies, flag it, let the run continue.
    if not (len(live) > 0 and kept >= 0.80 * len(live)):
        print(f"    reconcile {tenant}: SKIP - live set ({len(live)}) did not reproduce cache "
              f"(kept {kept}/{len(ondisk)}); {len(dead)} left in place")
        return
    pdir = os.path.join(RAW, platform, tenant, "_purged")
    if os.path.isdir(pdir):
        shutil.rmtree(pdir)
    os.makedirs(pdir, exist_ok=True)
    for f in dead:
        shutil.move(os.path.join(detdir, f), os.path.join(pdir, f))
    print(f"    reconcile {tenant}: purged {len(dead)} dead (URL gone from board), kept {kept} live")


# ---------------------------------------------------------------------------
# enumerate-completeness guard (root fix for false expiry)
# ---------------------------------------------------------------------------
# The expiry path trusts each pull's enumerate as a COMPLETE list of what is live. It is not:
# offset pagination over a date-desc sort while new jobs post shifts records across page seams,
# so a live job is skipped even though pagination "finished" (proven: Kroger req 203617 live on
# the site, absent from that day's enumerate, false-expired). Two layers, from the adapters'
# own run_log (no adapter changes needed):
#   (a) source-total assertion — if the adapter logs a `total`, `captured` must reach it. Even a
#       few short (kroger 490/494) false-expires the missed jobs, so this is strict.
#   (b) delta band — no source total (radancy/compass/jibe): in_scope must stay within the band
#       of the trailing runs. Loose to start (15%); tighten from data, never loosen under load.
# A tenant that fails HOLDS its whole source_id (fail-closed, option A: records key by source_id,
# so a shared platform can't hold one tenant). supabase_sink then skips held sources entirely.
ENUM_BAND = 0.85   # layer (b): in_scope must be >= 85% of the trailing reference


def _latest_index_events(platform, tenant, n=6):
    path = os.path.join(RAW, platform, tenant, "run_log.jsonl")
    evs = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event") == "index":
                    evs.append(e)
    except OSError:
        return []
    return evs[-n:]


def enumerate_complete(platform, tenant, slack=0):
    """(ok, reason). Layer (a) source-total if the adapter logs one; else layer (b) delta band.
    No run_log or no prior reference -> ok (nothing to compare against, e.g. first run).

    `slack` is a per-tenant allowance for a MEASURED, CONSTANT source overcount where the API's
    advertised total is reliably N higher than what pagination yields (Oracle ORC's
    TotalJobsCount does this for Kroger: gap == exactly 4 on every run, total floating 467..488,
    the crawl ending on an empty page = source exhausted). Calibrated to the observed gap and no
    larger: a genuine page-seam skip lowers `captured` further, pushing the gap past `slack`, so
    real truncation is still caught. slack=0 (the default) preserves the strict check everywhere
    else."""
    evs = _latest_index_events(platform, tenant)
    if not evs:
        return True, "no run_log (uncheckable)"
    cur = evs[-1]
    total, captured = cur.get("total"), cur.get("captured")
    if total is not None and captured is not None:                 # layer (a): authoritative
        if captured < total - slack:
            return False, f"truncated enumerate: captured {captured} < source total {total}" + (f" - slack {slack}" if slack else "")
        return True, f"complete: captured {captured} >= total {total}" + (f" - slack {slack}" if slack else "")
    metric = "in_scope" if cur.get("in_scope") is not None else "captured"   # layer (b)
    curv = cur.get(metric)
    prior = [e.get(metric) for e in evs[:-1] if e.get(metric) is not None]
    if curv is None or not prior:
        return True, "no prior reference (uncheckable)"
    ref = max(prior)
    if curv < ENUM_BAND * ref:
        return False, f"short enumerate: {metric} {curv} < {int(ENUM_BAND * 100)}% of trailing {ref}"
    return True, f"within band: {metric} {curv} vs trailing {ref}"


def run_guard(units, results, stamp):
    """Per-tenant completeness -> per-source_id status {ok|skipped|failed}, fail-closed. 'failed'
    (adapter mode exited non-zero) outranks a completeness 'skipped'. Writes out/guard_status.json
    for supabase_sink (which holds any non-ok source at its prior state). Returns the status dict."""
    src = {}          # source_id -> ok|skipped|failed
    reasons = {}
    tcfg = load_json(os.path.join(CONFIG_DIR, "tenants.json"))   # per-tenant enumerate_total_slack
    for u in units:
        plat, tenant = u["platform"], u["tenant"]
        if results[tenant]["failed_mode"]:
            src[plat] = "failed"
            reasons.setdefault(plat, []).append(f"{tenant}: adapter mode '{results[tenant]['failed_mode']}' exited non-zero")
            continue
        slack = ((tcfg.get(plat) or {}).get(tenant) or {}).get("enumerate_total_slack", 0)
        ok, why = enumerate_complete(plat, tenant, slack=slack)
        if not ok:
            if src.get(plat) != "failed":
                src[plat] = "skipped"
            reasons.setdefault(plat, []).append(f"{tenant}: {why}")
        else:
            src.setdefault(plat, "ok")
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "guard_status.json"), "w", encoding="utf-8") as fh:
            json.dump({"stamp": stamp, "sources": src, "reasons": reasons}, fh, indent=2)
    except OSError as e:
        print(f"    guard_status write skipped: {e}")
    skipped = sorted(s for s, v in src.items() if v == "skipped")
    failed = sorted(s for s, v in src.items() if v == "failed")
    if skipped or failed:
        print("\n--- enumerate guard ---")
        for s in failed:
            print(f"    FAILED (held, source broke): {s} — {'; '.join(reasons.get(s, []))}")
        for s in skipped:
            print(f"    SKIPPED (held, enumerate short — pipeline working): {s} — {'; '.join(reasons.get(s, []))}")
    else:
        print("\n--- enumerate guard: all sources complete ---")
    return src


def preflight(publish):
    """Green-path "prep" check run before any pull: verify nothing structural blocks a run from
    reaching completion (and, when --publish, from baking + deploying). Returns a list of
    (key, message, is_critical). Cheap, fast, read-only. A critical issue aborts the run early
    with a clear RECORDED reason, instead of failing deep in the pipeline where nothing is logged."""
    issues = []

    # 1) config parses — a broken pull.json/tenants.json would otherwise sys.exit inside resolve_units.
    for name in ("pull.json", "tenants.json"):
        try:
            load_json(os.path.join(CONFIG_DIR, name))
        except Exception as e:
            issues.append((f"config/{name}", f"unreadable: {type(e).__name__}: {e}", True))

    # 2) Supabase REST reachable — read-only connectivity ping. ANY HTTP response (even 4xx from
    #    RLS/permissions on the probe path) proves the server + DNS + network are up, which is all
    #    this check cares about; only a real connection failure (DNS/timeout/refused) is critical.
    try:
        req = urllib.request.Request(
            SUPABASE_URL + "/rest/v1/", headers={"apikey": SUPABASE_PUBLISHABLE_KEY}, method="GET")
        with urllib.request.urlopen(req, timeout=12) as r:
            r.read(1)
    except urllib.error.HTTPError:
        pass                                    # got an HTTP status back -> reachable
    except Exception as e:
        issues.append(("supabase-net", f"Supabase REST unreachable ({type(e).__name__})", True))

    # 3) publish toolchain + secret — only relevant when this run will publish.
    if publish:
        if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            issues.append(("supabase-key", "SUPABASE_SERVICE_ROLE_KEY not set (push would fail)", True))
        for tool in ("node", "vercel"):
            if not shutil.which(tool):
                issues.append((tool, f"'{tool}' not on PATH (bake/deploy would fail)", True))
        if not os.path.exists(CHROME):
            issues.append(("chrome", f"Chrome not found at {CHROME} (bake would fail)", True))

    # 4) disk headroom — a full bake writes ~1k HTML files. Warn, don't abort.
    try:
        free_mb = shutil.disk_usage(ROOT).free // (1024 * 1024)
        if free_mb < 1024:
            issues.append(("disk", f"low disk: {free_mb} MB free on the project drive", False))
    except Exception:
        pass

    return issues


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

    # ---- main run path. Stamp FIRST (so any crash below still records under this stamp), then a
    #      green-path preflight, then resolve + run. ----
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    global _CURRENT_STAMP
    _CURRENT_STAMP = stamp

    print("=" * 78)
    print(f"RECURRING PULL   {stamp}   {'DRY-RUN' if a.dry_run else ('PUBLISH' if a.publish else 'no-publish')}")
    print("=" * 78)

    # preflight ("prep"): abort fast WITH a recorded reason on a structural problem, rather than
    # crashing deep in the run where nothing reaches the dashboard.
    print("\n--- preflight: green-path check ---")
    pf = preflight(a.publish)
    for key, msg, crit in pf:
        print(f"    {'FAIL' if crit else 'warn'}  {key}: {msg}")
    if not pf:
        print("    ok  all checks passed")
    critical = [x for x in pf if x[2]]
    if critical:
        reason = "preflight blocked the run - " + "; ".join(f"{k}: {m}" for k, m, _ in critical)
        print(f"\n!! {reason}\n   Nothing pulled. Recording the failure to the dashboard.")
        try:
            runlog.emit_failure(stamp=stamp, reason=reason)
        except Exception as e:
            print(f"(dashboard record failed - non-fatal: {type(e).__name__}: {e})")
        return 2

    units = resolve_units(a.tenant)
    baseline = load_baseline()["tenants"]
    print(f"tenants: {', '.join(u['tenant'] for u in units)}")

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
        if not a.dry_run:
            clean_enumerate(platform, tenant)   # fresh enumerate so in-scope == this pull's board
        for mode in u["modes"]:
            if mode not in modes:
                mres[mode] = "skip"
                continue
            if mode == "normalize":
                reconcile_detail(platform, tenant)   # drop detail whose URL left the board
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

    # ---- enumerate-completeness guard: which sources are complete enough to push. A short or
    #      broken enumerate HOLDS its source_id at prior state (supabase_sink reads guard_status),
    #      so a partial pull can no longer false-expire the board. Runs before the push.
    run_guard(units, results, stamp)

    # ---- enrich: persist verdicts + category onto normalized.jsonl (THE MISSING LAYER) ----
    # Adapters leave experience_condition/evidence_clauses/credentials/category empty by
    # construction; normalize/enrich.py fills them on disk. report.py recomputes the verdict
    # fields in memory but NOT category (it reads category off the enriched record), so without
    # this step category lands empty and every record reads as a category regression. Runs over
    # all tenants on disk (idempotent, additive), same as report.py's glob.
    print("\n--- enrich: normalize/enrich.py (persist verdicts + category) ---")
    rc, _ = run([sys.executable, "-m", "normalize.enrich"])
    if rc != 0:
        print("!! enrich failed - cannot consolidate correctly. Run is PARTIAL.")
        return _finish(stamp, units, results, prior_counts, baseline, None, None, partial=True,
                       publish=a.publish, complete=False, movement=["enrich (normalize.enrich) exited non-zero"])

    # ---- consolidate: report.py -> out/applicable.jsonl (BEFORE audit + push) ----
    # Snapshot the prior applicable set in memory first, then let report.py overwrite it.
    prior_applicable = read_applicable(APPLICABLE)
    print("\n--- consolidate: analyze/report.py (all tenants on disk) ---")
    rc, _ = run([sys.executable, "-m", "analyze.report"])
    if rc != 0:
        print("!! report.py failed - cannot consolidate. Run is PARTIAL.")
        return _finish(stamp, units, results, prior_counts, baseline, None, None, partial=True,
                       publish=a.publish, complete=False, movement=["report (analyze.report) exited non-zero"])

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
    # Per-tenant "seasonal/dormant" exemption. A tenant that config-flags allow_zero_records
    # (config/tenants.json) is a verified seasonal board that is legitimately empty out of season
    # (Spirit Christmas: 0 in WA until ~Oct-Dec). Its zero does NOT halt the whole publish - it
    # still rides the pull, so its jobs surface (as "entered") the moment the season opens. This is
    # the loud activation the operator asked for in place of a background monitor. Config-driven,
    # no tenant branching; every non-flagged tenant keeps the hard zero-records halt.
    tcfg_halt = load_json(os.path.join(CONFIG_DIR, "tenants.json"))
    def _allow_zero(u):
        return bool(((tcfg_halt.get(u["platform"]) or {}).get(u["tenant"]) or {}).get("allow_zero_records"))
    for u in units:
        t = u["tenant"]
        row = table.get(t)
        base = baseline.get(t)
        if row is None:
            if not _allow_zero(u):
                halts.append(f"{t}: no rows in consolidated report (zero records?)")
            continue
        if _allow_zero(u) and row["records"] > 0:
            print(f"    *** SEASONAL TENANT ACTIVATED: {t} now has {row['records']} records "
                  f"({row.get('applicable', '?')} applicable) — a dormant board opened. "
                  f"Inspect and set a config/baseline.json row. ***")
        if row["records"] == 0:
            if not _allow_zero(u):
                halts.append(f"{t}: zero records")
        elif base and row["records"] < MIN_RECORD_FRACTION * base["records"]:
            halts.append(f"{t}: {row['records']} records < 50% of baseline {base['records']}")
        if base and abs(row["density"] - base["density"]) > MAX_DENSITY_MOVE:
            halts.append(f"{t}: density {row['density']:.1f}% moved >15pts from baseline {base['density']:.1f}%")
    if mv_halt:
        halts.append(f"movement {mv_pct:.2f}% of set / worst employer {worst_emp} {worst_pct:.2f}% over threshold")

    complete = not halts
    return _finish(stamp, units, results, prior_counts, baseline, table, (mv_pct, worst_emp, worst_pct, mv_path),
                   partial=not complete, publish=a.publish, complete=complete, movement=halts)


def _finish(stamp, units, results, prior_counts, baseline, table, mv, partial, publish, complete, movement):
    # ---- output table (step 9) ----
    print("\n" + "=" * 78)
    print("RUN TABLE")
    print("=" * 78)
    hdr = f"{'tenant':<16}{'platform':<12}{'modes':<22}{'recs':>6}{'delta':>7}{'appl':>6}{'dens':>7}{'d-dens':>8}  flag"
    print(hdr)
    print("-" * len(hdr))
    total_appl = 0
    base_total_appl = 0
    tenant_rows = []          # same data as the printed table, kept for the run record
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
        tenant_rows.append({"tenant": t, "platform": plat, "modes": modestr, "records": recs,
                            "d_records": d_recs, "applicable": appl, "density": round(dens, 1),
                            "d_density": round(d_dens, 1), "flag": flag})

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
    pub = {"published": False, "publish_status": None, "deploy_url": None,
           "bake_job_pages": None, "bake_listing_views": None,
           "bake_jobs_fetched": None, "bake_jobs_total": None, "bake_complete": None}
    rc = 0 if complete else 1
    if complete and publish:
        rc, pub = _publish()
    elif publish and not complete:
        print("\n--publish requested but run is PARTIAL - publish withheld.")
        pub["publish_status"] = "withheld (PARTIAL)"
    elif not publish:
        print("\n(no --publish: stopped at the table.)")
        pub["publish_status"] = "not requested"

    # ---- durable run record + local dashboard (BOTH: out/runs/ + Supabase mirror) ----
    # Fully guarded: a record/dashboard/mirror fault must never change the run's outcome.
    try:
        if pub.get("bake_complete") is False:
            severity = "critical"          # fetch truncated -> partial site; loud regardless of the rest
        elif pub["published"]:
            severity = "good"
        elif pub["publish_status"] and "FAILED" in pub["publish_status"]:
            severity = "critical"
        elif complete:
            severity = "good"
        else:
            severity = "warning"
        live, expired = _lifecycle_counts()
        record = {
            "stamp": stamp, "ran_at": runlog.iso_from_stamp(stamp),
            "status": status, "severity": severity,
            "published": pub["published"], "publish_status": pub["publish_status"],
            "deploy_url": pub["deploy_url"],
            "total_applicable": total_appl, "baseline_applicable": base_total_appl,
            "applicable_delta": total_appl - base_total_appl,
            "movement_pct": round(mv[0], 2) if mv else None,
            "worst_employer": mv[1] if mv else None,
            "worst_employer_pct": round(mv[2], 2) if mv else None,
            "bake_job_pages": pub["bake_job_pages"], "bake_listing_views": pub["bake_listing_views"],
            "bake_jobs_fetched": pub.get("bake_jobs_fetched"), "bake_jobs_total": pub.get("bake_jobs_total"),
            "bake_complete": pub.get("bake_complete"),
            "live_jobs": live, "expired_jobs": expired,
            "git_head": _git_head(), "halts": list(movement or []), "tenants": tenant_rows,
        }
        dash, note = runlog.emit(record)
        print(f"\nrun record: {dash}   (supabase: {note})")
    except Exception as e:
        print(f"\n(run record/dashboard skipped - non-fatal: {type(e).__name__}: {e})")
    return rc


def _publish():
    """In order, halting immediately on any non-zero exit. report.py already ran at
    consolidation (it produces the applicable.jsonl the push consumes); site_data.py/jobs.js
    is intentionally omitted (dead - Supabase is the source of truth). A halt here leaves the
    prior production build serving.

    Returns (rc, info) where info feeds the run record: published bool, publish_status,
    deploy_url, and the bake summary (job pages / listing views parsed from build.mjs's line)."""
    print("\n" + "=" * 78)
    print("PUBLISH (COMPLETE)")
    print("=" * 78)
    info = {"published": False, "publish_status": None, "deploy_url": None,
            "bake_job_pages": None, "bake_listing_views": None,
            "bake_jobs_fetched": None, "bake_jobs_total": None, "bake_complete": None}

    # capture=True on the node stages so their (stderr) output flows through the tee and
    # a non-zero exit is seen. A silent bake failure and a good bake used to log identically.
    steps = [
        ("push to Supabase", [sys.executable, "-m", "analyze.supabase_sink"], ROOT, False),
        # The ONE recency computation -> out/freshness.json, which the bake merges onto each
        # record as is_new (the per-card New badge). Must run BEFORE the bake; reads the local
        # applicable.jsonl + config, no network.
        ("freshness (new badges)", [sys.executable, "-m", "analyze.freshness"], ROOT, False),
        ("bake (prerender build)", ["node", "build.mjs"], PRERENDER, True),
        ("retire", ["node", "retire.mjs"], PRERENDER, True),
    ]
    for name, cmd, cwd, cap in steps:
        print(f"\n--- {name} ---")
        rc, out = run(cmd, cwd=cwd, capture=cap)
        if name.startswith("bake"):
            m = re.search(r"BAKE COMPLETE:\s*(\d+)\s+job pages,\s*(\d+)\s+listing views", out or "")
            if m:
                info["bake_job_pages"], info["bake_listing_views"] = int(m.group(1)), int(m.group(2))
            # Coverage signal: rows fetched vs the DB's authoritative count. Parsed even on a
            # BAKE FAILED exit (the line is emitted regardless), so the dashboard shows WHY.
            c = re.search(r"BAKE COVERAGE:\s*jobs\s*(\d+)/(\d+|\?)\s+list\s*(\d+)/(\d+|\?)\s+complete=(true|false)", out or "")
            if c:
                info["bake_jobs_fetched"] = int(c.group(1))
                info["bake_jobs_total"] = None if c.group(2) == "?" else int(c.group(2))
                info["bake_complete"] = (c.group(5) == "true")
        if rc != 0:
            print(f"\n!! {name} exited {rc} - halting publish. Prior production build keeps serving.")
            if name.startswith("bake"):
                info["publish_status"] = f"BAKE FAILED (exit {rc})"
                print(f"STATUS: BAKE FAILED (exit {rc})")
            else:
                info["publish_status"] = f"PUBLISH FAILED at {name} (exit {rc})"
                print(f"STATUS: PUBLISH FAILED at {name} (exit {rc})")
            return 1, info

    print("\n--- deploy (vercel --prod) ---")
    rc, out = run(["vercel", "deploy", "--prod", "--yes"], cwd=DEPLOY_DIR, capture=True)
    if rc != 0:
        print("\n!! deploy exited non-zero - halting. Prior production build keeps serving.")
        info["publish_status"] = f"PUBLISH FAILED at deploy (exit {rc})"
        print(f"STATUS: PUBLISH FAILED at deploy (exit {rc})")
        return 1, info
    url = ""
    for m in re.finditer(r"https://\S+\.vercel\.app", out or ""):
        url = m.group(0)
    info["published"], info["deploy_url"], info["publish_status"] = True, url, "PUBLISH COMPLETE"
    print(f"\ndeploy: {url or '(url not captured - check vercel output)'}")
    print("STATUS: PUBLISH COMPLETE")

    # Notify Google of new/retired pages — ONLY after a successful publish, and strictly
    # best-effort (never changes the publish result). new -> URL_UPDATED, retired -> URL_DELETED.
    print("\n--- indexing: notify Google (new -> URL_UPDATED, retired -> URL_DELETED) ---")
    try:
        from analyze import indexing
        info["indexing"] = indexing.submit_after_publish()
    except Exception as e:
        print(f"[indexing] skipped (non-fatal): {type(e).__name__}: {e}")

    return 0, info


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              text=True, capture_output=True).stdout.strip() or None
    except Exception:
        return None


def _lifecycle_counts():
    """live/expired job counts from the last bake's manifest (latest-only; may lag a PARTIAL)."""
    path = os.path.join(DEPLOY_DIR, "_lifecycle.json")
    try:
        d = load_json(path)
        return len(d.get("live", [])), len(d.get("expired", []))
    except Exception:
        return None, None


if __name__ == "__main__":
    # Top-level crash guard: ANY unhandled exception below the stamp (e.g. an adapter step that
    # raises mid-loop) still records a FAILED run to the dashboard, so a mid-run crash is NEVER
    # invisible. Normal/partial completions emit their own richer record via _finish().
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise                                   # argparse / explicit sys.exit — already intentional
    except BaseException as e:
        tb = traceback.format_exc()
        print(tb, flush=True)
        last = tb.strip().splitlines()[-1] if tb.strip() else None
        try:
            runlog.emit_failure(stamp=_CURRENT_STAMP,
                                reason=f"run_pull crashed: {type(e).__name__}: {e}",
                                detail=last)
        except Exception:
            pass
        sys.exit(1)
