"""
Radancy TalentBrew career-site adapter - No-Experience Job Network.

SCOPE: fetch and write raw HTML/JSON to disk. Nothing else.
No field mapping, no dedupe, no normalized model, no experience logic.

PLATFORM NAMING - read this before adding a tenant.
The key name is a label, not a finding. Verified by direct fetch 2 Sep 2026:
requests to securitycareers-aus.icims.com return the career site at
jobs.aus.com; the search layer reports SearchAsService; assets load from
tbcdn.talentbrew.com; analytics post to radancy.net; AND the document base
host is *.i.icims.com. TalentBrew markup and Radancy analytics on iCIMS
infrastructure. The vendor relationship is UNKNOWN and no claim is made.
"radancy_tb" is used because the markup self-identifies that way.

This adapter is built against ONE verified fetch shape: the server-rendered
/search-jobs listing described below. Any other tenant - including another
host ending in icims.com - gets --probe run against it first, and goes to its
own platform key if the shape differs. The platform key names the code path,
so one key must never cover two fetch shapes.

Usage:
  python3 -m adapters.radancy_tb --tenant allied_security --probe
  python3 -m adapters.radancy_tb --tenant allied_security --locate
  python3 -m adapters.radancy_tb --tenant allied_security --inspect
  python3 -m adapters.radancy_tb --tenant allied_security --index
  python3 -m adapters.radancy_tb --tenant allied_security --detail
  python3 -m adapters.radancy_tb --tenant allied_security --report
"""

import argparse
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
RAW_ROOT = os.path.join(ROOT, "raw", "radancy_tb")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "radancy_tb"
PAGE_SIZE = 15          # observed, not configured server-side
DELAY_SECONDS = 1.0
MAX_PAGES = 800         # safety stop, not a business rule
TIMEOUT = 45

# Job links: /job/{city-slug}/{title-slug}/{orgId}/{internalId}
_JOB_HREF = re.compile(r'href="(/job/[^"]+/(\d+)/(\d+))"')
# Req ID as printed in the link text: "Req ID: 2026-1671802"
_REQ_ID = re.compile(r"Req ID:\s*([0-9]{4}-[0-9]+)")
# Stated page count, diagnostic only - never a stop condition (QA rule 4)
_PAGE_COUNT = re.compile(r"page\s+\d+\s*/\s*(\d+)", re.I)
_TOTAL = re.compile(r'meta-search-analytics-total-jobs["\s:]+(\d+)', re.I)
# JSON-LD blocks on the job detail page
_LDJSON = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.S | re.I,
)
# Sitemap location rows: href + visible "Washington Jobs 146"
_SITEMAP_ROW = re.compile(
    r'href="(/location/([a-z0-9\-]+)-jobs/\d+/([\d\-]+)/(\d+))"', re.I
)


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH}. Known: {', '.join(tenants)}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def headers():
    return {
        "accept": "text/html,application/xhtml+xml",
        "accept-language": "en-US,en;q=0.9",
    }


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


def get(url):
    return http.get(url, headers=headers(), timeout=TIMEOUT, **_IMPERSONATE)


def decoded_text(r):
    """Decode the response body from its DECLARED charset.

    Writing r.text let the charset be guessed, and the guess put U+FFFD where the
    page's smart quotes and (R) sit - "driver's license" became "driver<FFFD>s
    license", which then defeated the credential allowlist downstream. The page
    declares its charset in the Content-Type header (and its <meta charset>);
    honor that and decode r.content ourselves. Default UTF-8 only when nothing is
    declared."""
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


def page_url(tenant, page):
    """Page 1 is the bare index_url. Radancy appends &p=N to existing params."""
    base = tenant["index_url"]
    if page <= 1:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}p={page}"


def extract_rows(html):
    """One row per job link. Req ID is matched from the text that follows it.

    The listing renders title, city, state and Req ID inside the anchor, so a
    row carries enough to apply the location filter without a detail fetch.
    """
    rows = []
    for m in _JOB_HREF.finditer(html):
        href, org_id, internal_id = m.group(1), m.group(2), m.group(3)
        # Anchor text runs from the end of the href to the closing tag.
        tail = html[m.end(): m.end() + 400]
        text = re.sub(r"<[^>]+>", " ", tail.split("</a>")[0])
        text = " ".join(text.split())
        req = _REQ_ID.search(text)
        rows.append({
            "href": href,
            "org_id": org_id,
            "internal_id": internal_id,
            "req_id": req.group(1) if req else None,
            "link_text": text,
        })
    return rows


def in_scope(row, tenant):
    """Location filter against the anchor text.

    Four location formats across four prior tenants, and a token derived from
    one sample was wrong twice. Tokens live in config so a miss is a config
    edit, not a code change. Empty match_any means take everything.
    """
    f = tenant.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True
    return any(t in row["link_text"] for t in terms)


def mode_probe(tenant):
    """Verify the index URL on this tenant instead of assuming it."""
    url = page_url(tenant, 1)
    print(f"tenant   : {tenant['key']}  ({tenant.get('label','')})")
    print(f"index    : {url}")
    print()
    try:
        r = get(url)
    except Exception as e:
        print(f"FAIL  request raised: {type(e).__name__}: {e}")
        return 1

    print(f"status   : {r.status_code}")
    print(f"bytes    : {len(r.content)}")
    if r.status_code != 200:
        print(r.text[:400])
        return 1

    rows = extract_rows(r.text)
    total = _TOTAL.search(r.text)
    pages = _PAGE_COUNT.search(r.text)
    print(f"job links: {len(rows)} on page 1")
    print(f"stated total : {total.group(1) if total else 'not found'}  (diagnostic only)")
    print(f"stated pages : {pages.group(1) if pages else 'not found'}  (diagnostic only)")
    scoped = [x for x in rows if in_scope(x, tenant)]
    print(f"in scope on page 1: {len(scoped)}")
    if rows:
        print(f"\nfirst row: {rows[0]['req_id']}  {rows[0]['link_text'][:90]}")

    # Does &p=N actually paginate, or return page 1 again?
    if len(rows) >= PAGE_SIZE:
        time.sleep(DELAY_SECONDS)
        r2 = get(page_url(tenant, 2))
        rows2 = extract_rows(r2.text) if r2.status_code == 200 else []
        same = {x["internal_id"] for x in rows} == {x["internal_id"] for x in rows2}
        print(f"\npage 2 status {r2.status_code}, {len(rows2)} links, "
              f"identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - &p=N is not advancing. Stop and re-derive.")
            return 1

    print("\nProbe OK.")
    log(tenant, "probe", status=r.status_code, page1_links=len(rows),
        stated_total=total.group(1) if total else None)
    return 0


def mode_locate(tenant):
    """Resolve location-scoped index URLs from the site's own sitemap.

    The state facet path (e.g. 6252001-XXXXXXX) is a GeoNames id. It is NOT
    hardcoded here - a hardcoded id is exactly the unverified inference that
    produced the Workday 404. This reads it off the page.
    """
    url = tenant["sitemap_url"]
    r = get(url)
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1

    want = (tenant.get("locate_hint") or "").lower()
    hits = []
    for m in _SITEMAP_ROW.finditer(r.text):
        href, slug, path, level = m.groups()
        if want and want not in slug:
            continue
        tail = r.text[m.end(): m.end() + 300]
        text = " ".join(re.sub(r"<[^>]+>", " ", tail.split("</a>")[0]).split())
        hits.append((level, href, text))

    if not hits:
        print(f"no sitemap rows matched hint '{want}'")
        return 1

    print(f"matched {len(hits)} rows (level 3 = state, level 4 = city)\n")
    for level, href, text in sorted(hits)[:40]:
        print(f"  L{level}  {tenant['careers_base']}{href}\n        {text[:80]}")
    print("\nPut the level-3 URL in config as index_url if it paginates with &p=N.")
    print("Run --probe against it before trusting it.")
    return 0


def mode_inspect(tenant):
    """Print the JSON-LD from one job page. Inspect for VALUES, not names.

    ExternalQualificationsStr existed on two Oracle tenants and was empty on
    one. The same discipline applies to JobPosting.qualifications here.
    """
    r = get(page_url(tenant, 1))
    if r.status_code != 200:
        print(f"status {r.status_code}")
        return 1
    rows = extract_rows(r.text)
    if not rows:
        print("no job links on page 1")
        return 1

    job_url = tenant["careers_base"] + rows[0]["href"]
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
                print(f"  {filled}{k:24} len={len(s):>6}  {s[:80]!r}")
    if not found:
        print("NO JobPosting JSON-LD found. The detail parse assumption is wrong -")
        print("stop and re-derive before running --detail.")
        return 1
    return 0


def mode_index(tenant):
    """Paginate the board. Stop on a genuinely empty page, never on a total."""
    p = paths(tenant)
    os.makedirs(p["index"], exist_ok=True)

    seen, page, rows_all = 0, 1, []
    while page <= MAX_PAGES:
        url = page_url(tenant, page)
        r = get(url)
        if r.status_code != 200:
            print(f"stopped at page {page}: status {r.status_code}")
            log(tenant, "index_error", page=page, status=r.status_code)
            break

        rows = extract_rows(r.text)
        if not rows:
            print(f"empty page at {page} - done")
            break

        with open(os.path.join(p["index"], f"page_{page:04d}.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(r.text)

        rows_all.extend(rows)
        seen += len(rows)
        scoped = sum(1 for x in rows if in_scope(x, tenant))
        print(f"  page {page:>4}  +{len(rows):>3}  in-scope {scoped:>3}  running {seen}")

        page += 1
        time.sleep(DELAY_SECONDS)

    ids = {x["internal_id"] for x in rows_all}
    scoped_all = [x for x in rows_all if in_scope(x, tenant)]
    print(f"\nindex complete: {seen} links, {len(ids)} distinct, "
          f"{len(scoped_all)} in scope -> {p['index']}")
    if len(ids) != seen:
        print(f"  NOTE {seen - len(ids)} duplicate links across pages.")

    with open(os.path.join(p["base"], "rows.jsonl"), "w", encoding="utf-8") as fh:
        for x in rows_all:
            fh.write(json.dumps(x) + "\n")

    log(tenant, "index", captured=seen, distinct=len(ids),
        in_scope=len(scoped_all), pages=page - 1, index_url=tenant["index_url"])
    return 0


def load_rows(tenant):
    f = os.path.join(paths(tenant)["base"], "rows.jsonl")
    if not os.path.exists(f):
        sys.exit("no rows.jsonl on disk - run --index first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_detail(tenant):
    """Fetch detail pages for in-scope rows. Resumable. Raw HTML written whole.

    Raw is the asset. The JSON-LD is extracted at normalize time from the
    stored page, so a parser change never costs a re-fetch.
    """
    p = paths(tenant)
    os.makedirs(p["detail"], exist_ok=True)

    rows = load_rows(tenant)
    scoped = [x for x in rows if in_scope(x, tenant)]
    seen_ids, unique = set(), []
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

        r = get(tenant["careers_base"] + row["href"])
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
    log(tenant, "detail", scoped=len(unique), fetched=done,
        skipped=skipped, failed=failed, no_ldjson=no_ld)
    return 0


def mode_report(tenant):
    p = paths(tenant)
    rows = load_rows(tenant) if os.path.exists(
        os.path.join(p["base"], "rows.jsonl")) else []
    scoped = [x for x in rows if in_scope(x, tenant)]
    details = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant           : {tenant['key']}")
    print(f"index_url        : {tenant['index_url']}")
    print(f"location tokens  : {(tenant.get('location_filter') or {}).get('match_any')}")
    print(f"expected in scope: {tenant.get('expected_in_scope')}  (facet read, manual)")
    print(f"rows captured    : {len(rows)}")
    print(f"in scope         : {len(scoped)}")
    print(f"detail on disk   : {details}")
    print(f"raw path         : {p['base']}")
    return 0


# ---------------------------------------------------------------------------
# mapping - JSON-LD JobPosting -> normalized contract
#
# DELIBERATELY DUPLICATES STRUCTURE from the other adapters. Adapters do not
# share code with each other; every Radancy field name in this file lives in
# map_record. The requirement EXTRACTOR is not here - that is normalize.experience,
# one implementation, shared, driven by this tenant's forked openers in config.
# ---------------------------------------------------------------------------

_UNIT_TO_PERIOD = {"HOUR": "HOURLY", "DAY": "DAILY", "WEEK": "WEEKLY",
                   "MONTH": "MONTHLY", "YEAR": "ANNUAL"}

# Fourth source, fourth location shape. JSON-LD addressRegion has been 'WA' on
# every Allied record seen, but a future Radancy tenant may emit a full state
# name, so accept EITHER and normalise to the two-letter code - the same
# discipline the Workday adapter applies to its own location field. This name->
# code table is fixed US reference data, not tenant config, so it lives here.
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


def extract_jobposting(html):
    """The JSON-LD JobPosting object from a stored detail page, or None.

    The page renders the description TWICE in the visible HTML - that duplication
    is what inflated the heading counts 2x during recon. The JSON-LD block is the
    single canonical copy, so normalize reads it and never the visible markup."""
    for m in _LDJSON.finditer(html or ""):
        try:
            obj = json.loads(m.group(1).strip())
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            return obj
    return None


def parse_location(ld):
    """(location_raw, city, state2) from jobLocation.address. state normalised to
    a two-letter code; (raw, city, None) when it will not resolve."""
    loc = ld.get("jobLocation")
    if isinstance(loc, list):
        place = loc[0] if loc else {}
    elif isinstance(loc, dict):
        place = loc
    else:
        place = {}
    addr = (place or {}).get("address") or {}
    city = (addr.get("addressLocality") or "").strip() or None
    region = (addr.get("addressRegion") or "").strip()
    state = None
    if region:
        if len(region) == 2 and region.upper() in _STATE_CODES:
            state = region.upper()
        else:
            state = US_STATE_TO_CODE.get(region.lower())
    raw = ", ".join([x for x in (city, region) if x]) or None
    return raw, city, state


def parse_salary(ld):
    """(min, max, is_stated, pay_period, warning).

    A baseSalary whose currency is EMPTY is NOT a stated wage. A number with no
    currency is a derived/placeholder figure, and treating one as published is
    the exact confusion that once listed a part-time warehouse role at
    $207K-289K. Empty currency -> unstated, no number kept."""
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, False, "UNKNOWN", None
    currency = (bs.get("currency") or "").strip()
    if not currency:
        return (None, None, False, "UNKNOWN",
                "baseSalary present but currency empty - not a stated wage")
    val = bs.get("value") if isinstance(bs.get("value"), dict) else {}
    lo, _ = model.parse_money(val.get("minValue"))
    hi, _ = model.parse_money(val.get("maxValue"))
    single, _ = model.parse_money(val.get("value"))
    if lo is None and hi is None and single is not None:
        lo = hi = single
    if lo is None and hi is None:
        return None, None, False, "UNKNOWN", None
    unit = (val.get("unitText") or "").strip().upper()
    return lo, hi, True, _UNIT_TO_PERIOD.get(unit, "UNKNOWN"), None


def map_record(ld, t, retrieved_at):
    """Radancy JSON-LD JobPosting -> normalized contract. Every Radancy field name
    in this adapter lives here."""
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    r["source_job_id"] = str(ld.get("identifier") or "") or None
    org = ld.get("hiringOrganization")
    r["company_name"] = (org.get("name") if isinstance(org, dict) else None) \
        or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = ld.get("title")

    # INPUT: the JSON-LD `description` is the canonical body the extractor sections.
    # Never the visible page HTML - it renders the description twice.
    desc = ld.get("description")
    r["description_html"] = desc
    r["description_text"] = strip_html(desc)
    # No segmented qualifications field on this platform - the JobPosting block
    # carries no 'qualifications' key (confirmed by --inspect, 146/146). Body only.
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

    r["employment_type"] = ld.get("employmentType")
    r["shift_raw"] = ld.get("workHours")
    r["posted_at"] = ld.get("datePosted")
    r["freshness_state"] = "UNKNOWN"

    lo, hi, stated, period, salary_warn = parse_salary(ld)
    if stated:
        r["salary_min"] = lo
        r["salary_max"] = hi
        r["salary_is_stated"] = True
        r["pay_period"] = period
    if salary_warn:
        warnings.append(salary_warn)

    r["apply_url"] = ld.get("url")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    # industry is the source's own label; a field read, so no method tag. There is
    # no job-function field on this board, so source_function stays null.
    r["source_category"] = ld.get("industry")
    r["source_function"] = None

    r["source_url"] = ld.get("url")
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


def load_details(t):
    """Every stored detail page, parsed to its JSON-LD JobPosting. Returns a list
    of (filename, jobposting_or_None)."""
    p = paths(t)
    if not os.path.isdir(p["detail"]):
        sys.exit("no detail records - run --detail first")
    out = []
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".html"):
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            out.append((fn, extract_jobposting(fh.read())))
    return out


def mode_normalize(t):
    """Map detail pages into the contract. Derived fields (experience_condition,
    credentials, ...) are left empty BY DESIGN - filling them is normalize.enrich's
    job, running the shared extractor with this tenant's forked openers."""
    details = load_details(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    p = paths(t)
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.localtime(os.path.getmtime(p["detail"])))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns, no_ld = [], [], [], 0
    for fn, ld in details:
        if ld is None:
            no_ld += 1
            continue
        rec, w = map_record(ld, t, retrieved)
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
          f"({no_ld} had no JSON-LD) -> {out_path}")
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
    ap = argparse.ArgumentParser(description="Radancy TalentBrew adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify index URL and pagination")
    g.add_argument("--locate", action="store_true", help="resolve location URLs from sitemap")
    g.add_argument("--inspect", action="store_true", help="print JSON-LD fields from one job")
    g.add_argument("--index", action="store_true", help="paginate the board")
    g.add_argument("--detail", action="store_true", help="fetch in-scope job pages")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map detail JSON-LD into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "locate", "inspect", "index", "detail", "report", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
