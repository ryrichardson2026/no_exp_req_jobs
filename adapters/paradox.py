"""
Paradox (Olivia) careers-board adapter - No-Experience Job Network.

SCOPE: fetch and write raw job JSON to disk. Nothing else. No experience logic
(that is normalize.enrich with this tenant's forked openers).

PLATFORM NAMING - read before adding a tenant. Named for the READ SURFACE. careers.{brand}.com
is a Paradox/Olivia widget (cdn.olivia.paradox.ai) backed by a JSON jobs API; the apply flow
is Paradox conversational ("Olivia"). Confirmed 2026-09-17 by Chrome network trace + cold Python.
SERVES a diverse portfolio on the SAME shape (per-brand careers host): Shake Shack, Chipotle,
Inspire Brands (Arby's/BWW/Sonic/Dunkin/Jimmy John's), Panda Express.

FETCH SHAPE (reverse-engineered + verified in Chrome + COLD from Python 2026-09-17):
  data   POST {careers_host}/api/get-jobs?radius=15&page_number=N&enable_kilometers=false
         body {} ; needs a primed session (GET {careers_host}/jobs for cookies) + Referer +
         Origin headers (cold 403s without them). Returns {jobs:[...], facets, totalJob}, 10/page.
         The job DESCRIPTION is INLINE in the list record - NO separate detail fetch (single-pass).
  scope  CLIENT-SIDE on job.locations[].stateAbbr in markets (+ countryAbbr == 'US'). A field
         read, not the site's geo-radius (radius= param) which bleeds across state/national lines.
         Page to totalJob; totalJob is a DIAGNOSTIC cross-check, not the stop condition.

INVARIANTS honored: vendor total is a DIAGNOSTIC (completeness = page-to-empty); a transient
failure truncates + aborts WITHOUT writing a partial set as complete; config is data (careers
host + market abbreviations live in config, no branching on tenant identity).

Usage:
  python -m adapters.paradox --tenant shake_shack --probe
  python -m adapters.paradox --tenant shake_shack --inspect
  python -m adapters.paradox --tenant shake_shack --index
  python -m adapters.paradox --tenant shake_shack --report
  python -m adapters.paradox --tenant shake_shack --normalize
"""
import argparse
import html as htmllib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "paradox")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except Exception:  # pragma: no cover
    import requests as http
    _IMPERSONATE = {}

PLATFORM = "paradox"
DELAY_SECONDS = 0.4
PAGE_SIZE = 10           # vendor-fixed page size
MAX_PAGES = 400          # safety stop, not a business rule
TIMEOUT = 30


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        known = ", ".join(k for k in tenants if not k.startswith("_"))
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH} [{PLATFORM}]. Known: {known}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {"base": base,
            "index": os.path.join(base, "records.jsonl"),   # in-scope jobs w/ description
            "run": os.path.join(base, "run_log.jsonl")}


def log(tenant, event, **fields):
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------
# fetch - primed session (cookies) + Referer/Origin (cold 403s without them)
# --------------------------------------------------------------------------

_SESSION = None


def _session(t):
    global _SESSION
    if _SESSION is None:
        _SESSION = http.Session(**_IMPERSONATE)
        try:
            _SESSION.get(t["careers_host"].rstrip("/") + "/jobs", timeout=TIMEOUT)
        except Exception:
            pass
    return _SESSION


def _headers(t):
    host = t["careers_host"].rstrip("/")
    return {"Referer": host + "/jobs", "Origin": host,
            "Content-Type": "application/json", "Accept": "application/json"}


def fetch_page(t, n):
    host = t["careers_host"].rstrip("/")
    path = t.get("api_path", "/api/get-jobs")
    url = f"{host}{path}?radius=15&page_number={n}&enable_kilometers=false"
    return _session(t).post(url, json={}, timeout=TIMEOUT, headers=_headers(t))


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _posted_date(job):
    """customFields is a list of {name,value} (or occasionally a dict); dig out a posted date."""
    cf = job.get("customFields")
    if isinstance(cf, dict):
        return cf.get("postedDate") or cf.get("posted_date")
    if isinstance(cf, list):
        for f in cf:
            if isinstance(f, dict) and re.search(r"post", str(f.get("name") or f.get("key") or ""), re.I):
                return f.get("value")
    return job.get("postedDate") or job.get("datePosted")


def _markets(t):
    return {m.upper() for m in (t.get("markets") or [])}


def in_scope_location(job, t):
    """Return the first location whose stateAbbr is a target market (US only), else None."""
    want = _markets(t)
    for loc in job.get("locations") or []:
        if (loc.get("countryAbbr") or "US").upper() != "US":
            continue
        st = (loc.get("stateAbbr") or "").upper()
        if not want or st in want:
            return loc
    return None


def strip_html(s):
    if not s:
        return None
    txt = htmllib.unescape(re.sub(r"<[^>]+>", " ", s))
    return " ".join(txt.split()) or None


def total_jobs(payload):
    return payload.get("totalJob") if isinstance(payload, dict) else None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def mode_probe(t):
    print(f"tenant : {t['key']}  ({t.get('label','')})")
    print(f"host   : {t['careers_host']}   markets : {sorted(_markets(t))}")
    r = fetch_page(t, 1)
    print(f"\nstatus : {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300]); return 1
    j = r.json()
    jobs = j.get("jobs", [])
    print(f"page size (measured) : {len(jobs)}   totalJob (DIAGNOSTIC) : {total_jobs(j)}")
    scoped = [x for x in jobs if in_scope_location(x, t)]
    print(f"in scope on page 1   : {len(scoped)}/{len(jobs)}")
    if jobs:
        x = jobs[0]
        loc = (x.get("locations") or [{}])[0]
        print(f"\nfirst record: {x.get('requisitionID')}  {(x.get('title') or '')[:60]}")
        print(f"  loc={loc.get('city')},{loc.get('stateAbbr')}  desc_chars={len(x.get('description') or '')}")
    print("\nProbe OK.")
    log(t, "probe", status=r.status_code, total=total_jobs(j))
    return 0


def _walk(t):
    """Page to an empty page; keep in-scope jobs, slimmed to the fields we map."""
    kept, seen = [], set()
    total = None
    for page in range(1, MAX_PAGES + 1):
        r = fetch_paged(lambda: fetch_page(t, page), label=f"page {page}: ")
        j = r.json()
        total = total_jobs(j) or total
        jobs = j.get("jobs", [])
        if not jobs:
            break
        for x in jobs:
            uid = x.get("uniqueID") or x.get("requisitionID")
            if uid in seen:
                continue
            seen.add(uid)
            loc = in_scope_location(x, t)
            if loc:
                kept.append({"uniqueID": uid, "requisitionID": x.get("requisitionID"),
                             "title": x.get("title"), "description": x.get("description"),
                             "employmentType": x.get("employmentType"),
                             "originalURL": x.get("originalURL"), "companyName": x.get("companyName"),
                             "location": loc,
                             "postedAt": _posted_date(x)})
        if page % 10 == 0:
            print(f"  page {page}: seen {len(seen)}, in-scope {len(kept)} (total {total})")
        if total and len(seen) >= total:
            break
        time.sleep(DELAY_SECONDS)
    return kept, total


def mode_index(t):
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    try:
        kept, total = _walk(t)
    except Truncated as e:
        print(f"\n!! ABORT index: {e}. Partial capture DISCARDED (prior data kept).")
        log(t, "index_abort", detail=str(e))
        return 1
    with open(p["index"], "w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nindex complete: board {total}, in-scope {len(kept)} -> {p['index']}")
    log(t, "index", board_total=total, in_scope=len(kept))
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.exists(p["index"]):
        return []
    with open(p["index"], "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def mode_inspect(t):
    recs = load_index(t) or _walk(t)[0]
    if not recs:
        print("no in-scope records to inspect"); return 1
    r = recs[0]
    print(f"record : {r.get('requisitionID')}  {r.get('title')}")
    desc = htmllib.unescape(r.get("description") or "")
    heads = re.findall(r"(?is)<(?:b|strong|h[1-6])[^>]*>\s*([A-Z][^<]{2,50}?):?\s*</", desc)
    reqish = [h.strip() for h in heads
              if re.search(r"qualif|requir|experien|skill|educ|essential|who|looking", h, re.I)]
    print(f"requirement-ish headings (derive openers from these): {reqish[:12]}")
    print(f"\ntext head: {strip_html(desc)[:220]}")
    return 0


def _emp_type(v):
    if not v:
        return None
    key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
    return {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "CONTRACTOR": "Contract",
            "TEMPORARY": "Temporary", "INTERN": "Internship"}.get(key, str(v).strip().title())


def map_record(rec, t, retrieved_at):
    r = model.new_record()
    warnings = []
    loc = rec.get("location") or {}
    r["source_id"] = PLATFORM
    r["source_job_id"] = rec.get("uniqueID") or rec.get("requisitionID")
    r["company_name"] = t.get("company_name") or rec.get("companyName") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = rec.get("title")

    r["description_html"] = rec.get("description")
    r["description_text"] = strip_html(rec.get("description"))
    r["qualifications"] = []
    r["qualifications_html"] = None

    r["city"] = loc.get("city")
    r["state"] = (loc.get("stateAbbr") or "").upper() or None
    r["location_raw"] = loc.get("locationText") or loc.get("cityStateAbbr") \
        or ", ".join(x for x in [loc.get("city"), (loc.get("stateAbbr") or "")] if x) or None
    r["lat"] = loc.get("latitude")
    r["lng"] = loc.get("longitude")

    r["employment_type"] = _emp_type(rec.get("employmentType"))
    r["shift_raw"] = None
    r["posted_at"] = (rec.get("postedAt") or "")[:10] or None
    r["freshness_state"] = "UNKNOWN"

    r["apply_url"] = rec.get("originalURL")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = None
    r["source_function"] = None
    r["source_url"] = rec.get("originalURL")
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    if not r["state"]:
        warnings.append(f"{r['source_job_id']}: no state resolved")
    return r, warnings


def mode_report(t):
    from collections import Counter
    recs = load_index(t)
    by_state = Counter((r.get("location") or {}).get("stateAbbr") for r in recs)
    with_desc = sum(1 for r in recs if (r.get("description") or "").strip())
    print(f"tenant        : {t['key']}")
    print(f"markets       : {sorted(_markets(t))}")
    print(f"in-scope      : {len(recs)}   by state: {dict(by_state)}")
    print(f"with desc     : {with_desc}/{len(recs)}")
    return 0


def mode_normalize(t):
    recs = load_index(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = paths(t)
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(
        os.path.getmtime(p["index"]))) if os.path.exists(p["index"]) else now

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for rec in recs:
        r, w = map_record(rec, t, retrieved)
        model.apply_seen_state(r, seen_state, now)
        r["is_new"] = True if known_before == 0 else r["first_seen"] == now
        probs = model.validate(r)
        if probs:
            invalid.append((r.get("source_job_id"), probs))
        mapped.append(r)
        warns.extend(w)

    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(seen_state, fh, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in mapped:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{len(recs)} records -> {len(mapped)} normalized -> {out_path}")
    print("\nFILL RATE\n")
    for f, n, pct in model.fill_report(mapped):
        print(f"  {n:>5}  {pct:>5.1f}%  {f}")
    print(f"\nvalidation failures: {len(invalid)}")
    if warns:
        print(f"mapping warnings: {len(warns)} (e.g. {warns[0]})")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Paradox (Olivia) careers-board adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify API + per-page scope + totalJob")
    g.add_argument("--inspect", action="store_true", help="one in-scope record: description + headings")
    g.add_argument("--index", action="store_true", help="page the board, keep in-scope, write records")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()
    t = load_tenant(a.tenant)
    return {"probe": mode_probe, "inspect": mode_inspect, "index": mode_index,
            "report": mode_report, "normalize": mode_normalize}[
        next(k for k in ("probe", "inspect", "index", "report", "normalize")
             if getattr(a, k))](t)


if __name__ == "__main__":
    sys.exit(main())
