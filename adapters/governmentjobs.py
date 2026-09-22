"""
GovernmentJobs.com (NEOGOV) careers-site adapter - No-Experience Job Network.

SCOPE: fetch and write raw HTML/JSON to disk. Nothing else. No field mapping beyond
map_record, no dedupe logic, no experience typing (that is normalize.experience, shared).

PLATFORM NAMING - read before adding a tenant. The public careers portal at
www.governmentjobs.com/careers/<agency> is NEOGOV's applicant board. Verified by direct
fetch 2026-09-22: the job list is client-rendered - the page HTML says "0 jobs found" and
carries no job rows; the real feed is an AJAX call:

    GET https://www.governmentjobs.com/careers/home/index?agency=<slug>&page=<N>
        &sort=PostingDate&isDescendingSort=true
    Header: X-Requested-With: XMLHttpRequest   <-- REQUIRED. Without it the server returns
                                                   the full empty page shell, not the fragment.

-> an HTML fragment of 10 job rows per page. Paginate until a genuinely empty page (page 99
returns 0). The visible "N jobs found" total is a DIAGNOSTIC ONLY, never a stop condition
(invariant 3). Detail pages are server-rendered at /careers/<slug>/jobs/<id>/<slug> and carry
a JSON-LD JobPosting block - the canonical body the extractor sections.

"governmentjobs" is the key because that is the host. This adapter is built against ONE fetch
shape (the AJAX index + JSON-LD detail above); any employer whose shape differs gets --probe
run first and its own platform key. The agency slug is the ONLY per-tenant difference, so the
index URL is derived from the tenant key (== slug) and probe/inspect run before any config.

Usage:
  python3 -m adapters.governmentjobs --tenant seattle --probe
  python3 -m adapters.governmentjobs --tenant seattle --inspect
  python3 -m adapters.governmentjobs --tenant seattle --index
  python3 -m adapters.governmentjobs --tenant seattle --detail
  python3 -m adapters.governmentjobs --tenant seattle --report
  python3 -m adapters.governmentjobs --tenant seattle --normalize
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
RAW_ROOT = os.path.join(ROOT, "raw", "governmentjobs")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

PLATFORM = "governmentjobs"
CAREERS_BASE = "https://www.governmentjobs.com"
INDEX_ENDPOINT = CAREERS_BASE + "/careers/home/index"
PAGE_SIZE = 10          # observed, not configured server-side
DELAY_SECONDS = 1.0
MAX_PAGES = 800         # safety stop, not a business rule
TIMEOUT = 45

# JSON-LD blocks on the detail page.
_LDJSON = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
# Vendor "N jobs found" total - diagnostic only, never a stop condition (invariant 3).
_TOTAL = re.compile(r'([\d,]+)\s+jobs?\s+found', re.I)


def _job_href_rx(agency):
    """Detail links in the fragment: /careers/<agency>/jobs/<id>/<slug>. The numeric
    id is the stable identifier; the slug is cosmetic."""
    return re.compile(r'href="(/careers/' + re.escape(agency) + r'/jobs/(\d+)/[a-z0-9\-]+)"', re.I)


def load_tenant(name):
    """Config entry if present; otherwise a DERIVED stub (agency == key). The derived
    stub lets --probe/--inspect run before the tenant is written to config - the index
    URL depends only on the slug, so the read-surface GATEs need no config. index/detail/
    normalize still want a real entry (employer_domain, scope_states, openers)."""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name in tenants and isinstance(tenants[name], dict):
        t = dict(tenants[name])
    else:
        t = {"_derived": True, "label": name, "agency": name}
    t["key"] = name
    t.setdefault("agency", name)
    return t


def headers(ajax=False):
    h = {
        "accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "accept-language": "en-US,en;q=0.9",
    }
    if ajax:
        h["x-requested-with"] = "XMLHttpRequest"
        h["accept"] = "text/html, */*; q=0.01"
    return h


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {
        "base": base,
        "index": os.path.join(base, "index"),
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


def get(url, ajax=False):
    return http.get(url, headers=headers(ajax), timeout=TIMEOUT, **_IMPERSONATE)


def decoded_text(r):
    """Decode from the DECLARED charset - a guessed charset put U+FFFD into
    "driver's license" on another board and defeated the credential allowlist."""
    ctype = ""
    try:
        ctype = r.headers.get("content-type", "") or ""
    except Exception:
        ctype = ""
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    enc = m.group(1) if m else None
    if not enc:
        head = r.content[:4096].decode("ascii", "ignore")
        mm = re.search(r'<meta[^>]+charset=["\']?([\w-]+)', head, re.I)
        enc = mm.group(1) if mm else "utf-8"
    try:
        return r.content.decode(enc, "strict")
    except (LookupError, UnicodeDecodeError):
        return r.content.decode("utf-8", "replace")


def index_url(tenant, page):
    """The AJAX index endpoint for one page. Sort is PostingDate desc - stable and it
    paginates (verified); a complete crawl doesn't depend on the order."""
    return (f"{INDEX_ENDPOINT}?agency={tenant['agency']}&page={page}"
            f"&sort=PostingDate&isDescendingSort=true")


def extract_rows(html, agency):
    """One row per distinct job detail link in the fragment. The numeric id is the
    stable identifier and the detail-page filename."""
    rows, seen = [], set()
    for m in _job_href_rx(agency).finditer(html or ""):
        href, jid = m.group(1), m.group(2)
        if jid in seen:
            continue
        seen.add(jid)
        rows.append({"href": href, "internal_id": jid})
    return rows


def in_scope(row, tenant):
    """No row-level filter - these are single-agency WA boards, and out-of-area rows are
    dropped at normalize by scope_states against the JSON-LD state (which parses reliably),
    the same tolerance the Chipotle/radancy path uses. Kept as a hook for symmetry."""
    return True


def mode_probe(tenant):
    """Verify the AJAX index answers, paginates, and stops on a real empty page."""
    url = index_url(tenant, 1)
    print(f"tenant   : {tenant['key']}  ({tenant.get('label','')})"
          + ("   [config: DERIVED stub]" if tenant.get("_derived") else ""))
    print(f"agency   : {tenant['agency']}")
    print(f"index    : {url}")
    print(f"header   : X-Requested-With: XMLHttpRequest")
    print()
    try:
        r = get(url, ajax=True)
    except Exception as e:
        print(f"FAIL  request raised: {type(e).__name__}: {e}")
        return 1
    print(f"status   : {r.status_code}")
    print(f"bytes    : {len(r.content)}")
    if r.status_code != 200:
        print(r.text[:400])
        return 1

    rows = extract_rows(r.text, tenant["agency"])
    total = _TOTAL.search(r.text)
    print(f"job links: {len(rows)} on page 1")
    print(f"stated total : {total.group(1) if total else 'not found'}  (diagnostic only)")
    if rows:
        print(f"first link  : {rows[0]['href']}")

    # page 2 must advance, and a far page must be empty (not a repeating tail).
    if len(rows) >= PAGE_SIZE:
        time.sleep(DELAY_SECONDS)
        r2 = get(index_url(tenant, 2), ajax=True)
        rows2 = extract_rows(r2.text, tenant["agency"]) if r2.status_code == 200 else []
        same = {x["internal_id"] for x in rows} == {x["internal_id"] for x in rows2}
        print(f"\npage 2 status {r2.status_code}, {len(rows2)} links, identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - &page=N is not advancing. Stop and re-derive.")
            return 1
        time.sleep(DELAY_SECONDS)
        r99 = get(index_url(tenant, 99), ajax=True)
        rows99 = extract_rows(r99.text, tenant["agency"]) if r99.status_code == 200 else []
        print(f"page 99 status {r99.status_code}, {len(rows99)} links (expect 0 - real empty page)")
        if rows99:
            print("  WARNING - a far page is non-empty; verify the empty-page stop before --index.")

    print("\nProbe OK." if rows else "\nProbe returned 0 links - re-check the agency slug / header.")
    log(tenant, "probe", status=r.status_code, page1_links=len(rows),
        stated_total=total.group(1) if total else None)
    return 0 if rows else 1


def mode_inspect(tenant):
    """Print the JSON-LD JobPosting fields from one detail page. Inspect for VALUES
    (fill), not just names - a field can exist and be empty on one agency."""
    r = get(index_url(tenant, 1), ajax=True)
    if r.status_code != 200:
        print(f"index status {r.status_code}")
        return 1
    rows = extract_rows(r.text, tenant["agency"])
    if not rows:
        print("no job links on page 1")
        return 1

    job_url = CAREERS_BASE + rows[0]["href"]
    print(f"job: {job_url}\n")
    time.sleep(DELAY_SECONDS)
    d = get(job_url)
    print(f"status {d.status_code}, {len(d.content)} bytes\n")
    if d.status_code != 200:
        return 1

    found = 0
    for block in _LDJSON.finditer(d.text):
        try:
            obj = json.loads(block.group(1).strip())
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            found += 1
            print("JOBPOSTING FIELDS\n")
            for k in sorted(obj):
                v = obj[k]
                s = v if isinstance(v, str) else json.dumps(v)
                filled = "FILLED " if s and s.strip() else "EMPTY  "
                print(f"  {filled}{k:24} len={len(s):>6}  {s[:90]!r}")
    if not found:
        print("NO JobPosting JSON-LD found. The detail parse assumption is wrong -")
        print("stop and re-derive before running --detail.")
        return 1
    return 0


def mode_index(tenant):
    """Paginate the AJAX board. Stop on a genuinely empty page, never on a total."""
    p = paths(tenant)
    os.makedirs(p["index"], exist_ok=True)
    seen, page, rows_all = 0, 1, []
    try:
        while page <= MAX_PAGES:
            url = index_url(tenant, page)
            r = fetch_paged(lambda: get(url, ajax=True), label=f"page {page}: ")
            rows = extract_rows(r.text, tenant["agency"])
            if not rows:
                print(f"empty page at {page} - done")
                break
            with open(os.path.join(p["index"], f"page_{page:04d}.html"), "w",
                      encoding="utf-8") as fh:
                fh.write(r.text)
            rows_all.extend(rows)
            seen += len(rows)
            print(f"  page {page:>4}  +{len(rows):>3}  running {seen}")
            page += 1
            time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT: {e}. Partial capture DISCARDED (prior data kept); rows.jsonl "
              f"NOT rewritten. Re-run when the source recovers.")
        log(tenant, "index_abort", detail=str(e), captured_before_abort=seen)
        return 1

    ids = {x["internal_id"] for x in rows_all}
    print(f"\nindex complete: {seen} links, {len(ids)} distinct -> {p['index']}")
    if len(ids) != seen:
        print(f"  NOTE {seen - len(ids)} duplicate links across pages.")
    with open(os.path.join(p["base"], "rows.jsonl"), "w", encoding="utf-8") as fh:
        for x in rows_all:
            fh.write(json.dumps(x) + "\n")
    log(tenant, "index", captured=seen, distinct=len(ids), pages=page - 1)
    return 0


def load_rows(tenant):
    f = os.path.join(paths(tenant)["base"], "rows.jsonl")
    if not os.path.exists(f):
        sys.exit("no rows.jsonl on disk - run --index first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_detail(tenant):
    """Fetch detail pages for in-scope rows. Resumable. Raw HTML written whole so a
    parser change never costs a re-fetch."""
    p = paths(tenant)
    os.makedirs(p["detail"], exist_ok=True)
    rows = load_rows(tenant)
    scoped, seen_ids, unique = [x for x in rows if in_scope(x, tenant)], set(), []
    for x in scoped:
        if x["internal_id"] not in seen_ids:
            seen_ids.add(x["internal_id"])
            unique.append(x)
    print(f"rows: {len(rows)}, in scope {len(scoped)}, distinct {len(unique)}")

    done = skipped = failed = no_ld = 0
    for i, row in enumerate(unique, 1):
        out = os.path.join(p["detail"], f"{row['internal_id']}.html")
        if os.path.exists(out):
            skipped += 1
            continue
        r = get(CAREERS_BASE + row["href"])
        if r.status_code != 200:
            print(f"  [{i}/{len(unique)}] {row['internal_id']} status {r.status_code}")
            failed += 1
            log(tenant, "detail_error", id=row["internal_id"], status=r.status_code)
        else:
            body = decoded_text(r)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(body)
            if not _LDJSON.search(body):
                no_ld += 1
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(unique)}] {done} fetched")
        time.sleep(DELAY_SECONDS)

    print(f"\ndetail complete: {done} fetched, {skipped} on disk, {failed} failed")
    print(f"pages with no JSON-LD block: {no_ld}")
    log(tenant, "detail", scoped=len(unique), fetched=done, skipped=skipped,
        failed=failed, no_ldjson=no_ld)
    return 0


def mode_report(tenant):
    p = paths(tenant)
    rows = load_rows(tenant) if os.path.exists(
        os.path.join(p["base"], "rows.jsonl")) else []
    details = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant         : {tenant['key']}")
    print(f"agency         : {tenant['agency']}")
    print(f"scope_states   : {tenant.get('scope_states')}")
    print(f"rows captured  : {len(rows)}")
    print(f"detail on disk : {details}")
    print(f"raw path       : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - JSON-LD JobPosting -> normalized contract.
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Adapters do not share
# code with each other; every GovernmentJobs field name lives in map_record. The
# requirement EXTRACTOR is normalize.experience, shared, driven by this tenant's
# forked openers in config.
# ---------------------------------------------------------------------------

_UNIT_TO_PERIOD = {"HOUR": "HOURLY", "DAY": "DAILY", "WEEK": "WEEKLY",
                   "MONTH": "MONTHLY", "YEAR": "ANNUAL"}

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


# NEOGOV frequently GLUES a bold requirements heading to the end of the prior sentence
# ("...working conditions/environment.<strong>MINIMUM QUALIFICATIONS TO APPLY:</strong><ul>..."),
# so the extractor's html_to_text never yields the heading as its own line and the section is
# missed (reads NOT_STATED). Force a block break before a bold heading (bold text ending in a
# colon) that follows body text. Display-appropriate too - the heading should not run into the
# previous sentence. Scoped to this adapter; the shared extractor is untouched.
_HEADING_BREAK = re.compile(
    r'(?<=[\w.,;:)\]"\'])(\s*<(?:strong|b)\b[^>]*>[^<]{0,70}?:\s*</(?:strong|b)>)', re.I)


def isolate_headings(h):
    return _HEADING_BREAK.sub(r'<br>\1', h or "")


def extract_jobposting(html):
    """The JSON-LD JobPosting object from a stored detail page, or None."""
    for m in _LDJSON.finditer(html or ""):
        try:
            obj = json.loads(m.group(1).strip())
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            return obj
    return None


def parse_location(ld):
    """(location_raw, city, state2) from jobLocation.address; state -> 2-letter code.

    NEOGOV puts city+state in addressLocality ("Seattle, WA") AND a separate
    addressRegion ("WA"), so strip a trailing state token off the locality to keep
    `city` clean (else the board renders "Seattle, WA, WA")."""
    loc = ld.get("jobLocation")
    place = (loc[0] if loc else {}) if isinstance(loc, list) else (loc if isinstance(loc, dict) else {})
    addr = (place or {}).get("address") or {}
    city = (addr.get("addressLocality") or "").strip() or None
    region = (addr.get("addressRegion") or "").strip()
    if city and "," in city:
        head, tail = city.rsplit(",", 1)
        tail = tail.strip()
        if tail.upper() in _STATE_CODES or tail.lower() in US_STATE_TO_CODE:
            city = head.strip() or None
            if not region:
                region = tail
    state = None
    if region:
        state = region.upper() if (len(region) == 2 and region.upper() in _STATE_CODES) \
            else US_STATE_TO_CODE.get(region.lower())
    raw = ", ".join([x for x in (city, region) if x]) or None
    return raw, city, state


def parse_salary(ld):
    """(min, max, is_stated, pay_period, warning). Empty currency -> NOT a stated wage."""
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, False, "UNKNOWN", None
    if not (bs.get("currency") or "").strip():
        return None, None, False, "UNKNOWN", "baseSalary present but currency empty - not a stated wage"
    val = bs.get("value") if isinstance(bs.get("value"), dict) else {}
    lo, _ = model.parse_money(val.get("minValue"))
    hi, _ = model.parse_money(val.get("maxValue"))
    single, _ = model.parse_money(val.get("value"))
    if lo is None and hi is None and single is not None:
        lo = hi = single
    if lo is None and hi is None:
        return None, None, False, "UNKNOWN", None
    unit = (val.get("unitText") or "").strip().upper()
    period = _UNIT_TO_PERIOD.get(unit)
    if period is None:
        # No usable period -> not a stated wage (a bare number is unusable to the audience,
        # and the model rejects a stated salary with UNKNOWN period). Don't guess from magnitude.
        return None, None, False, "UNKNOWN", "baseSalary present but unitText missing/unknown - not a stated wage"
    return lo, hi, True, period, None


def map_record(ld, t, retrieved_at, internal_id, url):
    """GovernmentJobs JSON-LD JobPosting -> normalized contract. The JSON-LD carries NO
    identifier/url, so the stable id and canonical URL come from the detail-page path
    (internal_id from the {id}.html filename, url from the captured row href)."""
    r = model.new_record()
    warnings = []
    r["source_id"] = PLATFORM
    r["source_job_id"] = str(internal_id) or None
    org = ld.get("hiringOrganization")
    org_name = html.unescape(org.get("name")) if isinstance(org, dict) and org.get("name") else None
    r["company_name"] = t.get("company_name") or org_name or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = html.unescape(ld.get("title")) if ld.get("title") else None

    # The JSON-LD description is entity-ENCODED HTML ("&lt;p&gt;..."). Unescape ONCE so
    # description_html is real HTML the extractor's html_to_text can section, and
    # description_text strips cleanly (same as the phenom adapter). Skipping this leaves
    # literal <p> tags in the "text" and the requirements sectionizer never fires.
    desc = isolate_headings(html.unescape(ld.get("description") or "")) or None
    r["description_html"] = desc
    r["description_text"] = strip_html(desc)
    r["qualifications"] = []
    r["qualifications_html"] = None

    raw, city, state = parse_location(ld)
    r["location_raw"] = raw
    if city:
        r["city"] = city
    if state:
        r["state"] = state
    elif raw:
        warnings.append(f"state did not resolve: {raw!r}")

    # NEOGOV emits a non-informative "OTHER" for every posting; the real job-type
    # (Career Service / Term-Ltd) lives only in the list fragment, not the JSON-LD.
    # Null the placeholder rather than carry a meaningless value.
    et = ld.get("employmentType")
    r["employment_type"] = None if (et or "").upper() == "OTHER" else et
    r["posted_at"] = ld.get("datePosted")
    r["freshness_state"] = "UNKNOWN"

    lo, hi, stated, period, salary_warn = parse_salary(ld)
    if stated:
        r["salary_min"], r["salary_max"], r["salary_is_stated"], r["pay_period"] = lo, hi, True, period
    if salary_warn:
        warnings.append(salary_warn)

    r["apply_url"] = url
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = ld.get("industry")
    r["source_function"] = None
    r["source_url"] = url
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")

    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    return r, warnings


def load_details(t):
    """(internal_id, jobposting_or_None) per stored detail page. The id is the {id}.html
    filename - the JSON-LD carries no identifier of its own."""
    p = paths(t)
    if not os.path.isdir(p["detail"]):
        sys.exit("no detail records - run --detail first")
    out = []
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".html"):
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            html = fh.read()
        out.append((fn[:-5], extract_jobposting(html)))
    return out


def _href_by_id(t):
    """{internal_id: canonical detail href} from the captured index rows, so normalize can
    build source/apply URLs the JSON-LD does not carry."""
    f = os.path.join(paths(t)["base"], "rows.jsonl")
    m = {}
    if os.path.exists(f):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if r.get("internal_id") and r.get("href"):
                        m[r["internal_id"]] = r["href"]
    return m


def mode_normalize(t):
    """Map detail JSON-LD into the contract. Derived fields (experience_condition,
    credentials, ...) are left empty BY DESIGN - normalize.enrich fills them with the
    shared extractor and this tenant's forked openers."""
    details = load_details(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    p = paths(t)
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(p["detail"])))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    href_by_id = _href_by_id(t)
    scope = t.get("scope_states")
    mapped, invalid, warns, no_ld, dropped_scope = [], [], [], 0, 0
    for jid, ld in details:
        if ld is None:
            no_ld += 1
            continue
        href = href_by_id.get(jid) or f"/careers/{t['agency']}/jobs/{jid}"
        rec, w = map_record(ld, t, retrieved, jid, CAREERS_BASE + href)
        if scope and rec.get("state") and rec["state"] not in scope:
            dropped_scope += 1
            continue
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

    print(f"{len(details)} detail -> {len(mapped)} normalized "
          f"({no_ld} had no JSON-LD, {dropped_scope} out-of-scope state dropped) -> {out_path}")
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
        uw = {}
        for w in warns:
            uw[w] = uw.get(w, 0) + 1
        for w, n in sorted(uw.items(), key=lambda x: -x[1])[:10]:
            print(f"  {n:>4}x  {w}")
    log(t, "normalize", records=len(mapped), invalid=len(invalid), no_ldjson=no_ld)
    return 0


def main():
    ap = argparse.ArgumentParser(description="GovernmentJobs.com (NEOGOV) adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify AJAX index URL + pagination")
    g.add_argument("--inspect", action="store_true", help="print JSON-LD fields from one job")
    g.add_argument("--index", action="store_true", help="paginate the board")
    g.add_argument("--detail", action="store_true", help="fetch job detail pages")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map detail JSON-LD into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "index", "detail", "report", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
