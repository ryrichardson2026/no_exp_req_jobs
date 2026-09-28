"""Walmart careers-site adapter - No-Experience Job Network.

Read surface: the custom Walmart careers GraphQL "job search assistant" at
`POST careers.walmart.com/api/graphql` (a persisted query, identified by `queryId`, whose
`variables.chatRequest.context.job_search_context` carries a small filter DSL). The index
record carries NO description; the FULL description is server-rendered on the job detail page
`/us/en/jobs/{job_id}` inside the Next.js `__NEXT_DATA__` island (props.pageProps.jobDetails).
So this is a hybrid like phenom: a JSON index + an HTML-embedded-JSON detail.

  index  : POST /api/graphql  {queryId, variables:{chatRequest:{...,context:{job_search_context:
           {refined_query, filters, job_page, ...}}}}}
           -> data.jobSearchAssistant.tool_messages[0].artifact.{jobs[], total_jobs,
              store_jobs_aggregation_result[]}.
  detail : GET  /us/en/jobs/{job_id}
           -> HTML; parse <script id="__NEXT_DATA__"> -> props.pageProps.jobDetails.

WHY PER-STORE ENUMERATION (invariant 3, completeness). The assistant's relevance-sorted
pagination does NOT converge: adjacent pages overlap ~40% and paging the whole WA set to
depth returns only ~85% of the true total (measured 465/549). But the same base response
carries a `store_jobs_aggregation_result` whose per-store counts SUM EXACTLY to total_jobs,
and a compound filter `primaryLocationState == 'WA' && storeNumber == 'N'` returns that
store's set completely (small stores in one page). So the index enumerates PER STORE and
pages each store until it has collected that store's own advertised count (a deterministic
stop that survives the relevance overlap), then unions. `total_jobs` and each store `count`
are diagnostics/loop-bounds, never a global stop.

Config is data: the GraphQL host, the persisted queryId, the base WA filter and the scope
(source prefix / pay frequency / excluded categories) all live in tenants.json. No adapter
branches on tenant identity.

  python3 -m adapters.walmart --tenant walmart --probe
  python3 -m adapters.walmart --tenant walmart --inspect
  python3 -m adapters.walmart --tenant walmart --index
  python3 -m adapters.walmart --tenant walmart --detail
  python3 -m adapters.walmart --tenant walmart --normalize
"""
import argparse
import json
import os
import sys
import time
import uuid

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:
    sys.exit("curl-cffi is required:  pip install curl-cffi")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "walmart")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

PLATFORM = "walmart"
DELAY_SECONDS = 0.5
MAX_STORE_PAGES = 12     # per-store page cap (safety stop, not a business rule)
TIMEOUT = 45

GRAPHQL_URL = "https://careers.walmart.com/api/graphql"
INIT_URL = "https://careers.walmart.com/api/init"
DETAIL_URL_TMPL = "https://careers.walmart.com/us/en/jobs/{pid}"


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


# ---------------------------------------------------------------------------
# HTTP - a cookie-bearing session (bootstrapped once against /api/init), plus the
# two calls: the GraphQL search (index) and the detail-page GET.
# ---------------------------------------------------------------------------

_SESSION = None


def session():
    global _SESSION
    if _SESSION is None:
        _SESSION = http.Session()
        try:                                   # establish any session cookie the API expects
            _SESSION.get(INIT_URL, timeout=TIMEOUT, **_IMPERSONATE)
        except Exception:
            pass
    return _SESSION


def _thread_id():
    # A FRESH thread id per request: the assistant is stateful, and reusing one thread across
    # paged/parallel requests corrupts the result window. Uniqueness, not format, is what matters.
    return f"S-{int(time.time() * 1000)}-{uuid.uuid4()}"


def search(tenant, filters, job_page):
    """POST the persisted job-search query for one filter slice + page."""
    body = {
        "queryId": tenant["index_query_id"],
        "variables": {
            "chatRequest": {
                "messages": [{"role": "user", "content": [{"type": "text", "text": "show jobs"}]}],
                "thread_id": _thread_id(),
                "channel": "job_search",
                "context": {
                    "job_search_context": {
                        "refined_query": tenant.get("refined_query", "jobId == '*'"),
                        "direct_search": True,
                        "locale": "en_US",
                        "sort": "relevance",
                        "active_tab": "jobs",
                        "management_levels": [],
                        "content_page": 0,
                        "future_roles_page": 0,
                        "job_page": job_page,
                        "filters": filters,
                    }
                },
            }
        },
        "headers": {},
    }
    return session().post(GRAPHQL_URL,
                          headers={"content-type": "application/json", "accept": "application/json"},
                          data=json.dumps(body), timeout=TIMEOUT, **_IMPERSONATE)


def artifact(payload):
    """The jobs payload is the first tool_message artifact that carries a `jobs` list."""
    try:
        tms = payload["data"]["jobSearchAssistant"]["tool_messages"]
    except (KeyError, TypeError):
        return None
    for tm in tms or []:
        art = tm.get("artifact") if isinstance(tm, dict) else None
        if isinstance(art, dict) and "jobs" in art:
            return art
    return None


def wa_filter(tenant):
    lf = tenant.get("location_filter") or {}
    field = lf.get("query_field", "primaryLocationState")
    terms = lf.get("match_any") or ["WA"]
    return f"{field} == '{terms[0]}'"


def store_filter(tenant, store_number):
    return f"{wa_filter(tenant)} && storeNumber == '{store_number}'"


# ---------------------------------------------------------------------------
# record identity + scope
# ---------------------------------------------------------------------------

def job_id(job):
    for k in ("job_id", "jobId"):
        if job.get(k):
            return str(job[k])
    return None


def _source_prefix(job):
    jid = job_id(job) or ""
    return jid.split("-", 1)[0] if "-" in jid else jid


def in_scope(job, tenant):
    """The client-side scope is the authority (a server filter can leak). WA by the location
    field, then the tenant's structural scope: an id-prefix allowlist (store 'CP' vs corporate
    'R'), a pay-frequency allowlist (hourly frontline), and an excluded-category denylist. All
    are config DATA (scope.*), never a tenant branch. Empty rule = don't constrain on it."""
    lf = tenant.get("location_filter") or {}
    terms = lf.get("match_any")
    if terms:
        field = lf.get("field", "state")
        if not any(t == str(job.get(field, "")) for t in terms):
            return False

    scope = tenant.get("scope") or {}
    srcs = scope.get("source_prefix")
    if srcs and _source_prefix(job) not in srcs:
        return False
    pays = scope.get("pay_frequency")
    if pays and job.get("payFrequency") not in pays:
        return False
    excl = scope.get("exclude_categories")
    if excl:
        cats = job.get("categories") or []
        if any(c in excl for c in cats):
            return False
    return True


# ---------------------------------------------------------------------------
# index - per-store enumeration
# ---------------------------------------------------------------------------

def _base_artifact(tenant):
    """The unscoped WA base query: carries the store aggregation (the enumeration driver) and
    the diagnostic total. Retried for transport, then validated for the artifact."""
    r = fetch_paged(lambda: search(tenant, wa_filter(tenant), 0), label="base: ")
    try:
        payload = r.json()
    except Exception:
        raise Truncated("base: 200 but body not JSON")
    art = artifact(payload)
    if art is None:
        raise Truncated("base: response carried no jobs artifact (query id / filter broken?)")
    return art


def _enumerate_store(tenant, store_number, expected):
    """Page one store's slice until we've collected its advertised count (deterministic stop
    that survives relevance overlap), an empty page, no-progress, or the page cap. Returns the
    unique job dicts for the store. Raises Truncated on a transport/artifact failure."""
    collected, page = {}, 0
    while page < MAX_STORE_PAGES:
        r = fetch_paged(lambda: search(tenant, store_filter(tenant, store_number), page),
                        label=f"store {store_number} p{page}: ")
        try:
            payload = r.json()
        except Exception:
            raise Truncated(f"store {store_number} p{page}: 200 but body not JSON")
        art = artifact(payload)
        if art is None:
            raise Truncated(f"store {store_number} p{page}: no jobs artifact")
        jobs = art.get("jobs") or []
        if not jobs:
            break
        new = 0
        for j in jobs:
            jid = job_id(j)
            if jid and jid not in collected:
                collected[jid] = j
                new += 1
        page += 1
        if expected and len(collected) >= expected:
            break
        if new == 0:                            # relevance window plateaued - no more to gain
            break
        time.sleep(DELAY_SECONDS)
    return list(collected.values())


def mode_index(tenant):
    """Enumerate every WA store, union their complete slices. Stop conditions are per-store
    (own count / empty / no-progress); the global total is a diagnostic, never a stop."""
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)

    try:
        base = _base_artifact(tenant)
    except Truncated as e:
        print(f"\n!! ABORT: {e}. Nothing captured; records.jsonl NOT rewritten.")
        log(tenant, "index_abort", detail=str(e), captured_before_abort=0)
        return 1

    stores = base.get("store_jobs_aggregation_result") or []
    stated_total = base.get("total_jobs")
    agg_sum = sum(int(s.get("count") or 0) for s in stores)
    print(f"stores: {len(stores)}   agg-sum: {agg_sum}   vendor total_jobs: {stated_total}")
    if not stores:
        print("!! ABORT: base query returned no store aggregation - cannot enumerate.")
        log(tenant, "index_abort", detail="no store_jobs_aggregation_result")
        return 1
    # Completeness tripwire (invariant 3). The store aggregation IS the enumeration universe, so it
    # must account for every job the vendor's OWN headline counts: agg_sum and total_jobs come from
    # the SAME base response and must agree EXACTLY. This is not "trusting a vendor total" as a
    # pagination stop (we still exhaust each store) - it cross-checks two vendor numbers so a CAPPED
    # or truncated aggregation can't silently drop stores (e.g. newly-opened WA stores beyond a cap).
    # On disagreement, refuse to enumerate a partial board rather than publish an undercount.
    if stated_total is not None and agg_sum != stated_total:
        print(f"!! ABORT: store aggregation sums to {agg_sum} but vendor total_jobs is {stated_total} "
              f"- the aggregation is capped/inconsistent, so some WA stores would be missed. Not "
              f"enumerating a partial board. Re-derive the aggregation shape.")
        log(tenant, "index_abort", detail=f"agg_sum {agg_sum} != total_jobs {stated_total}",
            agg_sum=agg_sum, total_jobs=stated_total)
        return 1

    all_jobs, shortfalls = {}, []
    try:
        for i, s in enumerate(stores, 1):
            sn = s.get("storeNumber")
            expected = int(s.get("count") or 0)
            got = _enumerate_store(tenant, sn, expected)
            for j in got:
                jid = job_id(j)
                if jid and jid not in all_jobs:
                    all_jobs[jid] = j
            scoped = sum(1 for j in got if in_scope(j, tenant))
            flag = "" if len(got) >= expected else f"  SHORT {len(got)}/{expected}"
            if len(got) < expected:
                shortfalls.append((sn, len(got), expected))
                log(tenant, "store_short", store=sn, city=s.get("city"),
                    got=len(got), expected=expected)
            print(f"  [{i:>2}/{len(stores)}] store {sn} {str(s.get('city'))[:16]:<16} "
                  f"{len(got):>3}/{expected:<3} in-scope {scoped:>2}{flag}")
            time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT: {e}. Partial capture DISCARDED (prior data kept); records.jsonl "
              f"NOT rewritten. Re-run when the source recovers.")
        log(tenant, "index_abort", detail=str(e), captured_before_abort=len(all_jobs))
        return 1

    all_list = list(all_jobs.values())
    scoped_all = [j for j in all_list if in_scope(j, tenant)]
    print(f"\nindex complete: {len(all_list)} distinct captured across {len(stores)} stores "
          f"(agg-sum {agg_sum}), {len(scoped_all)} in scope -> {p['base']}")
    if shortfalls:
        miss = sum(e - g for _s, g, e in shortfalls)
        print(f"  NOTE {len(shortfalls)} store(s) short of their advertised count, {miss} "
              f"record(s) not surfaced (relevance-window overlap on large stores).")

    with open(os.path.join(p["base"], "records.jsonl"), "w", encoding="utf-8") as fh:
        for j in all_list:
            fh.write(json.dumps(j, ensure_ascii=False) + "\n")
    # Anchor the daily completeness guard to the VENDOR total (checked equal to agg_sum above),
    # not agg_sum, so a capped aggregation surfaces as captured < total rather than passing.
    log(tenant, "index", captured=len(all_list), distinct=len(all_list),
        in_scope=len(scoped_all), total=stated_total or agg_sum, stores=len(stores), short=len(shortfalls))
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


# ---------------------------------------------------------------------------
# detail - GET the SSR job page, keep the raw HTML; jobDetails is parsed at normalize time
# ---------------------------------------------------------------------------

def detail_url(job):
    return DETAIL_URL_TMPL.format(pid=job_id(job))


def _next_data(html_text):
    """Return the parsed __NEXT_DATA__ JSON island, or None. Located by string span (the
    id can precede or follow other <script> attributes; a naive regex missed it)."""
    i = (html_text or "").find("__NEXT_DATA__")
    if i < 0:
        return None
    s = html_text.find(">", i) + 1
    e = html_text.find("</script>", s)
    if s <= 0 or e < 0:
        return None
    try:
        return json.loads(html_text[s:e])
    except ValueError:
        return None


def extract_detail(html_text):
    """The detail record fed to map_record: props.pageProps.jobDetails (title, the three
    templated description fields, createdAt, ...). None if the island/path is absent."""
    nd = _next_data(html_text)
    if not nd:
        return None
    try:
        jd = nd["props"]["pageProps"]["jobDetails"]
    except (KeyError, TypeError):
        return None
    return jd if isinstance(jd, dict) else None


def mode_detail(tenant):
    """Fetch detail pages for in-scope records. Resumable. Raw HTML written whole - the
    __NEXT_DATA__ is parsed at normalize time, so a parser change never costs a re-fetch."""
    p = paths(tenant)
    os.makedirs(p["detail"], exist_ok=True)
    unique = in_scope_unique(tenant)
    print(f"in scope, distinct: {len(unique)}")
    done = skipped = failed = no_detail = 0
    for i, job in enumerate(unique, 1):
        out = os.path.join(p["detail"], f"{job_id(job)}.html")
        if os.path.exists(out):
            skipped += 1
            continue
        r = session().get(detail_url(job), timeout=TIMEOUT, **_IMPERSONATE)
        if r.status_code != 200:
            print(f"  [{i}/{len(unique)}] {job_id(job)} status {r.status_code}")
            failed += 1
            log(tenant, "detail_error", id=job_id(job), status=r.status_code)
        else:
            body = r.text
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(body)
            if not extract_detail(body):
                no_detail += 1
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(unique)}] {done} fetched")
        time.sleep(DELAY_SECONDS)
    print(f"\ndetail complete: {done} fetched, {skipped} on disk, {failed} failed")
    print(f"pages with no parsed jobDetails: {no_detail}")
    log(tenant, "detail", scoped=len(unique), fetched=done, skipped=skipped,
        failed=failed, no_detail=no_detail)
    return 0


# ---------------------------------------------------------------------------
# probe / inspect / report
# ---------------------------------------------------------------------------

def mode_probe(tenant):
    """Verify the endpoint, the store aggregation, and that a single-store filter returns that
    store's advertised count EXACTLY (the completeness contract the index depends on)."""
    print(f"tenant : {tenant['key']}  ({tenant.get('label','')})")
    print(f"graphql: {GRAPHQL_URL}")
    print(f"filter : {wa_filter(tenant)}")
    print(f"scope  : {tenant.get('scope')}")
    print()
    try:
        r = search(tenant, wa_filter(tenant), 0)
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
    art = artifact(payload)
    if art is None:
        errs = payload.get("errors") if isinstance(payload, dict) else None
        print(f"FAIL  no jobs artifact. errors={errs}")
        return 1

    jobs = art.get("jobs") or []
    stores = art.get("store_jobs_aggregation_result") or []
    agg_sum = sum(int(s.get("count") or 0) for s in stores)
    print(f"page size (measured) : {len(jobs)}")
    print(f"stated total_jobs    : {art.get('total_jobs')}  (diagnostic only - NOT a stop)")
    print(f"stores in aggregation: {len(stores)}   agg-sum: {agg_sum}")
    scoped = [j for j in jobs if in_scope(j, tenant)]
    print(f"in scope on page 1   : {len(scoped)}/{len(jobs)}")
    if jobs:
        j = jobs[0]
        print(f"\nfirst record: {job_id(j)}  {str(j.get('jobPostingTitle') or j.get('title'))[:60]}")
        print(f"  source={_source_prefix(j)!r} pay={j.get('payFrequency')!r} "
              f"city={j.get('city')!r} state={j.get('state')!r} categories={j.get('categories')!r}")
        print(f"  detail url: {detail_url(j)}")

    # The completeness contract: a single small store must return its whole count in one page.
    if stores:
        small = min(stores, key=lambda s: int(s.get("count") or 0))
        sn, cnt = small.get("storeNumber"), int(small.get("count") or 0)
        time.sleep(DELAY_SECONDS)
        got = _enumerate_store(tenant, sn, cnt)
        ok = len(got) == cnt
        print(f"\nstore-filter check: store {sn} ({small.get('city')}) returned {len(got)}/{cnt} "
              f"-> {'EXACT (per-store enumeration is complete)' if ok else 'MISMATCH - re-derive'}")
        if not ok:
            return 1
    print("\nProbe OK.")
    log(tenant, "probe", status=r.status_code, page1=len(jobs), stores=len(stores),
        agg_sum=agg_sum, stated_total=art.get("total_jobs"))
    return 0


def mode_inspect(tenant):
    """Fetch one in-scope job's detail page and print jobDetails fields + fill.

    Inspect for VALUES, not names - a field that exists but is empty is not a source."""
    r = search(tenant, wa_filter(tenant), 0)
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1
    art = artifact(r.json())
    jobs = [j for j in (art.get("jobs") if art else []) if in_scope(j, tenant)]
    if not jobs:
        print("no in-scope jobs on page 1")
        return 1
    url = detail_url(jobs[0])
    print(f"index record fields ({len(jobs[0])}): {', '.join(sorted(jobs[0]))}\n")
    print(f"detail: {url}\n")
    time.sleep(DELAY_SECONDS)
    d = session().get(url, timeout=TIMEOUT, **_IMPERSONATE)
    print(f"status {d.status_code}, {len(d.content)} bytes\n")
    if d.status_code != 200:
        return 1
    jd = extract_detail(d.text)
    if not jd:
        print("NO jobDetails parsed from __NEXT_DATA__. The parse assumption is wrong -")
        print("stop and re-derive before running --detail.")
        return 1
    print("DETAIL FIELDS (props.pageProps.jobDetails)\n")
    for k in sorted(jd):
        v = jd[k]
        s = v if isinstance(v, str) else json.dumps(v)
        filled = "FILLED " if s and s.strip() and s not in ("null", "[]", "{}") else "EMPTY  "
        print(f"  {filled}{k:24} len={len(s):>6}  {s[:70]!r}")
    return 0


def mode_report(tenant):
    p = paths(tenant)
    recs = load_records(tenant) if os.path.exists(
        os.path.join(p["base"], "records.jsonl")) else []
    scoped = [j for j in recs if in_scope(j, tenant)]
    details = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant           : {tenant['key']}")
    print(f"location filter  : {tenant.get('location_filter')}")
    print(f"scope            : {tenant.get('scope')}")
    print(f"records captured : {len(recs)}")
    print(f"in scope         : {len(scoped)}")
    print(f"detail on disk   : {details}")
    print(f"raw path         : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - Walmart index record + detail jobDetails -> normalized contract
#
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Every Walmart field name lives
# in map_record. The requirement EXTRACTOR is not here - that is normalize.experience, shared,
# driven by this tenant's forked openers (headingless: absent_barrier_is_none_needed) in config.
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
    """employmentTypes is a list (["Part time"]); normalize to a clean label."""
    if isinstance(v, list):
        v = v[0] if v else None
    if not v:
        return None
    key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
    return _EMP_TYPE.get(key, str(v).strip().title())


def _title_case_city(city):
    c = (city or "").strip()
    return c.title() if c and c.isupper() else (c or None)


def _iso_date(ms_or_iso):
    """posted_at is a timestamptz column - emit a real ISO date (YYYY-MM-DD) or None, NEVER a
    raw passthrough (a bad value 22007-rejects the whole upsert). Index carries an epoch-ms
    int (jobPostingStartDate); detail carries an ISO createdAt."""
    if ms_or_iso is None or ms_or_iso == "":
        return None
    if isinstance(ms_or_iso, (int, float)):
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(ms_or_iso) / 1000.0))
        except (ValueError, OverflowError, OSError):
            return None
    s = str(ms_or_iso).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _strip_after(text, markers):
    """Truncate at the first configured marker. The 'What you'll do' field ends in a fixed,
    byte-identical Walmart benefits/legal block ('At Walmart, we offer competitive pay ... Live
    Better U ... Programs range from high school completion ...') that has NO bearing on the role
    but reads to the extractor as a required education/credential ('high school ... certificates')
    - it flipped every store job to experience-required (a requirements-span leak). Fencing it
    keeps the genuine role narrative while removing the poison. Data-driven + degrades gracefully:
    an unmatched marker just keeps more prose (the absent-barrier flag still classifies)."""
    if not text or not markers:
        return text
    cut = len(text)
    for m in markers:
        i = text.find(m)
        if 0 <= i < cut:
            cut = i
    return text[:cut].rstrip()


def _assemble_description(jd, strip_after=None):
    """Store roles are templated and HEADINGLESS (no minimumQualification): the three fields
    are Role summary (plain), 'What you'll do' (role narrative + a benefits/legal boilerplate
    tail, fenced by strip_after) and 'What you'll bring' (duties html). Keep the section
    headings so the body reads as a real posting; the extractor runs headingless
    (absent_barrier_is_none_needed) over the whole thing."""
    def block(heading, text):
        if not text or not str(text).strip():
            return None
        t = str(text)
        if "<" not in t:                        # plain text -> wrap so strip_html spacing holds
            t = "<p>" + t + "</p>"
        return f"<h2>{heading}</h2>{t}"
    parts = [
        block("Role summary", jd.get("descriptionSummary")),
        block("What you'll do", _strip_after(jd.get("description"), strip_after)),
        block("What you'll bring", jd.get("additionalDescription")),
    ]
    parts = [p for p in parts if p]
    return "\n".join(parts) if parts else None


def map_record(job, jd, t, retrieved_at):
    """Walmart index record (job) + detail jobDetails (jd) -> normalized contract."""
    r = model.new_record()
    warnings = []
    jd = jd or {}

    r["source_id"] = PLATFORM
    r["source_job_id"] = job_id(job)
    r["company_name"] = job.get("brand") or jd.get("brand") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = job.get("jobPostingTitle") or job.get("title") or jd.get("title")

    desc = _assemble_description(jd, t.get("description_strip_after"))
    if not desc:
        warnings.append("no jobDetails description on detail page")
    r["description_html"] = desc
    r["description_text"] = strip_html(desc)
    # Store roles carry NO minimumQualification (headingless by construction); leave the
    # segmented qualifications field empty - the openers/absent-barrier flag sectionize
    # description_html at enrich time.
    r["qualifications"] = []
    r["qualifications_html"] = None

    city = job.get("city")
    state = _state_code(job.get("state"))
    r["city"] = _title_case_city(city)
    r["state"] = state
    if job.get("state") and not state:
        warnings.append(f"state did not resolve: {job.get('state')!r}")
    loc_bits = [b for b in (r["city"], state) if b]
    r["location_raw"] = ", ".join(loc_bits) if loc_bits else None
    r["lat"] = job.get("latitude")
    r["lng"] = job.get("longitude")

    r["employment_type"] = _emp_type(job.get("employmentTypes") or jd.get("employmentTypes"))
    r["shift_raw"] = None
    r["posted_at"] = _iso_date(job.get("jobPostingStartDate")) or _iso_date(jd.get("createdAt"))
    r["freshness_state"] = "UNKNOWN"

    # Pay is a stated hourly range on the index record (minPay/maxPay + payFrequency: "Hourly").
    lo, hi = job.get("minPay"), job.get("maxPay")
    if (lo or hi) and str(job.get("payFrequency", "")).lower() == "hourly":
        r["salary_min"] = float(lo) if lo is not None else None
        r["salary_max"] = float(hi) if hi is not None else None
        r["salary_is_stated"] = True
        r["pay_period"] = "HOURLY"

    r["apply_url"] = detail_url(job)            # the SSR job page carries the Apply action
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    cats = job.get("categories")
    if isinstance(cats, list) and cats:
        r["source_category"] = str(cats[0]).strip() or None
    elif isinstance(cats, str):
        r["source_category"] = cats.strip() or None
    r["source_function"] = None

    r["source_url"] = detail_url(job)
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    return r, warnings


def mode_normalize(t):
    """Map captured records + their detail jobDetails into the contract. Derived fields
    (experience_condition, credentials, ...) are left empty BY DESIGN - normalize.enrich fills
    them with the shared extractor and this tenant's forked openers."""
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
        jd = None
        if os.path.exists(detail_file):
            with open(detail_file, "r", encoding="utf-8") as fh:
                jd = extract_detail(fh.read())
        if not jd:
            no_detail += 1
        rec, w = map_record(job, jd, t, retrieved)
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
    ap = argparse.ArgumentParser(description="Walmart careers-site adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify graphql endpoint + per-store completeness")
    g.add_argument("--inspect", action="store_true", help="print detail jobDetails fields AND fill")
    g.add_argument("--index", action="store_true", help="enumerate every WA store, union the slices")
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
