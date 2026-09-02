"""
Compass careers-site JSON API adapter - No-Experience Job Network.

SCOPE: fetch and write raw JSON to disk. Nothing else.
No field mapping, no dedupe, no normalized model, no experience logic.

PLATFORM NAMING - read this before adding a tenant.
Named for the READ SURFACE. Compass Group's ATS is SAP SuccessFactors
(applyURL -> career8.successfactors.com) and its text-to-apply layer is
Paradox (olivia.paradox.ai). Neither is what gets fetched. What gets fetched
is /api/get-jobs on careers.compass-usa.com.

THIRD CONFIRMATION OF FINDING 42 - the ATS is not the read surface:
  Allied Universal  iCIMS          -> TalentBrew HTML       (radancy_tb)
  Dollar General    iCIMS          -> Jibe JSON API         (jibe_api)
  Panda Rest. Group SuccessFactors -> Paradox-hosted pages  (not built)
  Compass Group     SuccessFactors -> own careers API       (this adapter)
Panda and Compass share an ATS *and* a text-apply vendor and still need
different adapters. Two employers, same ATS, no shared fetch path.

GENERALISATION: unknown. This looks like a bespoke careers-site API rather
than a vendor platform, so it may cover exactly one employer. That is
acceptable - the CEO threshold (F35) is that a bespoke adapter is worth it
when the employer's volume justifies it alone. Compass is ~301 WA jobs
across three otherwise-empty categories.

Usage:
  python3 -m adapters.compass_api --tenant compass_group --probe
  python3 -m adapters.compass_api --tenant compass_group --inspect
  python3 -m adapters.compass_api --tenant compass_group --facets
  python3 -m adapters.compass_api --tenant compass_group --index
  python3 -m adapters.compass_api --tenant compass_group --report
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
RAW_ROOT = os.path.join(ROOT, "raw", "compass_api")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "compass_api"
DELAY_SECONDS = 1.0
MAX_PAGES = 200          # safety stop, not a business rule
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


def fetch_page(tenant, page, session=None):
    """POST with the filters in the QUERY STRING, not the body.

    Captured from the site's own XHR: filter[state][0]=WA and
    filter[state][1]=Washington are URL params on a POST. The observed
    request also carried a small JSON body (content-length 78); body_extra
    in config supplies it if --probe shows it is required.
    """
    # JSON gives list-of-lists; urlencode requires tuple pairs, so coerce.
    params = [tuple(p) for p in tenant["query"]]
    params.append((tenant.get("page_param", "page_number"), str(page)))
    url = f"{tenant['api_url']}?{urlencode(params)}"
    body = tenant.get("body_extra") or {}
    caller = session or http
    return caller.post(url, json=body,
                       headers={"accept": "application/json",
                                "content-type": "application/json",
                                "origin": tenant["careers_host"],
                                "referer": tenant["careers_host"] + "/jobs"},
                       timeout=TIMEOUT, **_IMPERSONATE)


def open_session(tenant):
    """GET the careers page so the server sets its cookies (the ct= JWT among
    them) in the jar, then reuse the SAME session for the POST. Same shape as the
    Workday adapter's session handling.

    No token is pasted from config: a ct= JWT is short-lived and would rot between
    runs, making every future capture depend on a manual grab. Returns
    (session, get_status)."""
    s = http.Session()
    s.headers.update({
        "accept": "text/html,application/xhtml+xml",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/151.0.0.0 Safari/537.36"),
    })
    r = s.get(tenant["careers_host"] + "/jobs", timeout=TIMEOUT, **_IMPERSONATE)
    return s, r.status_code


def cookie_names(session):
    """Cookie names currently in the session jar, defensively across curl_cffi
    versions. Reported for diagnosis; never used to PREDICT the POST result -
    MultiCare returned records with no CSRF token in the jar at all, so that
    prediction was wrong and was removed."""
    try:
        return sorted(session.cookies.keys())
    except Exception:
        try:
            return sorted(c.name for c in session.cookies.jar)
        except Exception:
            return []


def extract_jobs(payload):
    return payload.get("jobs", []) or []


def job_id(job):
    for k in ("requisitionID", "uniqueID", "reference", "sourceID"):
        if job.get(k):
            return str(job[k])
    return None


def in_scope(job, tenant):
    """Location filter reads locations[].stateAbbr - NOT the top-level state.

    The response's own State facet is DIRTY: WA 296, Washington 5, and
    'Northwest Region' 3, plus Arizona/Nevada/Oregon/Utah strays pulled in
    by radius=15. A top-level state read would miss the region rows and keep
    the out-of-state ones. Every sampled record carries a clean stateAbbr on
    the location object, so that is the field.
    """
    f = tenant.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True
    field = f.get("field", "stateAbbr")
    for loc in job.get("locations") or []:
        if str(loc.get(field, "")).strip().upper() in {t.upper() for t in terms}:
            return True
    return False


def mode_probe(tenant):
    """Verify the endpoint, page size, pagination, and whether a body/session
    is actually required. All four were unknown from the DevTools capture."""
    print(f"tenant : {tenant['key']}  ({tenant.get('label','')})")
    print(f"api    : {tenant['api_url']}")
    print(f"body   : {tenant.get('body_extra') or '{} (empty)'}")
    print()

    try:
        s, get_status = open_session(tenant)
    except Exception as e:
        print(f"FAIL  session GET raised: {type(e).__name__}: {e}")
        return 1
    names = cookie_names(s)
    print(f"session GET status : {get_status}")
    print(f"cookies in jar     : {names or 'none'}")
    print(f"ct= present        : {'ct' in names}   "
          f"(diagnostic - the POST below is the actual test, not this line)")
    print()

    try:
        r = fetch_page(tenant, tenant.get("first_page", 1), session=s)
    except Exception as e:
        print(f"FAIL  request raised: {type(e).__name__}: {e}")
        return 1

    print(f"status : {r.status_code}   bytes: {len(r.content)}")
    if r.status_code != 200:
        print(r.text[:500])
        print(f"\ncookies the jar holds: {cookie_names(s)}")
        print("4xx with a session established: the ct= JWT (or another cookie) is")
        print("required and did not land from the GET. Capture it from a live")
        print("session; do not fabricate one.")
        return 1

    payload = r.json()
    jobs = extract_jobs(payload)
    total = payload.get("totalJob")
    print(f"page size (measured) : {len(jobs)}")
    print(f"totalJob             : {total}   (DIAGNOSTIC ONLY, never a stop condition)")

    scoped = [j for j in jobs if in_scope(j, tenant)]
    print(f"in scope on page 1   : {len(scoped)}/{len(jobs)}")
    if jobs:
        j = jobs[0]
        locs = j.get("locations") or [{}]
        print(f"\nfirst record: {job_id(j)}  {j.get('title','')[:70]}")
        print(f"  brandName={j.get('brandName')!r}  companyName={j.get('companyName')!r}")
        print(f"  stateAbbr={locs[0].get('stateAbbr')!r}  city={locs[0].get('city')!r}")
        print(f"  locations on record: {len(j.get('locations') or [])}")

    # Does page_number actually advance?
    if len(jobs) >= 2:
        time.sleep(DELAY_SECONDS)
        r2 = fetch_page(tenant, tenant.get("first_page", 1) + 1, session=s)
        jobs2 = extract_jobs(r2.json()) if r2.status_code == 200 else []
        same = {job_id(x) for x in jobs} == {job_id(x) for x in jobs2}
        print(f"\npage 2: status {r2.status_code}, {len(jobs2)} records, "
              f"identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - page_number is not advancing. Stop.")
            return 1

    print("\nProbe OK.")
    log(tenant, "probe", status=r.status_code, page_size=len(jobs),
        total_job=total, in_scope_page1=len(scoped))
    return 0


def mode_facets(tenant):
    """Print the response's own facet catalog.

    The payload carries State, City, Brand, Category and Employment Type
    facets with counts - the Target facet-block advantage without a second
    call. This is the reliable count, and it also exposes the dirty state
    values before they are trusted.
    """
    sess, _ = open_session(tenant)
    r = fetch_page(tenant, tenant.get("first_page", 1), session=sess)
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1
    payload = r.json()
    print(f"totalJob: {payload.get('totalJob')}\n")
    for facet in payload.get("facets", []) or []:
        rows = facet.get("facet_field_keyvalue", []) or []
        print(f"=== {facet.get('alias')}  (field: {facet.get('field')}) "
              f"- {len(rows)} values ===")
        for row in sorted(rows, key=lambda x: -(x.get("doc_count") or 0)):
            print(f"  {row.get('doc_count'):>6}  {row.get('custom_value')!r}")
        print()
    print("NOTE: the State facet is dirty (WA / Washington / Northwest Region,")
    print("plus out-of-state strays from radius). in_scope reads")
    print("locations[].stateAbbr instead. Confirm that here before --index.")
    return 0


def mode_inspect(tenant):
    """Print field names AND fill state from one live record."""
    sess, _ = open_session(tenant)
    r = fetch_page(tenant, tenant.get("first_page", 1), session=sess)
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
        print(f"  {filled}{k:22} len={len(s):>7}  {s[:60]!r}")

    print("\n--- description (first 1500 chars) ---")
    print((job.get("description") or "(EMPTY)")[:1500])
    print("\nLook for the REQUIREMENT SHAPE. Observed on this employer:")
    print("  'Requirement: ...' as an INLINE LABEL inside a <li>, not a heading")
    print("  'Qualifications' as a heading on salaried templates")
    print("These are different openers. Derive from this tenant's own text.")
    return 0


def mode_index(tenant):
    """Page the result set. Stop on a genuinely empty page, never on a total."""
    p = paths(tenant)
    os.makedirs(p["pages"], exist_ok=True)

    sess, _ = open_session(tenant)
    page = tenant.get("first_page", 1)
    seen, all_jobs = 0, []
    while page - tenant.get("first_page", 1) < MAX_PAGES:
        r = fetch_page(tenant, page, session=sess)
        if r.status_code != 200:
            print(f"stopped at page {page}: status {r.status_code}")
            log(tenant, "index_error", page=page, status=r.status_code)
            break

        payload = r.json()
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
        in_scope=len(scoped_all), pages=page - tenant.get("first_page", 1))
    return 0


def load_records(tenant):
    f = os.path.join(paths(tenant)["base"], "records.jsonl")
    if not os.path.exists(f):
        sys.exit("no records.jsonl on disk - run --index first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_report(tenant):
    from collections import Counter
    p = paths(tenant)
    recs = load_records(tenant) if os.path.exists(
        os.path.join(p["base"], "records.jsonl")) else []
    scoped = [j for j in recs if in_scope(j, tenant)]
    print(f"tenant           : {tenant['key']}")
    print(f"location filter  : {tenant.get('location_filter')}")
    print(f"expected in scope: {tenant.get('expected_in_scope')}  (NLx, diagnostic)")
    print(f"records captured : {len(recs)}")
    print(f"in scope         : {len(scoped)}")
    if scoped:
        brands = Counter(j.get("brandName") or "(none)" for j in scoped)
        print(f"\nBRANDS ({len(brands)}) - brandName is what renders on the card,")
        print("not companyName ('Compass Group Prod 5' means nothing to a seeker):")
        for b, n in brands.most_common():
            print(f"  {n:>5}  {b}")
        multi = sum(1 for j in scoped if len(j.get("locations") or []) > 1)
        print(f"\nrecords with >1 location: {multi}")
        ats = Counter("successfactors" if "successfactors" in (j.get("applyURL") or "")
                      else "other" for j in scoped)
        print(f"apply destinations: {dict(ats)}")
    print(f"\nraw path         : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - Compass job record -> normalized contract
#
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Every Compass field
# name lives in map_record. The requirement EXTRACTOR is not here - that is
# normalize.experience, one implementation, shared, driven by forked openers.
# ---------------------------------------------------------------------------

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


def pick_location(job, tenant):
    """The in-scope (WA) location object, else the first. locations is an array;
    a posting can span sites, and in_scope already matched at least one for a
    scoped record."""
    locs = job.get("locations") or []
    f = tenant.get("location_filter") or {}
    field = f.get("field", "stateAbbr")
    terms = {t.upper() for t in (f.get("match_any") or [])}
    for loc in locs:
        if str(loc.get(field, "")).strip().upper() in terms:
            return loc
    return locs[0] if locs else {}


def job_categories(job):
    """Employer's own category labels, carried in jobCardExtraFields as a
    {attribute_name: 'job_categories', value: [...]} row. A field read."""
    for row in job.get("jobCardExtraFields") or []:
        if row.get("attribute_name") == "job_categories":
            v = row.get("value")
            if isinstance(v, list):
                return "; ".join(str(x) for x in v) or None
            return str(v) or None
    return None


def map_record(job, t, retrieved_at):
    """Compass job record -> normalized contract. Every Compass field name here."""
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    r["source_job_id"] = job_id(job)
    # brandName, NOT companyName. companyName reads 'Compass Group Prod 5' - an
    # internal instance label meaningless to a seeker. brandName is what a person
    # recognises (Levy at Lumen Field, Bon Appetit at Expedia). Same reasoning that
    # keeps Fred Meyer and QFC separate.
    r["company_name"] = job.get("brandName") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = job.get("title")

    r["description_html"] = job.get("description")
    r["description_text"] = strip_html(job.get("description"))
    # No segmented qualifications field on this board - requirements live in the
    # description body (confirmed by --inspect). Same shape as Allied.
    r["qualifications"] = []
    r["qualifications_html"] = None

    loc = pick_location(job, t)
    city = (loc.get("city") or "").strip() or None
    state = (loc.get("stateAbbr") or "").strip().upper() or None
    r["location_raw"] = ", ".join([x for x in (city, state) if x]) or None
    r["city"] = city
    r["state"] = state
    r["lat"] = loc.get("latitude")
    r["lng"] = loc.get("longitude")

    et = job.get("employmentType")
    r["employment_type"] = (et[0] if isinstance(et, list) and et else et) or None
    r["shift_raw"] = None
    r["posted_at"] = None            # no posting-date field on this board
    r["freshness_state"] = "UNKNOWN"
    # Pay is stated only as description prose ('Salary: $81,000 - 86,500/year') -
    # a parse, not a field read - so it is NOT taken here; salary stays unstated.

    r["apply_url"] = job.get("applyURL")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    r["source_category"] = job_categories(job)
    r["source_function"] = None

    r["source_url"] = job.get("applyURL")
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


def mode_normalize(t):
    """Map captured records into the contract. Derived fields are left empty BY
    DESIGN - normalize.enrich fills them with the shared extractor and this
    tenant's forked openers. Deduped by requisition id (one record repeated
    across a page boundary in the capture)."""
    recs = load_records(t)
    seen_ids, unique = set(), []
    for job in recs:
        jid = job_id(job)
        if jid in seen_ids:
            continue
        seen_ids.add(jid)
        unique.append(job)

    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    src = os.path.join(paths(t)["base"], "records.jsonl")
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(src)))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for job in unique:
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

    print(f"{len(recs)} records -> {len(unique)} distinct -> {len(mapped)} normalized -> {out_path}")
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
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Compass careers API adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify endpoint, page size, pagination")
    g.add_argument("--facets", action="store_true", help="print the response's facet catalog")
    g.add_argument("--inspect", action="store_true", help="print field names AND fill state")
    g.add_argument("--index", action="store_true", help="page the result set")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "facets", "inspect", "index", "report", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
