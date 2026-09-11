"""
ADP Workforce Now recruiting adapter - No-Experience Job Network.

Ported from the tested reference ./pull_adp.py into this repo's adapter
conventions (structure mirrors adapters/jibe_api.py). STDLIB ONLY - urllib,
html, re, json, argparse, os, sys, time. No curl_cffi, no requests, no bs4.

PLATFORM NAMING - read this before adding a tenant.
Named for the READ SURFACE. What is fetched is the ADP WFN public staffing
search API behind an ADP-hosted career site (myjobs.adp.com/{site}/cx). The
ATS *is* ADP here, but the key still names the fetch shape, not the employer.

SINGLE-CALL SOURCE. The list $select returns jobDescription AND
jobQualifications inline, so there is NO detail fetch on this platform (same
property as Jibe/Compass). One call per page walks the whole board.

THREE UNKNOWNS this adapter is built to tolerate, all surfaced by --probe /
--inspect before --pull:
  1. Envelope key unknown - the row list may sit under jobRequisitions,
     requisitions, items, value, results, data, or a novel key. unwrap() tries
     the known keys then falls back to the first list-of-objects.
  2. Location shapes unknown - workLocations AND requisitionLocations are both
     selected and may differ (string / list-of-strings / nested nameCode+
     address). loc_strings() flattens all of them defensively.
  3. Tenant scoping UNRESOLVED - nothing in the URL names Gensco and $filter is
     empty, so scoping must arrive via header/cookie. Config carries a
     headers.Referer guess and a note flagging the headers as uncaptured.
     --probe PRINTS returned titles+locations so a wrong scope is caught on
     sight. Headers are NEVER hardcoded in code - they are read from config.

Usage:
  py -m adapters.adp_wfn --tenant gensco --probe
  py -m adapters.adp_wfn --tenant gensco --inspect
  py -m adapters.adp_wfn --tenant gensco --pull
  py -m adapters.adp_wfn --tenant gensco --normalize
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "adp_wfn")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "adp_wfn"
UA = "noprobjobs-pull/1.0 (+https://noprobjobs.com)"
TAG = re.compile(r"<[^>]+>")

# Response envelope varies by ADP endpoint. Try these in order, then fall back
# to the first list-of-objects. inspect/probe print which key was found.
LIST_KEYS = ["jobRequisitions", "requisitions", "items", "value", "results", "data"]

# Full state name -> two-letter code, so `state` reads the same across sources.
# Fixed US reference data, forked per the no-shared-code rule (Finding 42).
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


# ---------------------------------------------------------------------------
# tenant / paths / log  (structure mirrors adapters/jibe_api.py)
# ---------------------------------------------------------------------------

def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        known = ", ".join(k for k in tenants if not k.startswith("_"))
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH} under '{PLATFORM}'. Known: {known}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {
        "base": base,
        "records": os.path.join(base, "records.jsonl"),
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
# fetch - ported from pull_adp.py get(): 5xx/429 retry with backoff, plus a
# non-JSON body detector (a 200 with a non-JSON body means unauthorized /
# unscoped, a HARD failure, never written as data).
# ---------------------------------------------------------------------------

def headers_from(tenant):
    """Read request headers from config. Headers are NEVER hardcoded here -
    scoping (Referer/Cookie/Origin/bearer) lives in config so it is data, not
    code. The 'note' key is documentation, not a header."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    for k, v in (tenant.get("headers") or {}).items():
        if k == "note" or not isinstance(v, str):
            continue
        h[k] = v
    return h


def bootstrap_headers(tenant, hdrs):
    """If the tenant declares a token_bootstrap, GET that PUBLIC endpoint, read
    the named field, and inject it as a request header.

    ADP WFN mints a session token (myJobsToken) from a public career-site call
    (no login, no cookies); the staffing search/apply API returns HTTP 400
    without it. This is the 'scoping arrives via header' unknown, now resolved:
    the token is fetched fresh each run (it is session-scoped, so it is never
    hardcoded), and the url + token_field + header name all come from config, so
    this stays generic data, not code. Returns a mutated COPY of hdrs; raises
    RuntimeError on a failed/empty bootstrap (a scope failure is never silently
    swallowed into an unscoped request)."""
    tb = tenant.get("token_bootstrap")
    if not tb:
        return hdrs
    payload = get(tb["url"], {"User-Agent": UA, "Accept": "application/json"})
    field = tb.get("token_field", "myJobsToken")
    token = dig(payload, field) if isinstance(payload, dict) else None
    if not token or not isinstance(token, str):
        raise RuntimeError(
            f"token_bootstrap {tb['url']} returned no '{field}' - cannot scope "
            f"the request (got keys: {sorted(payload)[:12] if isinstance(payload, dict) else type(payload).__name__})")
    out = dict(hdrs)
    out[tb.get("header", "myJobsToken")] = token
    return out


def get(url, hdrs, retries=4, backoff=3):
    """Ported from pull_adp.py. Returns parsed JSON, or raises RuntimeError on a
    persistent failure or a non-JSON body (unauthorized/unscoped)."""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"{url} -> non-JSON response ({len(body)} bytes). "
                        f"Usually means the request was not authorized or scoped. "
                        f"First 200 chars: {body[:200]!r}")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"{url} -> {last}")
        except RuntimeError:
            raise
        except Exception as e:
            last = str(e)
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"{url} -> gave up after {retries}: {last}")


def list_url(tenant, skip):
    """Build the list URL with the $skip cursor. safe='$,/:'-preserves the
    OData $-prefixed param names through urlencode."""
    lr = tenant["list_request"]
    p = dict(lr["params"])
    p["$top"] = lr["page_size"]
    if skip:
        p[lr["pagination"]["cursor_param"]] = skip
    return tenant["endpoints"]["list"] + "?" + urllib.parse.urlencode(p, safe="$,/:")


# ---------------------------------------------------------------------------
# parsing - PURE functions on plain dicts, so tests run on fixtures with no
# network. Ported verbatim in spirit from pull_adp.py.
# ---------------------------------------------------------------------------

def unwrap(payload):
    """Find the row list inside whatever envelope came back. Known keys first,
    then the first list-of-objects. Returns (rows, key_name)."""
    if isinstance(payload, list):
        return payload, "<root list>"
    if not isinstance(payload, dict):
        return [], "<unknown>"
    for k in LIST_KEYS:
        v = payload.get(k)
        if isinstance(v, list):
            return v, k
    for k, v in payload.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v, k
    return [], "<none found>"


def dig(obj, path):
    """Dotted-path lookup. Returns None if any segment is missing."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def to_text(s):
    """HTML/entity -> clean text. Tolerates dicts carrying text/value."""
    if not s:
        return None
    if isinstance(s, dict):
        s = s.get("text") or s.get("value") or json.dumps(s)
    s = re.sub(r"<br\s*/?>", "\n", str(s), flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6])>", "\n", s, flags=re.I)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return "\n".join(l.strip() for l in s.split("\n")).strip()


def loc_strings(row):
    """workLocations / requisitionLocations shapes are unknown. Flatten anything
    stringy across: bare string, list-of-strings, and nested objects carrying
    nameCode / address / locationName / name (with an address sub-object of
    shortName / cityName / countrySubdivisionLevel1 / city / state / postalCode,
    each possibly a {codeValue} wrapper). Deduped, order preserved."""
    out = []
    for key in ("workLocations", "requisitionLocations"):
        v = row.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    for k in ("nameCode", "address", "locationName", "name"):
                        sub = item.get(k)
                        if isinstance(sub, str):
                            out.append(sub)
                        elif isinstance(sub, dict):
                            bits = [sub.get(x) for x in
                                    ("shortName", "cityName", "countrySubdivisionLevel1",
                                     "city", "state", "postalCode")]
                            bits = [b.get("codeValue") if isinstance(b, dict) else b for b in bits]
                            bits = [b for b in bits if isinstance(b, str)]
                            if bits:
                                out.append(", ".join(dict.fromkeys(bits)))
    return list(dict.fromkeys(out))


_DATE_LEAD = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


def parse_posted(value):
    """postingDate -> a string posted_at if it leads with an ISO date, else the
    raw string if it is a non-empty scalar, else None. Kept as text: the
    contract stores posted_at verbatim and freshness is computed downstream."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def location_state(loc):
    """Resolve a single flattened location string to a two-letter state code, or
    None. Scans comma-parts for a full state name OR a standalone uppercase
    two-letter code (a bare 'WA' or the 'WA 98402' ZIP tail). isupper() gates out
    lowercase city false positives ('Or'lando, 'In'dependence)."""
    if not isinstance(loc, str):
        return None
    for part in loc.split(","):
        p = part.strip()
        if not p:
            continue
        if p.lower() in US_STATE_TO_CODE:
            return US_STATE_TO_CODE[p.lower()]
        for tok in p.split():
            if len(tok) == 2 and tok.isupper() and tok in _STATE_CODES:
                return tok
    return None


def row_in_state(row, state_code):
    """True if ANY of a row's flattened locations resolves to state_code. A
    multi-site posting with at least one WA location is in-market."""
    if not state_code:
        return True
    for loc in loc_strings(row):
        if location_state(loc) == state_code:
            return True
    return False


def geo_scope_ok(tenant):
    """--pull may run only with a VERIFIED geo scope OR an explicit small-board
    exemption. Pure predicate so the guard is testable without a network call."""
    gs = tenant.get("geo_scope") or {}
    return bool(gs.get("verified") or gs.get("exempt"))


def parse_city_state(location_raw):
    """Parse a clean 'City, ST' or 'City, Full State' tail into (city, state).
    Conservative: only fills when the last comma-part resolves to a US state,
    else (None, None). Never guesses a city that is actually a street address."""
    if not isinstance(location_raw, str) or "," not in location_raw:
        return None, None
    parts = [p.strip() for p in location_raw.split(",") if p.strip()]
    if len(parts) < 2:
        return None, None
    # state may be the last part, or the 2nd of a 'City, ST ZIP' tail
    tail = parts[-1]
    state = None
    m = re.match(r"^([A-Za-z]{2})\b", tail)
    if m and m.group(1).upper() in _STATE_CODES:
        state = m.group(1).upper()
    elif tail.lower() in US_STATE_TO_CODE:
        state = US_STATE_TO_CODE[tail.lower()]
    if not state:
        return None, None
    city = parts[-2] if len(parts) >= 2 else None
    return (city or None), state


# ---------------------------------------------------------------------------
# mapping - ADP WFN requisition -> normalized contract. Every ADP field name
# lives here. No experience extraction, no classification (those are left at
# new_record() defaults for normalize.enrich).
# ---------------------------------------------------------------------------

def map_record(row, tenant, retrieved_at):
    """One ADP requisition dict -> a contract record (pre seen-state). Pure."""
    fm = tenant.get("field_map", {})
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    r["source_job_id"] = dig(row, fm.get("source_job_id", "reqId"))
    r["company_name"] = tenant.get("employer_name") or tenant.get("label")
    r["employer_domain"] = tenant.get("employer_domain")

    r["title"] = (dig(row, fm.get("title", "publishedJobTitle"))
                  or dig(row, fm.get("internal_title", "jobTitle")))

    desc = to_text(dig(row, fm.get("description_html", "jobDescription")))
    qual = to_text(dig(row, fm.get("qualifications_html", "jobQualifications")))
    # jobQualifications is its OWN field, not a heading inside the description.
    # Keep it separate (qualifications_html for the extractor) AND fold it into
    # description_text so the plain-text body carries the requirements too.
    r["description_html"] = dig(row, fm.get("description_html", "jobDescription"))
    r["description_text"] = "\n\n".join(x for x in (desc, qual) if x) or None
    r["qualifications"] = []
    r["qualifications_html"] = dig(row, fm.get("qualifications_html", "jobQualifications")) or None

    locs = loc_strings(row)
    r["location_raw"] = locs[0] if locs else None
    city, state = parse_city_state(r["location_raw"])
    r["city"] = city
    r["state"] = state

    r["employment_type"] = (to_text(dig(row, fm.get("employment_type", "type")))
                            or to_text(dig(row, fm.get("work_level", "workLevelCode"))))
    r["posted_at"] = parse_posted(dig(row, fm.get("posted_text", "postingDate")))
    r["freshness_state"] = "UNKNOWN"

    listing = tenant.get("endpoints", {}).get("listing_page")
    r["apply_url"] = listing
    r["apply_class"] = tenant.get("apply_class")
    r["source_class"] = tenant.get("source_class", "direct-employer")

    r["market"] = tenant.get("market")
    r["source_url"] = listing
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = tenant.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    model.order_salary(r)
    return r, warnings


def normalize_record(row, tenant, retrieved_at, now, seen_state):
    """Full pipeline step: map -> apply seen-state -> is_new. Mirrors
    jibe_api.mode_normalize's inner loop so a record reaches model.validate()
    well-formed (first_seen/last_seen set). Pure; tests drive it on fixtures."""
    rec, warnings = map_record(row, tenant, retrieved_at)
    known_before = len(seen_state)
    model.apply_seen_state(rec, seen_state, now)
    rec["is_new"] = True if known_before == 0 else rec["first_seen"] == now
    return rec, warnings


# ---------------------------------------------------------------------------
# gate: probe
# ---------------------------------------------------------------------------

def mode_probe(tenant):
    """Fetch page 1 and page 2 (via $skip). Print the envelope key, rows, the
    first ~5 titles+locations (so a wrong tenant scope is visible on sight), and
    whether the cursor is honored (zero overlap between pages)."""
    hdrs = headers_from(tenant)
    url = list_url(tenant, 0)
    print(f"tenant       : {tenant['key']}  ({tenant.get('label','')})")
    print(f"list endpoint: {url}\n")

    note = (tenant.get("headers", {}).get("note") or "").lower()
    if "not yet captured" in note or "uncaptured" in note or "guess" in note:
        print("WARNING: config still flags headers as UNCAPTURED. If scoping lives in a")
        print("header or cookie, this call may return the WRONG tenant or nothing.\n")

    try:
        hdrs = bootstrap_headers(tenant, hdrs)
    except RuntimeError as e:
        print(f"FAIL token bootstrap: {e}")
        return 1
    if tenant.get("token_bootstrap"):
        print(f"token bootstrap: {tenant['token_bootstrap']['url']} -> "
              f"{tenant['token_bootstrap'].get('header','myJobsToken')} injected\n")

    try:
        payload = get(url, hdrs)
    except RuntimeError as e:
        print(f"FAIL {e}")
        return 1

    rows, key = unwrap(payload)
    print(f"envelope key : {key}")
    print(f"rows returned: {len(rows)} (requested $top={tenant['list_request']['page_size']})")
    if isinstance(payload, dict):
        print(f"envelope keys: {sorted(payload.keys())}")
    if not rows:
        print("\nZero rows. Either the filter excludes everything or the request is unscoped.")
        return 1

    fm = tenant.get("field_map", {})
    tkey = fm.get("title", "publishedJobTitle")
    ikey = fm.get("internal_title", "jobTitle")
    idkey = fm.get("source_job_id", "reqId")
    print("\nfirst 5 rows (CHECK these are this employer's jobs):")
    for row in rows[:5]:
        title = dig(row, tkey) or dig(row, ikey) or ""
        print(f"  {dig(row, idkey)}  {str(title)[:50]}")
        for l in loc_strings(row)[:1]:
            print(f"       {l[:60]}")
    print(f"\nIf those titles/locations are NOT {tenant.get('employer_name','this employer')} jobs,")
    print("the request is NOT scoped: capture the real Request Headers (Cookie, Referer,")
    print("Origin, any bearer/oauth) from the live board's XHR in devtools into headers.\n")

    cur = tenant["list_request"]["pagination"]["cursor_param"]
    size = tenant["list_request"]["page_size"]
    try:
        p2 = get(list_url(tenant, size), hdrs)
        r2, _ = unwrap(p2)
        ids1 = {dig(r, idkey) for r in rows}
        ids2 = {dig(r, idkey) for r in r2}
        print(f"page 2 via {cur}={size}: {len(r2)} rows | overlap with page 1: "
              f"{len(ids1 & ids2)} (want 0)")
        if ids1 and ids1 == ids2:
            print(f"  {cur} is being IGNORED. Find the real pagination parameter before --pull.")
    except RuntimeError as e:
        print(f"page 2 failed: {e}")
    return 0


# ---------------------------------------------------------------------------
# gate: inspect
# ---------------------------------------------------------------------------

def mode_inspect(tenant):
    """Fetch page 1. Print the envelope key, row keys, field_map resolution,
    BOTH raw location shapes + the flattened result, and the jobQualifications
    length + first lines."""
    hdrs = headers_from(tenant)
    try:
        hdrs = bootstrap_headers(tenant, hdrs)
        payload = get(list_url(tenant, 0), hdrs)
    except RuntimeError as e:
        print(f"FAIL {e}")
        return 1
    rows, key = unwrap(payload)
    if not rows:
        print("no rows returned")
        return 1
    row = rows[0]
    print(f"envelope key: {key}\nrow keys: {sorted(row.keys())}\n")

    print("field_map resolution:")
    for contract, path in tenant.get("field_map", {}).items():
        v = dig(row, path)
        kind = type(v).__name__
        prev = to_text(v)
        prev = (prev[:45] if isinstance(prev, str) else "") if v is not None else ""
        prev = prev if isinstance(v, (str,)) else (f"<{kind}>" if v is not None else "")
        print(f"  {'OK  ' if v not in (None, '') else 'MISS'} {contract:<22} <- {path:<22} {prev}")

    print("\nlocation shapes (both are selected and MAY differ):")
    for k in ("workLocations", "requisitionLocations"):
        print(f"  {k}: {json.dumps(row.get(k))[:200]}")
    print(f"  flattened -> {loc_strings(row)}")

    qkey = tenant.get("field_map", {}).get("qualifications_html", "jobQualifications")
    qual = to_text(dig(row, qkey))
    print(f"\njobQualifications ({qkey}): {len(qual) if qual else 0} chars")
    if qual:
        print("  first 300:")
        for line in qual[:300].split("\n"):
            print(f"    {line}")
    return 0


# ---------------------------------------------------------------------------
# gate: pull  (single-call source - no detail fetch)
# ---------------------------------------------------------------------------

def mode_pull(tenant, max_pages=500):
    """Walk list pages by $skip, dedupe on reqId, BUFFER in memory, and write
    records.jsonl only after every page succeeded.

    On a PERSISTENT list failure after retries, get() raises RuntimeError: we
    ABORT before the write (repo hard rule - never write a partial capture as
    complete) and return non-zero so run_pull marks the source FAILED. A
    non-JSON body is a hard failure inside get(), not data.

    GEO-SCOPE GUARD (hard rule): refuse to run unless the config carries a
    verified geo scope OR an explicit small-board exemption. Gensco passes via
    geo_scope.exempt. EXEMPT is exempt from the SERVER-scope requirement ONLY -
    a client-side WA filter still runs on every returned page below, because
    Gensco's scoping is a header (unknown), so client-filtering to `state` is the
    only thing that guarantees in-market rows."""
    if not geo_scope_ok(tenant):
        print("!! REFUSING --pull: no verified geo scope and not marked exempt.")
        return 1

    hdrs = headers_from(tenant)
    try:
        hdrs = bootstrap_headers(tenant, hdrs)
    except RuntimeError as e:
        print(f"!! ABORT: token bootstrap failed: {e}. records.jsonl NOT rewritten.")
        log(tenant, "pull_abort", detail=f"token bootstrap: {e}")
        return 1
    rl = tenant.get("rate_limit", {})
    rps = rl.get("requests_per_second", 1)
    delay = 1.0 / rps if rps else 1.0
    retries = rl.get("max_retries", 4)
    backoff = rl.get("backoff_seconds", 3)
    size = tenant["list_request"]["page_size"]
    idkey = tenant.get("field_map", {}).get("source_job_id", "reqId")
    state = tenant.get("state")

    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)

    seen, buffered, skip, dropped = set(), [], 0, 0
    try:
        for _ in range(max_pages):
            payload = get(list_url(tenant, skip), hdrs, retries, backoff)
            rows, _key = unwrap(payload)
            # Dedupe + termination run on RAW rows so an all-out-of-state page
            # advances the cursor instead of ending the crawl. The client-side
            # geo filter only decides what gets BUFFERED - it runs even though
            # the board is scope-exempt (exempt = server-scope only).
            fresh = [r for r in rows if dig(r, idkey) not in seen]
            if not fresh:
                break
            for r in fresh:
                seen.add(dig(r, idkey))
                if state and not row_in_state(r, state):
                    dropped += 1
                    continue
                buffered.append(r)
            print(f"  {len(buffered)} in-state rows (skip {skip})", file=sys.stderr)
            skip += size
            time.sleep(delay)
    except RuntimeError as e:
        # Persistent failure or non-JSON body. Discard everything captured this
        # run - the write below is skipped by returning here.
        print(f"\n!! ABORT: {e}. Partial capture DISCARDED; records.jsonl NOT rewritten. "
              f"Re-run when the source recovers (or capture headers if it is a scope failure).")
        log(tenant, "pull_abort", detail=str(e), captured_before_abort=len(buffered))
        return 1

    with open(p["records"], "w", encoding="utf-8") as fh:
        for r in buffered:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(buffered)} records -> {p['records']}")
    if state:
        print(f"client-side {state} filter: dropped {dropped} non-{state} rows")
    log(tenant, "pull", records=len(buffered), dropped_out_of_state=dropped,
        state_filter=state, tz=tenant["list_request"]["params"].get("tz"))
    return 0


# ---------------------------------------------------------------------------
# gate: normalize
# ---------------------------------------------------------------------------

def load_records(tenant):
    f = paths(tenant)["records"]
    if not os.path.exists(f):
        sys.exit("no records.jsonl on disk - run --pull first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_normalize(tenant):
    """raw records -> contract records -> out/adp_wfn/<tenant>/normalized.jsonl.
    Derived fields (experience_condition, category, credentials, evidence) are
    left at new_record() defaults BY DESIGN - normalize.enrich fills them."""
    recs = load_records(tenant)
    out_dir = os.path.join(ROOT, "out", PLATFORM, tenant["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    src = paths(tenant)["records"]
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(src)))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)

    mapped, invalid, warns = [], [], []
    for row in recs:
        rec, w = normalize_record(row, tenant, retrieved, now, seen_state)
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
    print("\nFILL RATE\n")
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
    log(tenant, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="ADP Workforce Now adapter - stdlib only, single-call source")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true",
                   help="fetch page 1+2, print envelope key, titles/locations, cursor proof")
    g.add_argument("--inspect", action="store_true",
                   help="fetch page 1, print field_map + both location shapes + qualifications")
    g.add_argument("--pull", action="store_true",
                   help="walk $skip pages, dedupe on reqId, write records.jsonl (abort on failure)")
    g.add_argument("--normalize", action="store_true",
                   help="map captured records into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "pull", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
