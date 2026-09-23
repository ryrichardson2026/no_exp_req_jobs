"""Phenom People career-site adapter - No-Experience Job Network.

Read surface: the Phenom `POST /widgets` search API (ddoKey=refineSearch) returns a
paginated JSON job list scoped by facets (state + category); each record carries only a
short descriptionTeaser, so the FULL description - where requirements live - is fetched
per job from the Phenom job-detail page, which embeds a JobPosting JSON-LD block (the same
shape radancy_tb/oracle parse). So this is a hybrid: JSON index (like jibe_api) + JSON-LD
detail (like radancy_tb).

  index  : POST widgets_url  {ddoKey:refineSearch, from, size, selected_fields:{...}}
           -> {refineSearch:{totalHits, data:{jobs:[...]}}}, paged from=0,size,2*size...
           to a genuinely empty page (NEVER trust totalHits as a stop - it is a diagnostic).
  detail : GET  {careers_base}/global/en/job/{jobSeqNo}  (bare pid resolves; no slug needed)
           -> HTML with a JobPosting JSON-LD block; description is the full body.

Config is data: the widgets host, the base search body and the selected_fields facets all
live in tenants.json. No adapter branches on tenant identity.

  python3 -m adapters.phenom --tenant tjx --probe
  python3 -m adapters.phenom --tenant tjx --inspect
  python3 -m adapters.phenom --tenant tjx --index
  python3 -m adapters.phenom --tenant tjx --detail
  python3 -m adapters.phenom --tenant tjx --normalize
"""
import argparse
import html
import json
import os
import re
import sys
import time

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:
    sys.exit("curl-cffi is required:  pip install curl-cffi")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "phenom")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

PLATFORM = "phenom"
DELAY_SECONDS = 1.0
MAX_PAGES = 500          # safety stop, not a business rule
TIMEOUT = 45

_LDJSON = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                     re.S | re.I)


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH}. Known: "
                 f"{', '.join(k for k in tenants if not k.startswith('_'))}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {
        "base": base,
        "detail": os.path.join(base, "detail"),
        "run": os.path.join(base, "run_log.jsonl"),
    }


def log(tenant, event, **fields):
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def page_size(tenant):
    return int(tenant.get("page_size", 50))


def search(tenant, frm):
    """POST the refineSearch widget. Body = the tenant's fixed base + facets + this page."""
    body = dict(tenant["search_body"])
    body["ddoKey"] = "refineSearch"
    body["selected_fields"] = tenant.get("selected_fields", {})
    body["from"] = frm
    body["size"] = page_size(tenant)
    return http.post(tenant["widgets_url"],
                     headers={"content-type": "application/json", "accept": "application/json"},
                     data=json.dumps(body), timeout=TIMEOUT, **_IMPERSONATE)


def extract_jobs(payload):
    """Records arrive wrapped: {"refineSearch": {"data": {"jobs": [...]}}}."""
    rs = payload.get("refineSearch") if isinstance(payload, dict) else None
    if not isinstance(rs, dict):
        return []
    data = rs.get("data") or {}
    return data.get("jobs") or []


def stated_total(payload):
    rs = payload.get("refineSearch") if isinstance(payload, dict) else None
    return rs.get("totalHits") if isinstance(rs, dict) else None


def job_id(job):
    for k in ("jobId", "reqId", "jobSeqNo"):
        if job.get(k):
            return str(job[k])
    return None


def job_pid(job, tenant=None):
    # Which index-record id builds the detail URL. Default = jobSeqNo (most Phenom sites); a
    # tenant whose detail path keys on a different field declares it as config data
    # (detail_pid_field: "jobId" for DaVita), never a tenant branch in code.
    if tenant and tenant.get("detail_pid_field"):
        return job.get(tenant["detail_pid_field"])
    return job.get("jobSeqNo") or job.get("jobId")


def detail_url(tenant, job):
    return tenant["detail_url_tmpl"].format(pid=job_pid(job, tenant))


def in_scope(job, tenant):
    """Location filter on a NAMED FIELD (Phenom returns a clean full 'state', e.g.
    'Washington'). The refineSearch facets already scope server-side, but the client-side
    filter is the authority (a facet can leak - see OnTrac). Empty match_any = take all."""
    f = tenant.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True
    field = f.get("field")
    hay = str(job.get(field, "")) if field else json.dumps(job)
    return any(t in hay for t in terms)


def mode_probe(tenant):
    """Verify the widgets endpoint, page size, pagination and scope rate."""
    print(f"tenant : {tenant['key']}  ({tenant.get('label','')})")
    print(f"widgets: {tenant['widgets_url']}")
    print(f"facets : {tenant.get('selected_fields')}")
    print()
    try:
        r = search(tenant, 0)
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
    print(f"stated total : {stated_total(payload)}  (diagnostic only - NOT a stop condition)")
    scoped = [j for j in jobs if in_scope(j, tenant)]
    print(f"in scope on page 1   : {len(scoped)}/{len(jobs)}")
    if jobs:
        j = jobs[0]
        print(f"\nfirst record: {job_id(j)}  {j.get('title','')[:70]}")
        print(f"  brand={j.get('brand')!r} city={j.get('city')!r} state={j.get('state')!r} "
              f"type={j.get('type')!r} category={j.get('category')!r}")
        print(f"  detail url: {detail_url(tenant, j)}")

    # Does the next page advance, or return page 1 again?
    if len(jobs) >= page_size(tenant):
        time.sleep(DELAY_SECONDS)
        p2 = search(tenant, page_size(tenant)).json()
        jobs2 = extract_jobs(p2)
        same = {job_id(x) for x in jobs} == {job_id(x) for x in jobs2}
        print(f"\npage 2: {len(jobs2)} records, identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - `from` is not advancing. Stop and re-derive.")
            return 1
    print("\nProbe OK.")
    log(tenant, "probe", status=r.status_code, page1=len(jobs), stated_total=stated_total(payload))
    return 0


def extract_jobposting(html):
    """Return the JobPosting JSON-LD dict from a stored detail page, or None."""
    for m in _LDJSON.finditer(html or ""):
        try:
            obj = json.loads(m.group(1).strip())
        except Exception:
            continue
        for o in (obj if isinstance(obj, list) else [obj]):
            if isinstance(o, dict):
                t = o.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return o
    return None


# Some Phenom sites (DaVita) serve NO JobPosting JSON-LD; the full description is server-rendered
# in the phApp.ddo object as a single JSON-escaped "description" string (one substantive occurrence
# in the page). Config opts in with detail_source:"ddo" — data-driven, no tenant branch.
def _ddo_description(html_text):
    m = re.search(r'"description"\s*:\s*("(?:[^"\\]|\\.)*")', html_text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))   # JSON-decode: < -> '<', escaped quotes, entities
    except ValueError:
        return None


def extract_detail(html_text, tenant):
    """The detail record fed to map_record. detail_source:"jsonld" (default) -> the JobPosting
    JSON-LD dict; "ddo" -> a minimal {"description": ...} from phApp.ddo. Either way map_record
    only REQUIRES `description` (title/date/employment_type fall back to the index record)."""
    if (tenant.get("detail_source") or "jsonld") == "ddo":
        desc = _ddo_description(html_text)
        return {"description": desc} if desc else None
    return extract_jobposting(html_text)


def mode_inspect(tenant):
    """Fetch one in-scope job's detail page and print the JobPosting JSON-LD fields + fill.

    Inspect for VALUES, not names - a field that exists but is empty is not a source."""
    r = search(tenant, 0)
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1
    jobs = [j for j in extract_jobs(r.json()) if in_scope(j, tenant)]
    if not jobs:
        print("no in-scope jobs on page 1")
        return 1
    url = detail_url(tenant, jobs[0])
    print(f"index record fields ({len(jobs[0])}): {', '.join(sorted(jobs[0]))}\n")
    print(f"detail: {url}\n")
    time.sleep(DELAY_SECONDS)
    d = http.get(url, timeout=TIMEOUT, **_IMPERSONATE)
    print(f"status {d.status_code}, {len(d.content)} bytes\n")
    if d.status_code != 200:
        return 1
    src = tenant.get("detail_source") or "jsonld"
    jp = extract_detail(d.text, tenant)
    if not jp:
        print(f"NO detail description found (detail_source={src}). The parse assumption is wrong -")
        print("stop and re-derive before running --detail.")
        return 1
    print(f"DETAIL FIELDS (source={src})\n")
    for k in sorted(jp):
        v = jp[k]
        s = v if isinstance(v, str) else json.dumps(v)
        filled = "FILLED " if s and s.strip() else "EMPTY  "
        print(f"  {filled}{k:22} len={len(s):>6}  {s[:70]!r}")
    return 0


def mode_index(tenant):
    """Page the scoped result set. Stop on a genuinely empty page, never on the total."""
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    size = page_size(tenant)
    frm, seen, all_jobs = 0, 0, []
    try:
        while frm < MAX_PAGES * size:
            r = fetch_paged(lambda: search(tenant, frm), label=f"from {frm}: ")
            try:
                payload = r.json()
            except Exception:
                raise Truncated(f"from {frm}: 200 but body not JSON")
            jobs = extract_jobs(payload)
            if not jobs:
                print(f"empty page at from={frm} - done")
                break
            all_jobs.extend(jobs)
            seen += len(jobs)
            scoped = sum(1 for j in jobs if in_scope(j, tenant))
            print(f"  from {frm:>5}  +{len(jobs):>3}  in-scope {scoped:>3}  running {seen}  "
                  f"(stated total {stated_total(payload)})")
            frm += size
            time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT: {e}. Partial capture DISCARDED (prior data kept); records.jsonl "
              f"NOT rewritten. Re-run when the source recovers.")
        log(tenant, "index_abort", detail=str(e), captured_before_abort=seen)
        return 1

    ids = {job_id(j) for j in all_jobs}
    scoped_all = [j for j in all_jobs if in_scope(j, tenant)]
    print(f"\nindex complete: {seen} records, {len(ids)} distinct, "
          f"{len(scoped_all)} in scope -> {p['base']}")
    if len(ids) != seen:
        print(f"  NOTE {seen - len(ids)} duplicate records across pages.")
    with open(os.path.join(p["base"], "records.jsonl"), "w", encoding="utf-8") as fh:
        for j in all_jobs:
            fh.write(json.dumps(j, ensure_ascii=False) + "\n")
    log(tenant, "index", captured=seen, distinct=len(ids), in_scope=len(scoped_all))
    return 0


def load_records(tenant):
    f = os.path.join(paths(tenant)["base"], "records.jsonl")
    if not os.path.exists(f):
        sys.exit("no records.jsonl on disk - run --index first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def in_scope_unique(tenant):
    """In-scope records, deduped by job_id - the set --detail fetches and reconcile keys on."""
    scoped = [j for j in load_records(tenant) if in_scope(j, tenant)]
    seen, unique = set(), []
    for j in scoped:
        jid = job_id(j)
        if jid and jid not in seen:
            seen.add(jid)
            unique.append(j)
    return unique


def mode_detail(tenant):
    """Fetch detail pages for in-scope records. Resumable. Raw HTML written whole -
    JSON-LD is extracted at normalize time, so a parser change never costs a re-fetch."""
    p = paths(tenant)
    os.makedirs(p["detail"], exist_ok=True)
    unique = in_scope_unique(tenant)
    print(f"in scope, distinct: {len(unique)}")
    done = skipped = failed = no_ld = 0
    for i, job in enumerate(unique, 1):
        out = os.path.join(p["detail"], f"{job_id(job)}.html")
        if os.path.exists(out):
            skipped += 1
            continue
        r = http.get(detail_url(tenant, job), timeout=TIMEOUT, **_IMPERSONATE)
        if r.status_code != 200:
            print(f"  [{i}/{len(unique)}] {job_id(job)} status {r.status_code}")
            failed += 1
            log(tenant, "detail_error", id=job_id(job), status=r.status_code)
        else:
            body = r.text
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(body)
            if not extract_detail(body, tenant):
                no_ld += 1
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(unique)}] {done} fetched")
        time.sleep(DELAY_SECONDS)
    print(f"\ndetail complete: {done} fetched, {skipped} on disk, {failed} failed")
    print(f"pages with no detail description: {no_ld}")
    log(tenant, "detail", scoped=len(unique), fetched=done, skipped=skipped,
        failed=failed, no_ldjson=no_ld)
    return 0


def mode_report(tenant):
    p = paths(tenant)
    recs = load_records(tenant) if os.path.exists(
        os.path.join(p["base"], "records.jsonl")) else []
    scoped = [j for j in recs if in_scope(j, tenant)]
    details = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant           : {tenant['key']}")
    print(f"facets           : {tenant.get('selected_fields')}")
    print(f"location filter  : {tenant.get('location_filter')}")
    print(f"records captured : {len(recs)}")
    print(f"in scope         : {len(scoped)}")
    print(f"detail on disk   : {details}")
    print(f"raw path         : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - Phenom index record + detail JobPosting JSON-LD -> normalized contract
#
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Every Phenom field name
# lives in map_record. The requirement EXTRACTOR is not here - that is
# normalize.experience, shared, driven by this tenant's forked openers in config.
# ---------------------------------------------------------------------------

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


def _state_code(st):
    st = (st or "").strip()
    if not st:
        return None
    if len(st) == 2 and st.upper() in _STATE_CODES:
        return st.upper()
    return US_STATE_TO_CODE.get(st.lower())


_EMP_TYPE = {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "CONTRACTOR": "Contract",
             "TEMPORARY": "Temporary", "INTERN": "Internship", "PER_DIEM": "Per diem"}


def _emp_type(v):
    """JobPosting employmentType is a JSON array (["PART_TIME"]) - normalize to a clean label
    so the card never renders the raw array. Accepts list, JSON-string-of-list, or plain string."""
    if isinstance(v, str) and v.startswith("["):
        try:
            v = json.loads(v)
        except ValueError:
            pass
    if isinstance(v, list):
        v = v[0] if v else None
    if not v:
        return None
    key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
    return _EMP_TYPE.get(key, str(v).strip().title())


def map_record(job, ld, t, retrieved_at):
    """Phenom index record (job) + detail JobPosting JSON-LD (ld) -> normalized contract."""
    r = model.new_record()
    warnings = []
    ld = ld or {}

    r["source_id"] = PLATFORM
    r["source_job_id"] = job_id(job)
    r["company_name"] = job.get("brand") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = job.get("title") or ld.get("title")

    # Requirements live in the full description body (JSON-LD), not the index teaser and
    # not a segmented qualifications field - the openers sectionize description_html.
    # Phenom's JSON-LD description is HTML-ENTITY-ENCODED ("&lt;div&gt;"), so unescape once
    # to recover real tags before storing/stripping - else the extractor sees escaped HTML
    # and description_text carries literal "<div>" text.
    desc = ld.get("description")
    if not desc:
        warnings.append("no JobPosting description on detail page")
    desc = html.unescape(desc) if desc else desc
    r["description_html"] = desc
    r["description_text"] = strip_html(desc)
    r["qualifications"] = []
    r["qualifications_html"] = None

    r["location_raw"] = job.get("cityStateCountry") or job.get("cityState") or job.get("location")
    r["city"] = job.get("city")
    r["state"] = _state_code(job.get("state"))
    if job.get("state") and not r["state"]:
        warnings.append(f"state did not resolve: {job.get('state')!r}")
    r["lat"] = job.get("latitude")
    r["lng"] = job.get("longitude")

    r["employment_type"] = _emp_type(ld.get("employmentType") or job.get("type"))
    r["shift_raw"] = None
    r["posted_at"] = (ld.get("datePosted") or job.get("postedDate") or job.get("dateCreated") or "")[:10] or None
    r["freshness_state"] = "UNKNOWN"
    # No baseSalary on the JobPosting JSON-LD (confirmed by --inspect); pay, when present, is
    # description prose, so salary stays unstated (not parsed here).

    r["apply_url"] = job.get("applyUrl") or job.get("apply_url")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    cat = job.get("category")
    if isinstance(cat, list) and cat:
        r["source_category"] = str(cat[0]).strip() or None
    elif isinstance(cat, str):
        r["source_category"] = cat.strip() or None
    r["source_function"] = None

    r["source_url"] = detail_url(t, job)
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    return r, warnings


def mode_normalize(t):
    """Map captured records + their detail JSON-LD into the contract. Derived fields
    (experience_condition, credentials, ...) are left empty BY DESIGN - normalize.enrich
    fills them with the shared extractor and this tenant's forked openers."""
    p = paths(t)
    unique = in_scope_unique(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    src = os.path.join(p["base"], "records.jsonl")
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(src)))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns, no_detail = [], [], [], 0
    for job in unique:
        detail_file = os.path.join(p["detail"], f"{job_id(job)}.html")
        ld = None
        if os.path.exists(detail_file):
            with open(detail_file, "r", encoding="utf-8") as fh:
                ld = extract_detail(fh.read(), t)
        if not ld:
            no_detail += 1
        rec, w = map_record(job, ld, t, retrieved)
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

    print(f"{len(unique)} in-scope -> {len(mapped)} normalized "
          f"({no_detail} had no detail description) -> {out_path}")
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
    log(t, "normalize", records=len(mapped), invalid=len(invalid), no_detail=no_detail)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Phenom People career-site adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify widgets endpoint, page size, pagination")
    g.add_argument("--inspect", action="store_true", help="print detail JobPosting fields AND fill")
    g.add_argument("--index", action="store_true", help="page the scoped result set")
    g.add_argument("--detail", action="store_true", help="fetch in-scope job detail pages")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "index", "detail", "report", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main() or 0)
