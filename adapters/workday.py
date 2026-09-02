"""
Workday CXS adapter - No-Experience Job Network.

SCOPE: fetch and write raw JSON to disk. Nothing else.
No field mapping in the fetch modes; mapping lives in map_record below and
writes into the normalized contract.

DELIBERATELY DUPLICATES STRUCTURE FROM adapters/oracle_orc.py. Adapters do not
share code with each other - a Workday change must never be able to break
Oracle. The duplication is the point.

WHAT MAKES WORKDAY DIFFERENT FROM ORACLE, ALL VERIFIED ON A LIVE TENANT
(MultiCare, 1 Sep 2026, DevTools capture):

  1. POST, not GET. Settled - one source claimed GET works, every other said
     POST-only. The live request is POST.

  2. IT NEEDS A SESSION. Oracle is stateless. Workday sets PLAY_SESSION,
     CALYPSO_SESSION, CALYPSO_CSRF_TOKEN and wday_vps_cookie, and requires the
     CSRF token echoed back as the x-calypso-csrf-token header. A bare POST
     with no prior GET will not work.

  3. CLOUDFLARE SITS IN FRONT. server: cloudflare, cf_clearance in the jar.
     This is why curl-cffi with a real Chrome TLS fingerprint is required
     rather than urllib. Oracle had no such layer.

  4. Pagination is offset/limit in the POST BODY, not the query string.

  5. Two hostname patterns exist: {tenant}.wd{N}.myworkdayjobs.com and
     wd{N}.myworkdaysite.com/{lang}/recruiting/{tenant}/{site}. Config carries
     url_style so a parser written from one never silently fails on the other.

Usage:
  python -m adapters.workday --tenant multicare --probe
  python -m adapters.workday --tenant multicare --inspect
  python -m adapters.workday --tenant multicare --index
  python -m adapters.workday --tenant multicare --detail
  python -m adapters.workday --tenant multicare --report
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
RAW_ROOT = os.path.join(ROOT, "raw", "workday")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "workday"
PAGE_LIMIT = 20          # verified in the live request body
DELAY_SECONDS = 1.2      # record: 1-2s, no stated rate limit
MAX_PAGES = 600
TIMEOUT = 45
RESULT_CAP = 10000       # documented Workday ceiling


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH} under '{PLATFORM}'. "
                 f"Known: {', '.join(tenants) or '(none)'}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def base_urls(t):
    """Both documented hostname patterns. url_style is config data, never a
    branch on tenant identity."""
    style = t.get("url_style", "myworkdayjobs")
    lang = t.get("language", "en-US")
    if style == "myworkdaysite":
        host = t["host"]
        careers = f"https://{host}/{lang}/recruiting/{t['tenant']}/{t['site']}"
        cxs = f"https://{host}/wday/cxs/{t['tenant']}/{t['site']}"
    else:
        host = t["host"]
        careers = f"https://{host}/{lang}/{t['site']}"
        cxs = f"https://{host}/wday/cxs/{t['tenant']}/{t['site']}"
    return careers, cxs


def open_session(t):
    """GET the careers page to establish session cookies, then read the CSRF
    token out of the jar.

    This step does not exist in the Oracle adapter and is not optional here.
    Without CALYPSO_CSRF_TOKEN echoed as x-calypso-csrf-token, the POST is
    rejected."""
    careers, _ = base_urls(t)
    s = http.Session()
    s.headers.update({
        "accept": "application/json",
        "accept-language": t.get("language", "en-US"),
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/151.0.0.0 Safari/537.36"),
    })
    r = s.get(careers, timeout=TIMEOUT, **_IMPERSONATE)

    token = None
    for name in ("CALYPSO_CSRF_TOKEN", "calypso_csrf_token"):
        token = s.cookies.get(name) or token
    if not token:
        # some tenants emit it only in the document body
        m = re.search(r'"csrfToken"\s*:\s*"([0-9a-fA-F-]{20,})"', r.text or "")
        if m:
            token = m.group(1)
    if token:
        s.headers["x-calypso-csrf-token"] = token

    return s, r.status_code, token


def paths(t):
    base = os.path.join(RAW_ROOT, t["key"])
    return {"base": base,
            "index": os.path.join(base, "index"),
            "detail": os.path.join(base, "detail"),
            "run": os.path.join(base, "run_log.jsonl")}


def log(t, event, **fields):
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event,
           "applied_facets": t.get("applied_facets") or {}}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def fetch_page(s, t, offset, limit=PAGE_LIMIT, search_text=None, applied_facets=None):
    # search_text / applied_facets override the tenant defaults for one call. The
    # curated-category loop uses them to run the employer's own facet+search
    # queries; every other caller passes neither and gets the configured board.
    _, cxs = base_urls(t)
    body = {
        "appliedFacets": applied_facets if applied_facets is not None
        else (t.get("applied_facets") or {}),
        "limit": limit,
        "offset": offset,
        "searchText": search_text if search_text is not None
        else t.get("search_text", ""),
    }
    return s.post(f"{cxs}/jobs", json=body, timeout=TIMEOUT, **_IMPERSONATE)


def fetch_detail(s, t, external_path):
    _, cxs = base_urls(t)
    path = external_path if external_path.startswith("/") else "/" + external_path
    return s.get(f"{cxs}{path}", timeout=TIMEOUT, **_IMPERSONATE)


def extract_jobs(payload):
    return payload.get("jobPostings", []) or []


def extract_total(payload):
    for k in ("total", "totalCount", "totalJobs"):
        if payload.get(k) is not None:
            return payload[k]
    return None


def req_id(job):
    """Requisition id lives in bulletFields. Formats vary by tenant - JR78035,
    R-12345, 2024-1234 - so parse the field, never a pattern.

    But 'parse the field' first meant 'take the first non-empty element', and
    that was itself an assumption: on MultiCare bulletFields is ordered
    [location, reqId, facility, schedule], so the first element is
    "Lacey, Washington" - a location, not an id. Naming detail files by it
    collapses every posting in a city onto one filename. Field ORDER is a tenant
    convention just like field NAME, so key on SHAPE instead: a requisition id
    carries a digit and no comma and no space, which selects JR80240 and rejects
    "Lacey, Washington", "Capital Medical Center" and "Variable" on any tenant.

    Fall back to the trailing segment of externalPath. If nothing qualifies,
    return None - the caller must skip and count the record, never write a file
    under a guessed name."""
    bf = job.get("bulletFields") or []
    for v in bf:
        if isinstance(v, str) and v.strip():
            s = v.strip()
            if any(c.isdigit() for c in s) and "," not in s and " " not in s:
                return s
    ep = job.get("externalPath") or ""
    seg = ep.rsplit("_", 1)[-1] if "_" in ep else ep.rsplit("/", 1)[-1]
    seg = seg.strip()
    if seg and any(c.isdigit() for c in seg) and "," not in seg and " " not in seg:
        return seg
    return None


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s))[:120]


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


# --- survey helpers. Ported verbatim from oracle_orc; duplication across adapters
# is deliberate - there is no shared survey module, and each source's field names
# stay local to its own adapter. -------------------------------------------------

def sentences(text):
    out, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch in ".;!?":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    s = "".join(buf).strip()
    if s:
        out.append(s)
    return out


# Words that mean a sentence is TALKING ABOUT the experience bar. Broad on purpose
# - the point is to surface employer vocabulary for a human, not to classify.
_EXP_CUES = (
    "experience", "experienced", "years", "year of", "yrs",
    "no prior", "without prior", "entry level", "entry-level",
    "will train", "training provided", "on-the-job", "on the job training",
    "new grad", "recent graduate", "no experience", "background in",
    "minimum qualification", "preferred qualification", "required qualification",
)


def _tally(recs, field, transform=None):
    counts, blank = {}, 0
    for r in recs:
        v = r.get(field)
        if v is None or v == "" or v == []:
            blank += 1
            continue
        if transform:
            v = transform(v)
        key = v if isinstance(v, str) else json.dumps(v)[:80]
        counts[key] = counts.get(key, 0) + 1
    return counts, blank


def _print_tally(title, recs, field, limit=40):
    counts, blank = _tally(recs, field)
    filled = len(recs) - blank
    pct = (filled / len(recs) * 100) if recs else 0
    print(f"\n{title}  ({field})")
    print(f"  fill: {filled}/{len(recs)}  ({pct:.0f}%)   distinct values: {len(counts)}")
    for k, n in sorted(counts.items(), key=lambda x: -x[1])[:limit]:
        print(f"    {n:>5}  {k}")
    if len(counts) > limit:
        print(f"    ... {len(counts) - limit} more")


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def mode_probe(t):
    print(f"tenant   : {t['key']}  ({t.get('label','')})")
    careers, cxs = base_urls(t)
    print(f"careers  : {careers}")
    print(f"cxs      : {cxs}/jobs")
    print(f"facets   : {t.get('applied_facets') or '{} (whole board)'}\n")

    try:
        s, status, token = open_session(t)
    except Exception as e:
        print(f"FAIL  session GET raised: {type(e).__name__}: {e}")
        return 1
    print(f"session GET status : {status}")
    print(f"csrf token         : {'found' if token else 'not in cookie jar'}")
    if status != 200:
        print("\nSession GET did not return 200. Cloudflare challenge or wrong "
              "host/site. Nothing else will work until this does.")
        return 1
    if not token:
        print("\nNo CSRF token in the cookie jar. Some Workday tenants require "
              "the token and some do not - MultiCare returns records without one. "
              "The POST result below is the actual test, not this line.")

    try:
        r = fetch_page(s, t, 0, limit=5)
    except Exception as e:
        print(f"FAIL  POST raised: {type(e).__name__}: {e}")
        return 1

    print(f"\nPOST status : {r.status_code}")
    print(f"bytes       : {len(r.content)}")
    if r.status_code != 200:
        print(f"body        : {r.text[:400]}")
        return 1
    try:
        payload = r.json()
    except Exception:
        print("FAIL  200 but body is not JSON:")
        print(r.text[:400])
        return 1

    jobs, total = extract_jobs(payload), extract_total(payload)
    print(f"total       : {total}")
    print(f"returned    : {len(jobs)}")
    if total and total >= RESULT_CAP:
        print(f"\n** board is at or above the {RESULT_CAP} ceiling - scope with "
              f"applied_facets in config or the tail is unreachable **")
    if not jobs:
        print("\n200 with zero postings. Wrong site slug, or facets exclude "
              "everything.")
        return 1
    print("\nProbe OK. Session and POST return records on this tenant"
          f"{' (CSRF token sent)' if token else ' (no CSRF token needed)'}.")
    log(t, "probe", status=r.status_code, total=total, returned=len(jobs))
    return 0


def mode_inspect(t):
    s, status, token = open_session(t)
    if status != 200:
        print(f"session GET {status}")
        return 1
    r = fetch_page(s, t, 0, limit=2)
    if r.status_code != 200:
        print(f"POST {r.status_code}: {r.text[:300]}")
        return 1
    jobs = extract_jobs(r.json())
    if not jobs:
        print("no postings returned")
        return 1

    job = jobs[0]
    print("LISTING RECORD FIELDS\n")
    for k in sorted(job):
        v = job[k]
        s_ = json.dumps(v)[:120] if not isinstance(v, str) else v[:120]
        print(f"  {k:28} {s_}")
    print(f"\nresolved req id : {req_id(job)}")
    print(f"externalPath    : {job.get('externalPath')}")

    ep = job.get("externalPath")
    if ep:
        time.sleep(DELAY_SECONDS)
        d = fetch_detail(s, t, ep)
        print(f"\nDETAIL status {d.status_code}, {len(d.content)} bytes")
        if d.status_code == 200:
            try:
                body = d.json()
                info = body.get("jobPostingInfo") or body
                print(f"\nDETAIL RECORD FIELDS  "
                      f"(wrapper: {'jobPostingInfo' if 'jobPostingInfo' in body else 'top level'})\n")
                for k in sorted(info):
                    v = info[k]
                    s_ = json.dumps(v)[:120] if not isinstance(v, str) else v[:120]
                    print(f"  {k:28} {s_}")
            except Exception as e:
                print(f"  detail body not JSON: {e}")
    return 0


def mode_index(t):
    s, status, _ = open_session(t)
    if status != 200:
        print(f"session GET {status} - stopping")
        return 1
    p = paths(t)
    os.makedirs(p["index"], exist_ok=True)

    offset, page, seen, total = 0, 0, 0, None
    while page < MAX_PAGES:
        r = fetch_page(s, t, offset)
        if r.status_code != 200:
            print(f"stopped at offset {offset}: status {r.status_code}")
            log(t, "index_error", offset=offset, status=r.status_code)
            break
        payload = r.json()
        jobs = extract_jobs(payload)
        if total is None:
            total = extract_total(payload)
            print(f"board total: {total}")
            if total and total >= RESULT_CAP:
                print(f"** at or above the {RESULT_CAP} ceiling - the tail will "
                      f"be unreachable. Scope with applied_facets. **")
        if not jobs:
            print(f"empty page at offset {offset} - done")
            break

        with open(os.path.join(p["index"], f"page_{page:04d}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

        seen += len(jobs)
        print(f"  page {page:>3}  offset {offset:>6}  +{len(jobs):>3}  running {seen}")
        if total is not None and offset + len(jobs) >= total:
            break
        if offset + len(jobs) >= RESULT_CAP:
            print(f"  hit the {RESULT_CAP} ceiling - stopping")
            break
        offset += len(jobs)
        page += 1
        time.sleep(DELAY_SECONDS)

    print(f"\nindex complete: {seen} of {total} -> {p['index']}")
    log(t, "index", total=total, captured=seen, pages=page + 1)
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.isdir(p["index"]):
        sys.exit("no index on disk - run --index first")
    jobs = []
    for fn in sorted(os.listdir(p["index"])):
        if fn.endswith(".json"):
            with open(os.path.join(p["index"], fn), "r", encoding="utf-8") as fh:
                jobs.extend(extract_jobs(json.load(fh)))
    return jobs


def in_scope(job, t):
    f = t.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True
    field = f.get("field")
    hay = job.get(field) if field else json.dumps(job)
    if not isinstance(hay, str):
        return False
    return any(x in hay for x in terms)


def mode_detail(t):
    s, status, _ = open_session(t)
    if status != 200:
        print(f"session GET {status} - stopping")
        return 1
    p = paths(t)
    os.makedirs(p["detail"], exist_ok=True)

    jobs = load_index(t)
    scoped = [j for j in jobs if in_scope(j, t)]
    print(f"index: {len(jobs)} postings, {len(scoped)} in scope")

    done = skipped = failed = 0
    for i, job in enumerate(scoped, 1):
        rid = req_id(job)
        ep = job.get("externalPath")
        if not ep or not rid:
            failed += 1
            continue
        out = os.path.join(p["detail"], f"{safe_name(rid)}.json")
        if os.path.exists(out):
            skipped += 1
            continue
        r = fetch_detail(s, t, ep)
        if r.status_code != 200:
            print(f"  [{i}/{len(scoped)}] {rid} status {r.status_code}")
            failed += 1
            log(t, "detail_error", req=rid, status=r.status_code)
        else:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(r.text)
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(scoped)}] {done} fetched")
        time.sleep(DELAY_SECONDS)

    print(f"\ndetail complete: {done} fetched, {skipped} on disk, {failed} failed")
    log(t, "detail", scoped=len(scoped), fetched=done, skipped=skipped, failed=failed)
    return 0


def load_details(t):
    p = paths(t)
    if not os.path.isdir(p["detail"]):
        sys.exit("no detail records - run --detail first")
    recs = []
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            try:
                body = json.load(fh)
            except Exception:
                continue
        recs.append(body.get("jobPostingInfo") or body)
    return recs


# Third source, third location shape: 'City, ST, United States' on both Oracle
# tenants, 'Tacoma, Washington' on MultiCare. Accept EITHER a two-letter code or
# a full US state name and normalise to the two-letter code, so `state` reads the
# same across every source. A future Workday tenant may use either form, so this
# handles both rather than swapping one assumption for another. The name->code
# table is fixed US reference data, not tenant config, so it lives in the adapter.
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


def parse_location(location_raw):
    """(city, state2) from 'City, ST[, ...]' or 'City, Full State Name[, ...]'.
    State is normalised to its two-letter code. (None, None) when no state resolves."""
    if not isinstance(location_raw, str) or "," not in location_raw:
        return None, None
    parts = [p.strip() for p in location_raw.split(",")]
    city, token = parts[0], (parts[1] if len(parts) > 1 else "")
    if not city or not token:
        return None, None
    if len(token) == 2 and token.upper() in _STATE_CODES:
        return city, token.upper()
    code = US_STATE_TO_CODE.get(token.lower())
    if code:
        return city, code
    return None, None


def map_record(raw, t, retrieved_at):
    """Workday shape -> normalized contract. Every Workday field name in this
    file lives here."""
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    r["source_job_id"] = str(raw.get("jobReqId") or raw.get("id") or "") or None
    r["company_name"] = t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = raw.get("title")
    r["description_html"] = raw.get("jobDescription")
    r["description_text"] = strip_html(raw.get("jobDescription"))
    # Workday has no segmented qualifications field. Confirmed in the record.
    r["qualifications"] = []
    r["qualifications_html"] = None

    r["location_raw"] = raw.get("location") or raw.get("jobRequisitionLocation")
    city, state = parse_location(r["location_raw"])
    if city:
        r["city"], r["state"] = city, state
    elif r["location_raw"]:
        warnings.append(f"location did not parse: {r['location_raw']!r}")

    r["employment_type"] = raw.get("timeType") or raw.get("jobType")
    r["shift_raw"] = raw.get("shift")
    r["posted_at"] = raw.get("startDate") or raw.get("postedOn")
    r["freshness_state"] = "UNKNOWN"

    ext = raw.get("externalUrl") or raw.get("url")
    if not ext:
        careers, _ = base_urls(t)
        ep = raw.get("externalPath") or ""
        ext = careers + ep if ep else None
    r["apply_url"] = ext
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    r["source_category"] = raw.get("jobFamily")
    r["source_function"] = raw.get("jobFamilyGroup")

    r["source_url"] = r["apply_url"]
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


def mode_report(t):
    p = paths(t)
    jobs = load_index(t) if os.path.isdir(p["index"]) else []
    scoped = [j for j in jobs if in_scope(j, t)]
    details = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant         : {t['key']}")
    print(f"applied_facets : {t.get('applied_facets') or '{} (whole board)'}")
    print(f"NLx WA jobs    : {t.get('nlx_wa_jobs')}  (expected)")
    print(f"index captured : {len(jobs)}")
    print(f"in scope       : {len(scoped)}")
    print(f"detail on disk : {details}")
    print(f"raw path       : {p['base']}")
    return 0


def mode_normalize(t):
    recs = load_details(t)
    p = paths(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.localtime(os.path.getmtime(p["detail"])))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    # Curated-category recovery (from --categories). Keyed by requisition id, which
    # is jobReqId on the detail and the same id --categories read from the listing.
    cat_path = os.path.join(p["base"], "categories.json")
    catmap = {}
    if os.path.exists(cat_path):
        with open(cat_path, "r", encoding="utf-8") as fh:
            catmap = json.load(fh)

    mapped, invalid, warns = [], [], []
    for raw in recs:
        rec, w = map_record(raw, t, retrieved)
        # source_category from a payload field would be set in map_record; MultiCare
        # carries none, so recover it from the employer's own queries here and mark
        # the method so the weaker evidence is never read as a field.
        cats = catmap.get(str(raw.get("jobReqId") or raw.get("id") or ""))
        if cats:
            rec["source_category"] = cats
            rec["source_category_method"] = "employer-curated-query"
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

    print(f"{len(recs)} raw -> {len(mapped)} normalized -> {out_path}")
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
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def mode_survey(t):
    """Read the captured corpus and report its structure and its experience
    vocabulary. No network, no classification, no scoring - reconnaissance only.

    Ported from oracle_orc.mode_survey and adapted to Workday's shape: the record
    is nested under jobPostingInfo, requirements live in jobDescription (there is
    NO separate qualifications field), and there are no flex/salary fields.
    Inclusion rules should be written FROM this output, not imported from another
    source's phrase lists - a MultiCare clinical board will not read like Kroger."""
    recs = load_details(t)
    print("=" * 78)
    print(f"CORPUS SURVEY - {t['key']}  ({t.get('label','')})")
    print(f"{len(recs)} detail records read from disk. No API calls.")
    print("=" * 78)

    # ---------- 1. field fill ----------
    print("\n\n### 1. FIELD FILL - what is actually populated\n")
    keys = {}
    for r in recs:
        for k, v in r.items():
            if v not in (None, "", [], {}):
                keys[k] = keys.get(k, 0) + 1
    for k, n in sorted(keys.items(), key=lambda x: -x[1]):
        bar = "#" * int(n / max(1, len(recs)) * 30)
        print(f"  {n:>5}  {n/len(recs)*100:>5.1f}%  {k:<28} {bar}")

    # ---------- 2. employer taxonomy ----------
    print("\n\n### 2. EMPLOYER-SUPPLIED TAXONOMY - the inclusion axis")
    print("MultiCare's own labels, verbatim. Where a field is empty it is NOT in")
    print("the jobPostingInfo payload - jobFamily/jobFamilyGroup are carried on the")
    print("listing/facets, not the detail record, which is the taxonomy gap to see.")
    for f in ("jobFamily", "jobFamilyGroup", "Category", "jobProfile",
              "supervisoryOrganization", "jobCategory"):
        if any(f in r for r in recs):
            _print_tally(f"  {f}", recs, f, limit=45)

    # ---------- 3. terms and eligibility ----------
    print("\n\n### 3. TERMS AND ELIGIBILITY AXES\n")
    for f in ("timeType", "jobType", "scheduledWeeklyHours", "workerSubType",
              "remoteType", "shift", "workerType"):
        if any(f in r for r in recs):
            _print_tally(f"  {f}", recs, f, limit=25)

    # ---------- 4. location and time ----------
    print("\n\n### 4. LOCATION AND TIME\n")
    _print_tally("  location", recs, "location", limit=60)
    for f in ("startDate", "postedOn"):
        if any(f in r for r in recs):
            _print_tally(f"  {f}", recs, f, limit=24)

    # ---------- 5. salary / flex ----------
    print("\n\n### 5. SALARY / FLEX FIELDS\n")
    print("  Workday's jobPostingInfo carries no flex/salary block, unlike Oracle's")
    print("  requisitionFlexFields. Any pay statement is inside jobDescription prose,")
    print("  not a structured field - so salary is not mappable from the record here.")

    # ---------- 6. qualifications block ----------
    print("\n\n### 6. QUALIFICATIONS - Workday has NO separate field; body only\n")
    desc = [strip_html(r.get("jobDescription")) for r in recs]
    have = [d for d in desc if d]
    dlens = sorted(len(d) for d in have)
    print(f"  jobDescription present: {len(have)}/{len(recs)} "
          f"({len(have)/len(recs)*100:.0f}%)")
    if dlens:
        print(f"  chars  min {dlens[0]}  median {dlens[len(dlens)//2]}  max {dlens[-1]}")
    print("\n  --- three description bodies, verbatim (read for heading formats) ---")
    for d in have[:3]:
        print(f"\n  {d[:1400]}")

    # ---------- 7. experience vocabulary ----------
    print("\n\n" + "=" * 78)
    print("### 7. EXPERIENCE VOCABULARY - employers' own words")
    print("Every sentence mentioning the experience bar, grouped by frequency.")
    print("NOT classified. Read this to write the inclusion rules.")
    print("=" * 78 + "\n")

    freq, records_with = {}, 0
    for r in recs:
        text = strip_html(r.get("jobDescription"))
        hit = False
        for s in sentences(text):
            low = s.lower()
            if any(c in low for c in _EXP_CUES):
                key = " ".join(s.split())[:220]
                freq[key] = freq.get(key, 0) + 1
                hit = True
        if hit:
            records_with += 1

    print(f"  {records_with}/{len(recs)} records ({records_with/len(recs)*100:.0f}%) "
          f"contain at least one experience sentence")
    print(f"  {len(freq)} distinct sentences\n")

    print("  --- REPEATED (appears in 2+ postings; boilerplate the rules hinge on) ---\n")
    rep = [(k, n) for k, n in freq.items() if n > 1]
    for k, n in sorted(rep, key=lambda x: -x[1])[:70]:
        print(f"  {n:>4}x  {k}")
    print(f"\n  ({len(rep)} repeated sentences total)")

    print("\n\n  --- ONE-OFF SAMPLE (40 of the singletons; the long tail) ---\n")
    singles = [k for k, n in freq.items() if n == 1]
    step = max(1, len(singles) // 40)
    for k in singles[::step][:40]:
        print(f"  - {k}")
    print(f"\n  ({len(singles)} singleton sentences total)")

    print("\n" + "=" * 78)
    print("Nothing above is classified, scored, or filtered. Structure and "
          "vocabulary only.")
    print("=" * 78)
    return 0


def mode_categories(t):
    """Recover the category axis the payload does not carry. Runs the employer's
    OWN non-clinical search+facet queries (config: curated_categories), LISTING
    calls only, and records which requisition ids each query returns. This is
    weaker evidence than a field read - free-text search is both over-inclusive
    ('Food Service Director' returns beside 'Food Service Worker') and under-
    inclusive (a 'Dietary Aide' may not return at all) - so normalize tags it
    source_category_method 'employer-curated-query' and never merges it with a
    payload field. Writes {req_id: [category names]} to disk. No detail fetches."""
    cats = t.get("curated_categories") or []
    if not cats:
        print("no curated_categories in config for this tenant")
        return 1
    s, status, _ = open_session(t)
    if status != 200:
        print(f"session GET {status} - stopping")
        return 1

    assign, totals, requests_made = {}, {}, 1    # 1 = the session GET
    for c in cats:
        name = c["name"]
        st = c.get("searchText", "")
        af = c.get("appliedFacets") or {}
        offset, seen, total = 0, 0, None
        payload = None
        while True:
            r = fetch_page(s, t, offset, limit=PAGE_LIMIT, search_text=st, applied_facets=af)
            requests_made += 1
            if r.status_code != 200:
                print(f"  {name}: POST {r.status_code} at offset {offset} - stopping this query")
                break
            payload = r.json()
            if total is None:
                total = extract_total(payload)
                totals[name] = total
            jobs = extract_jobs(payload)
            if not jobs:
                break
            for j in jobs:
                rid = req_id(j)
                if rid:
                    assign.setdefault(rid, set()).add(name)
            seen += len(jobs)
            if total is not None and offset + len(jobs) >= total:
                break
            offset += len(jobs)
            time.sleep(DELAY_SECONDS)
        print(f"  {name:<30} total {str(total):>5}  captured {seen}")
        time.sleep(DELAY_SECONDS)

    out = {rid: sorted(names) for rid, names in assign.items()}
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    out_path = os.path.join(p["base"], "categories.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    per_cat = {}
    for names in out.values():
        for nm in names:
            per_cat[nm] = per_cat.get(nm, 0) + 1
    multi = sum(1 for names in out.values() if len(names) > 1)
    print(f"\nrequisitions tagged: {len(out)}   (hit by >1 query: {multi})")
    for nm, n in sorted(per_cat.items(), key=lambda x: -x[1]):
        print(f"  {n:>5}  {nm}")
    print(f"\nrequests made: {requests_made}")
    print("NOTE: free-text search - over-inclusive (directors returned) and "
          "under-inclusive (some titles missed). source_category_method marks it.")
    print(f"wrote {out_path}")
    log(t, "categories", requests=requests_made, tagged=len(out), per_cat=per_cat)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Workday CXS adapter")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    for m, h in (("probe", "session + CSRF + POST on this tenant"),
                 ("inspect", "real field names from one record"),
                 ("index", "enumerate the board"),
                 ("detail", "fetch detail for in-scope postings"),
                 ("report", "counts from disk"),
                 ("survey", "read the captured corpus: structure + experience vocabulary"),
                 ("categories", "recover the category axis via the employer's own search+facet queries"),
                 ("normalize", "map into the contract")):
        g.add_argument(f"--{m}", action="store_true", help=h)
    a = ap.parse_args()

    t = load_tenant(a.tenant)
    for m in ("probe", "inspect", "index", "detail", "report", "survey", "categories", "normalize"):
        if getattr(a, m):
            return globals()[f"mode_{m}"](t)


if __name__ == "__main__":
    sys.exit(main())
