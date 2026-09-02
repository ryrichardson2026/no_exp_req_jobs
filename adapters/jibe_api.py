"""
Jibe career-site JSON API adapter - No-Experience Job Network.

SCOPE: fetch and write raw JSON to disk. Nothing else.
No field mapping, no dedupe, no normalized model, no experience logic.

PLATFORM NAMING - read this before adding a tenant.
This is named for the READ SURFACE, not the ATS. Dollar General's payload
carries "ats_code": "icims" on every record - the ATS is a FIELD IN THE DATA,
not the thing being fetched. What is being fetched is /api/jobs on a Jibe
career site (domain={client}.jibeapply.com, client_code in the payload).

Three employers are now on iCIMS with three unrelated read surfaces:
  Allied Universal  -> TalentBrew markup, server-rendered HTML, &p=N
  Dollar General    -> Jibe, JSON API, ?page=N            <- this adapter
  classic iCIMS     -> unbuilt, unverified
An "icims" adapter covering all three would require branching on tenant
identity, which breaks config-is-data. They do not share a fetch path.

GENERALISATION IS UNPROVEN. The URL shape is vendor-generic, so a second Jibe
employer SHOULD be one config entry. Oracle looked uniform too until Kroger's
flex-field prompts shared zero overlap with Providence's. One confirmed tenant.
Run --probe on any new tenant before assuming it fits.

Usage:
  python3 -m adapters.jibe_api --tenant dollar_general --probe
  python3 -m adapters.jibe_api --tenant dollar_general --inspect
  python3 -m adapters.jibe_api --tenant dollar_general --index
  python3 -m adapters.jibe_api --tenant dollar_general --report
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import urlencode

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:
    sys.exit("curl-cffi is required:  pip install curl-cffi")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "jibe_api")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "jibe_api"
DELAY_SECONDS = 1.0
MAX_PAGES = 500          # safety stop, not a business rule
TIMEOUT = 45


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH}. Known: {', '.join(tenants)}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {
        "base": base,
        "pages": os.path.join(base, "pages"),
        "run": os.path.join(base, "run_log.jsonl"),
    }


def log(tenant, event, **fields):
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def fetch_page(tenant, page):
    params = dict(tenant["query"])
    params[tenant.get("page_param", "page")] = page
    url = f"{tenant['api_url']}?{urlencode(params)}"
    return http.get(url, headers={"accept": "application/json"},
                    timeout=TIMEOUT, **_IMPERSONATE)


def extract_jobs(payload):
    """Records arrive wrapped: {"jobs": [{"data": {...}}, ...]}.

    Unwrap one level so the rest of the pipeline sees job objects, but the
    RAW page is written untouched - a parser change never costs a re-fetch.
    """
    out = []
    for item in payload.get("jobs", []) or []:
        out.append(item.get("data", item))
    return out


def job_id(job):
    for k in ("req_id", "slug", "id"):
        if job.get(k):
            return str(job[k])
    return None


def in_scope(job, tenant):
    """Location filter on a NAMED FIELD, not a string token.

    This tenant returns a clean 'state' field ('Washington'). Every prior
    tenant needed an address token and two of them were wrong - the six-state
    Washington-city false positive cannot occur here. If a future Jibe tenant
    lacks the field, omit 'field' and the whole-record blob is matched instead.
    """
    f = tenant.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True
    field = f.get("field")
    hay = str(job.get(field, "")) if field else json.dumps(job)
    return any(t in hay for t in terms)


def mode_probe(tenant):
    """Verify the endpoint, page size, pagination and scope rate on this tenant."""
    print(f"tenant : {tenant['key']}  ({tenant.get('label','')})")
    print(f"api    : {tenant['api_url']}")
    print()

    try:
        r = fetch_page(tenant, tenant.get("first_page", 1))
    except Exception as e:
        print(f"FAIL  request raised: {type(e).__name__}: {e}")
        return 1

    print(f"status : {r.status_code}   bytes: {len(r.content)}")
    if r.status_code != 200:
        print(r.text[:400])
        return 1

    try:
        payload = r.json()
    except Exception:
        print("FAIL  200 but body is not JSON:")
        print(r.text[:400])
        return 1

    jobs = extract_jobs(payload)
    print(f"page size (measured) : {len(jobs)}")

    # Any count-like key is a DIAGNOSTIC only. Never a stop condition - a
    # vendor total reported 2,000 against a real 12,233 on a prior tenant.
    counts = {k: v for k, v in payload.items()
              if k != "jobs" and isinstance(v, (int, str))}
    print(f"other top-level keys : {counts if counts else 'none'}  (diagnostic only)")

    scoped = [j for j in jobs if in_scope(j, tenant)]
    print(f"in scope on page 1   : {len(scoped)}/{len(jobs)}")
    if jobs:
        j = jobs[0]
        print(f"\nfirst record: {job_id(j)}  {j.get('title','')[:80]}")
        print(f"  state={j.get('state')!r}  city={j.get('city')!r}  "
              f"employment_type={j.get('employment_type')!r}")

    # Does page N actually advance, or return page 1 again?
    if len(jobs) >= 2:
        time.sleep(DELAY_SECONDS)
        r2 = fetch_page(tenant, tenant.get("first_page", 1) + 1)
        jobs2 = extract_jobs(r2.json()) if r2.status_code == 200 else []
        same = {job_id(x) for x in jobs} == {job_id(x) for x in jobs2}
        print(f"\npage 2: status {r2.status_code}, {len(jobs2)} records, "
              f"identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - page param is not advancing. Stop.")
            return 1

    print("\nProbe OK.")
    log(tenant, "probe", status=r.status_code, page_size=len(jobs),
        in_scope_page1=len(scoped))
    return 0


def mode_inspect(tenant):
    """Print field names AND fill state from one live record.

    Inspect for VALUES, not names. ExternalQualificationsStr existed on two
    Oracle tenants and was EMPTY on one. 'qualifications' matters most here.
    """
    r = fetch_page(tenant, tenant.get("first_page", 1))
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1
    jobs = extract_jobs(r.json())
    if not jobs:
        print("no records returned")
        return 1

    job = jobs[0]
    print(f"RECORD FIELDS  ({job_id(job)})\n")
    for k in sorted(job):
        v = job[k]
        s = v if isinstance(v, str) else json.dumps(v)
        filled = "FILLED " if s and s.strip() not in ("", "null", "[]", "{}") else "EMPTY  "
        print(f"  {filled}{k:24} len={len(s):>6}  {s[:70]!r}")

    for key in ("qualifications", "description", "responsibilities"):
        val = job.get(key) or ""
        print(f"\n--- {key}  ({len(val)} chars) ---")
        print(val[:600] if val else "(EMPTY)")

    print("\nCheck: is 'qualifications' a real segmented block, or empty?")
    print("If empty, requirements live in 'description' and openers must be derived.")
    return 0


def mode_index(tenant):
    """Page the scoped result set. Stop on a genuinely empty page.

    One call per page returns FULL records - no detail fetch on this platform.
    """
    p = paths(tenant)
    os.makedirs(p["pages"], exist_ok=True)

    page = tenant.get("first_page", 1)
    seen, all_jobs = 0, []
    while page - tenant.get("first_page", 1) < MAX_PAGES:
        r = fetch_page(tenant, page)
        if r.status_code != 200:
            print(f"stopped at page {page}: status {r.status_code}")
            log(tenant, "index_error", page=page, status=r.status_code)
            break

        try:
            payload = r.json()
        except Exception:
            print(f"stopped at page {page}: body not JSON")
            break

        jobs = extract_jobs(payload)
        if not jobs:
            print(f"empty page at {page} - done")
            break

        with open(os.path.join(p["pages"], f"page_{page:04d}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

        all_jobs.extend(jobs)
        seen += len(jobs)
        scoped = sum(1 for j in jobs if in_scope(j, tenant))
        print(f"  page {page:>4}  +{len(jobs):>3}  in-scope {scoped:>3}  running {seen}")

        page += 1
        time.sleep(DELAY_SECONDS)

    ids = {job_id(j) for j in all_jobs}
    scoped_all = [j for j in all_jobs if in_scope(j, tenant)]
    print(f"\nindex complete: {seen} records, {len(ids)} distinct, "
          f"{len(scoped_all)} in scope -> {p['pages']}")
    if len(ids) != seen:
        print(f"  NOTE {seen - len(ids)} duplicate records across pages.")

    with open(os.path.join(p["base"], "records.jsonl"), "w", encoding="utf-8") as fh:
        for j in all_jobs:
            fh.write(json.dumps(j, ensure_ascii=False) + "\n")

    log(tenant, "index", captured=seen, distinct=len(ids),
        in_scope=len(scoped_all), pages=page - tenant.get("first_page", 1),
        query=tenant["query"])
    return 0


def load_records(tenant):
    f = os.path.join(paths(tenant)["base"], "records.jsonl")
    if not os.path.exists(f):
        sys.exit("no records.jsonl on disk - run --index first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_report(tenant):
    p = paths(tenant)
    recs = load_records(tenant) if os.path.exists(
        os.path.join(p["base"], "records.jsonl")) else []
    scoped = [j for j in recs if in_scope(j, tenant)]
    print(f"tenant           : {tenant['key']}")
    print(f"query            : {tenant['query']}")
    print(f"location filter  : {tenant.get('location_filter')}")
    print(f"expected in scope: {tenant.get('expected_in_scope')}  (NLx, not employer-stated)")
    print(f"records captured : {len(recs)}")
    print(f"in scope         : {len(scoped)}")
    if scoped:
        qual = sum(1 for j in scoped if (j.get("qualifications") or "").strip())
        age = sum(1 for j in scoped if "older only" in (j.get("title") or "").lower())
        print(f"  qualifications filled : {qual}/{len(scoped)}")
        print(f"  title carries age gate: {age}/{len(scoped)}  (label it, do not exclude)")
    print(f"raw path         : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - Jibe job record -> normalized contract
#
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Adapters do not
# share code with each other; every Jibe field name in this file lives in
# map_record. The requirement EXTRACTOR is not here - that is normalize.experience,
# one implementation, shared, driven by this tenant's forked openers in config.
# ---------------------------------------------------------------------------

# Jibe returns a clean full state name ('Washington'). Normalise to the two-letter
# code so `state` reads the same across every source. Fixed US reference data, not
# tenant config, so it lives in the adapter (duplicated per the no-shared-code rule).
US_STATE_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR", "guam": "GU",
}
_STATE_CODES = set(US_STATE_TO_CODE.values())


def strip_html(s):
    if not isinstance(s, str):
        return ""
    out, depth = [], 0
    for ch in s:
        if ch == "<":
            depth += 1
            out.append(" ")
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    txt = "".join(out)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#39;", "'"), ("&quot;", '"'),
                 ("&lt;", "<"), ("&gt;", ">"), ("&rsquo;", "'"), ("&ldquo;", '"'),
                 ("&rdquo;", '"'), ("&ndash;", "-"), ("&mdash;", "-")):
        txt = txt.replace(a, b)
    return " ".join(txt.split())


def map_record(job, t, retrieved_at):
    """Jibe job record -> normalized contract. Every Jibe field name lives here."""
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    r["source_job_id"] = job_id(job)
    r["company_name"] = job.get("hiring_organization") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = job.get("title")

    r["description_html"] = job.get("description")
    r["description_text"] = strip_html(job.get("description"))
    # First tenant on a non-Oracle source with a real segmented qualifications
    # block (confirmed populated on live records). Map it to qualifications_html so
    # the extractor sectionizes it - requirements live here, not in the marketing
    # description. qualifications stays [] (display segmentation is not attempted).
    qual = job.get("qualifications")
    r["qualifications"] = []
    r["qualifications_html"] = qual or None

    r["location_raw"] = job.get("full_location") or job.get("short_location")
    r["city"] = job.get("city")
    st = (job.get("state") or "").strip()
    if st:
        r["state"] = st.upper() if len(st) == 2 and st.upper() in _STATE_CODES \
            else US_STATE_TO_CODE.get(st.lower())
        if not r["state"]:
            warnings.append(f"state did not resolve: {st!r}")
    r["lat"] = job.get("latitude")
    r["lng"] = job.get("longitude")

    r["employment_type"] = job.get("employment_type")
    r["shift_raw"] = None
    r["posted_at"] = job.get("posted_date") or job.get("create_date")
    r["freshness_state"] = "UNKNOWN"
    # Pay is stated only as description prose ("New Hire Starting Pay Range: ...")
    # - a parse, not a field read - so it is NOT taken here; salary stays unstated.

    r["apply_url"] = job.get("apply_url")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    cats = job.get("categories")
    if isinstance(cats, list) and cats and isinstance(cats[0], dict):
        r["source_category"] = (cats[0].get("name") or "").strip() or None
    elif isinstance(job.get("category"), list) and job["category"]:
        r["source_category"] = str(job["category"][0]).strip() or None
    r["source_function"] = None

    r["source_url"] = job.get("apply_url")
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


def mode_normalize(t):
    """Map captured records into the contract. Derived fields (experience_condition,
    credentials, ...) are left empty BY DESIGN - normalize.enrich fills them with the
    shared extractor and this tenant's forked openers."""
    recs = load_records(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    p = paths(t)
    src = os.path.join(p["base"], "records.jsonl")
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(src)))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for job in recs:
        rec, w = map_record(job, t, retrieved)
        model.apply_seen_state(rec, seen_state, now)
        rec["is_new"] = True if known_before == 0 else rec["first_seen"] == now
        problems = model.validate(rec)
        if problems:
            invalid.append((rec.get("source_job_id"), problems))
        mapped.append(rec)
        warns.extend(w)

    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(seen_state, fh, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in mapped:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"{len(recs)} records -> {len(mapped)} normalized -> {out_path}")
    print(f"\nFILL RATE\n")
    for f, n, pct in model.fill_report(mapped):
        print(f"  {n:>5}  {pct:>5.1f}%  {f}")
    print(f"\nvalidation failures: {len(invalid)}")
    seen = {}
    for _j, probs in invalid:
        for pr in probs:
            seen[pr] = seen.get(pr, 0) + 1
    for pr, n in sorted(seen.items(), key=lambda x: -x[1])[:12]:
        print(f"  {n:>5}  {pr}")
    if warns:
        print(f"\nmapping warnings: {len(warns)}")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Jibe career-site API adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify endpoint, page size, pagination")
    g.add_argument("--inspect", action="store_true", help="print field names AND fill state")
    g.add_argument("--index", action="store_true", help="page the scoped result set")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "index", "report", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
