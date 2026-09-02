"""
Oracle Fusion Recruiting Cloud (ORC) adapter — No-Experience Job Network.

SCOPE: fetch and write raw JSON to disk. Nothing else.
No field mapping, no dedupe, no normalized model, no experience logic.
Those are a separate step against the raw capture.

The raw capture is the asset; this code is disposable. Every file written here
is untouched vendor JSON, so a parsing bug downstream never costs a re-fetch.

Call shape sources (both independent, neither is Oracle's own doc, which marks
these endpoints "Oracle internal use"):
  https://github.com/Masterjx9/OpenPostings/discussions/16
  https://jobo.world/ats/oraclecloud
Oracle reference for finder variables:
  https://docs.oracle.com/en/cloud/saas/human-resources/farws/api-recruiting-ce-job-requisitions.html

Usage:
  python3 -m adapters.oracle_orc --tenant providence --probe
  python3 -m adapters.oracle_orc --tenant providence --inspect
  python3 -m adapters.oracle_orc --tenant providence --index
  python3 -m adapters.oracle_orc --tenant providence --detail
  python3 -m adapters.oracle_orc --tenant providence --report
  python3 -m adapters.oracle_orc --tenant providence --survey
  python3 -m adapters.oracle_orc --tenant providence --normalize
"""

import argparse
import json
import re
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

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "oracle_orc")

PLATFORM = "oracle_orc"
LIST_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
FACETS = "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
EXPAND = "requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations"

PAGE_LIMIT = 100
DELAY_SECONDS = 0.6      # jobo.world: 1-2 req/sec, 500ms delays, 429 risk above that
MAX_PAGES = 500          # safety stop, not a business rule
TIMEOUT = 45


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH}. Known: {', '.join(tenants)}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def session_headers(tenant):
    # ora-irc-cx-userid is any UUID; without these three headers the endpoint
    # may error or return empty. Generated once per run so the whole run looks
    # like one anonymous candidate session.
    return {
        "ora-irc-cx-userid": str(uuid.uuid4()),
        "ora-irc-language": tenant.get("language", "en"),
        "content-type": "application/vnd.oracle.adf.resourceitem+json;charset=utf-8",
        "accept": "application/json",
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


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

def fetch_page(tenant, headers, offset, limit=PAGE_LIMIT):
    url = f"{os.environ.get('NEJN_SCHEME','https')}://{tenant['host']}{LIST_PATH}"
    # limit and offset MUST live inside the finder string. As top-level URL params
    # they are silently ignored: the framework paginates the outer items array
    # (always one wrapper element), not the inner requisitionList, so every page
    # returns the same first 25 records. Inside the finder they paginate the
    # requisitions and the 25-cap is lifted (limit=100 returns 100).
    finder = (
        f"findReqs;siteNumber={tenant['site_number']},sortBy=POSTING_DATES_DESC,"
        f"limit={limit},offset={offset}"
    )
    # Server-side facet filters, config-driven. Kroger's board is 12,140 and the
    # endpoint stops paginating past offset 10000, so the oldest ~2,140 records
    # (any WA posting among them) are unreachable client-side. Passing the WA
    # locationId as a bare finder variable makes the server return only the WA
    # subset, which fits under the ceiling. Absent key -> no change in behaviour,
    # and never a tenant branch: the values live in config, the mechanism here.
    for k, v in (tenant.get("finder_extra") or {}).items():
        finder += f",{k}={v}"
    params = {
        "onlyData": "true",
        "expand": EXPAND,
        "finder": finder,
        # facetsList is rejected as a top-level URL param ("cannot be used in this
        # context") and we consume no facet data, so it is omitted. FACETS stays
        # defined above as documentation of the option, not passed here.
    }
    r = http.get(url, params=params, headers=headers, timeout=TIMEOUT, **_IMPERSONATE)
    return r


def fetch_detail(tenant, headers, req_id):
    url = f"{os.environ.get('NEJN_SCHEME','https')}://{tenant['host']}{DETAIL_PATH}"
    params = {
        "expand": "all",
        "onlyData": "true",
        "finder": f"ById;Id={req_id},siteNumber={tenant['site_number']}",
    }
    r = http.get(url, params=params, headers=headers, timeout=TIMEOUT, **_IMPERSONATE)
    return r


def extract_jobs(payload):
    """Pull the job records out of a listing response without assuming much."""
    jobs = []
    for item in payload.get("items", []) or []:
        jobs.extend(item.get("requisitionList", []) or [])
    return jobs


def extract_total(payload):
    for item in payload.get("items", []) or []:
        if item.get("TotalJobsCount") is not None:
            return item["TotalJobsCount"]
    return None


def job_id(job):
    for k in ("Id", "id", "RequisitionId", "requisitionId", "JobRequisitionId"):
        if job.get(k):
            return str(job[k])
    return None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def mode_probe(tenant):
    """Verify the endpoint on this tenant instead of assuming it."""
    headers = session_headers(tenant)
    print(f"tenant   : {tenant['key']}  ({tenant.get('label','')})")
    print(f"host     : {tenant['host']}")
    print(f"site     : {tenant['site_number']}")
    print()

    try:
        r = fetch_page(tenant, headers, offset=0, limit=5)
    except Exception as e:
        print(f"FAIL  request raised: {type(e).__name__}: {e}")
        return 1

    print(f"status   : {r.status_code}")
    print(f"bytes    : {len(r.content)}")
    if r.status_code != 200:
        print(f"body     : {r.text[:400]}")
        print("\nNot 200. Check host and site_number against a live apply URL.")
        return 1

    try:
        payload = r.json()
    except Exception:
        print("FAIL  200 but body is not JSON. First 400 chars:")
        print(r.text[:400])
        return 1

    jobs = extract_jobs(payload)
    total = extract_total(payload)
    print(f"total    : {total}")
    print(f"returned : {len(jobs)} on this page")
    if not jobs:
        print("\n200 with zero jobs. Usually a wrong site_number or missing headers.")
        return 1
    print("\nProbe OK. Endpoint is live and returns records on this tenant.")
    log(tenant, "probe", status=r.status_code, total=total, returned=len(jobs))
    return 0


def mode_inspect(tenant):
    """Print real field names from one live record so filters stop being guesses."""
    headers = session_headers(tenant)
    r = fetch_page(tenant, headers, offset=0, limit=2)
    if r.status_code != 200:
        print(f"status {r.status_code}: {r.text[:300]}")
        return 1
    jobs = extract_jobs(r.json())
    if not jobs:
        print("no records returned")
        return 1
    job = jobs[0]
    print("LISTING RECORD FIELDS\n")
    for k in sorted(job):
        v = job[k]
        s = json.dumps(v)[:110] if not isinstance(v, str) else v[:110]
        print(f"  {k:34} {s}")
    rid = job_id(job)
    print(f"\nresolved job id: {rid}")

    if rid:
        time.sleep(DELAY_SECONDS)
        d = fetch_detail(tenant, headers, rid)
        print(f"\nDETAIL CALL status {d.status_code}, {len(d.content)} bytes")
        if d.status_code == 200:
            try:
                items = d.json().get("items", [])
                if items:
                    print("\nDETAIL RECORD FIELDS\n")
                    for k in sorted(items[0]):
                        v = items[0][k]
                        s = json.dumps(v)[:110] if not isinstance(v, str) else v[:110]
                        print(f"  {k:34} {s}")
            except Exception as e:
                print(f"  detail body not JSON: {e}")
    return 0


def mode_index(tenant):
    """Enumerate the whole board. Cheap. Writes raw pages untouched."""
    headers = session_headers(tenant)
    p = paths(tenant)
    os.makedirs(p["index"], exist_ok=True)

    offset, page, seen, total = 0, 0, 0, None
    while page < MAX_PAGES:
        r = fetch_page(tenant, headers, offset)
        if r.status_code != 200:
            print(f"stopped at offset {offset}: status {r.status_code}")
            log(tenant, "index_error", offset=offset, status=r.status_code)
            break

        payload = r.json()
        jobs = extract_jobs(payload)
        if total is None:
            total = extract_total(payload)
            print(f"board total: {total}")

        if not jobs:
            print(f"empty page at offset {offset} - done")
            break

        out = os.path.join(p["index"], f"page_{page:04d}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)

        seen += len(jobs)
        print(f"  page {page:>3}  offset {offset:>6}  +{len(jobs):>3}  running {seen}")

        if total is not None and offset + len(jobs) >= total:
            break
        # Advance by records actually returned, not by PAGE_LIMIT. With in-finder
        # pagination a full page is PAGE_LIMIT, but the last page is short (e.g. 34
        # of a 2034 board), so stepping by len(jobs) keeps offset exact instead of
        # overshooting on the final page.
        offset += len(jobs)
        page += 1
        time.sleep(DELAY_SECONDS)

    finder_extra = tenant.get("finder_extra") or {}
    if finder_extra:
        print(f"\nNOTE: server-side finder_extra applied: {finder_extra}")
        print("This capture is SCOPED, not the whole board. Do not read it as complete.")
    print(f"\nindex complete: {seen} records across {page + 1} pages -> {p['index']}")
    # finder_extra is written into the run log so a later reader can never mistake
    # a server-side-scoped capture for a complete board enumeration.
    log(tenant, "index", total=total, captured=seen, pages=page + 1,
        finder_extra=finder_extra)
    return 0


def load_index(tenant):
    p = paths(tenant)
    if not os.path.isdir(p["index"]):
        sys.exit("no index on disk - run --index first")
    jobs = []
    for fn in sorted(os.listdir(p["index"])):
        if fn.endswith(".json"):
            with open(os.path.join(p["index"], fn), "r", encoding="utf-8") as fh:
                jobs.extend(extract_jobs(json.load(fh)))
    return jobs


def in_scope(job, tenant):
    """Location filter. Reads the field named in config rather than the whole
    record, because a blob match catches records that merely MENTION the state.

    Measured on Providence 31 Aug 2026: blob matching scoped 851, the field
    scopes 848. The three extras were OR- and AK-primary roles listing a WA
    location elsewhere in the record - real WA-eligible remote work, but not
    WA by primary location.

    Set location_filter.field in config to pin it. Omit the field and it falls
    back to blob matching, which is the correct behaviour on a NEW tenant whose
    field names have not been read with --inspect yet."""
    f = tenant.get("location_filter") or {}
    terms = f.get("match_any")
    if not terms:
        return True

    field = f.get("field")
    if field:
        value = job.get(field)
        if not isinstance(value, str):
            return False          # field absent or not a string - out of scope
        haystack = value
    else:
        haystack = json.dumps(job)

    return any(t in haystack for t in terms)


def mode_detail(tenant):
    """Fetch full detail only for in-scope records. Resumable."""
    headers = session_headers(tenant)
    p = paths(tenant)
    os.makedirs(p["detail"], exist_ok=True)

    jobs = load_index(tenant)
    scoped = [j for j in jobs if in_scope(j, tenant)]
    print(f"index: {len(jobs)} records, {len(scoped)} in scope after location filter")

    done = skipped = failed = 0
    for i, job in enumerate(scoped, 1):
        rid = job_id(job)
        if not rid:
            failed += 1
            continue
        out = os.path.join(p["detail"], f"{rid}.json")
        if os.path.exists(out):
            skipped += 1
            continue

        r = fetch_detail(tenant, headers, rid)
        if r.status_code != 200:
            print(f"  [{i}/{len(scoped)}] {rid} status {r.status_code}")
            failed += 1
            log(tenant, "detail_error", req=rid, status=r.status_code)
        else:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(r.text)
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(scoped)}] {done} fetched")
        time.sleep(DELAY_SECONDS)

    print(f"\ndetail complete: {done} fetched, {skipped} already on disk, {failed} failed")
    log(tenant, "detail", scoped=len(scoped), fetched=done, skipped=skipped, failed=failed)
    return 0


def load_details(tenant):
    """Read every captured detail record off disk. No network."""
    p = paths(tenant)
    if not os.path.isdir(p["detail"]):
        sys.exit("no detail records on disk - run --detail first")
    recs = []
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except Exception:
                continue
        items = payload.get("items") or []
        if items:
            recs.append(items[0])
        elif isinstance(payload, dict) and payload.get("Id"):
            recs.append(payload)      # some tenants return the record unwrapped
    return recs


def strip_html(s):
    if not isinstance(s, str):
        return ""
    # Tags become spaces, not nothing. Without this, "<p>Education: HS diploma.</p>
    # <p>No experience required.</p>" collapses to "...diploma.No experience..."
    # and the sentence splitter mis-segments every multi-paragraph block.
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


# Words that mean a sentence is TALKING ABOUT the experience bar. Deliberately
# broad and deliberately not a classifier - the point is to surface employer
# vocabulary for a human to read, not to label anything.
_EXP_CUES = (
    "experience", "experienced", "years", "year of", "yrs",
    "no prior", "without prior", "entry level", "entry-level",
    "will train", "training provided", "on-the-job", "on the job training",
    "new grad", "recent graduate", "no experience", "background in",
    "minimum qualification", "preferred qualification", "required qualification",
)


def _tally(recs, field, limit=40, transform=None):
    counts = {}
    blank = 0
    for r in recs:
        v = r.get(field)
        if v is None or v == "" or v == []:
            blank += 1
            continue
        if transform:
            v = transform(v)
        key = v if isinstance(v, str) else json.dumps(v)[:80]
        counts[key] = counts.get(key, 0) + 1
    return counts, blank, limit


def _print_tally(title, recs, field, limit=40):
    counts, blank, limit = _tally(recs, field, limit)
    filled = len(recs) - blank
    pct = (filled / len(recs) * 100) if recs else 0
    print(f"\n{title}  ({field})")
    print(f"  fill: {filled}/{len(recs)}  ({pct:.0f}%)   distinct values: {len(counts)}")
    for k, n in sorted(counts.items(), key=lambda x: -x[1])[:limit]:
        print(f"    {n:>5}  {k}")
    if len(counts) > limit:
        print(f"    ... {len(counts) - limit} more")


def mode_survey(tenant):
    """Read the captured corpus and report its structure and its experience
    vocabulary. No network, no classification, no scoring - reconnaissance only.

    Inclusion and exclusion rules should be written FROM this output, not
    imported from a different source's phrase lists."""
    recs = load_details(tenant)
    print("=" * 78)
    print(f"CORPUS SURVEY - {tenant['key']}  ({tenant.get('label','')})")
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
        print(f"  {n:>5}  {n/len(recs)*100:>5.1f}%  {k:<34} {bar}")

    # ---------- 2. employer taxonomy ----------
    print("\n\n### 2. EMPLOYER-SUPPLIED TAXONOMY - the inclusion axis")
    print("These are Providence's own labels, not derived. If a category cleanly")
    print("separates frontline from clinical, inclusion is a lookup not a parse.")
    for f in ("Category", "JobFunction", "JobFunctionCode", "JobFamily",
              "Organization", "BusinessUnit", "Department"):
        if any(f in r for r in recs):
            _print_tally(f"  {f}", recs, f, limit=45)

    # ---------- 3. terms and eligibility axes ----------
    print("\n\n### 3. TERMS AND ELIGIBILITY AXES\n")
    for f in ("StudyLevel", "JobShift", "WorkerType", "JobType", "JobSchedule",
              "ContractType", "WorkplaceType", "JobLevel", "JobGrade",
              "WorkDays", "WorkHours", "ManagerLevel", "Level"):
        if any(f in r for r in recs):
            _print_tally(f"  {f}", recs, f, limit=25)

    # ---------- 4. location and time ----------
    print("\n\n### 4. LOCATION AND TIME\n")
    _print_tally("  PrimaryLocation", recs, "PrimaryLocation", limit=60)
    for f in ("ExternalPostedStartDate", "PostedDate"):
        if any(f in r for r in recs):
            _print_tally(f"  {f} (year-month)", recs, f,
                         limit=24)

    # ---------- 5. flex fields ----------
    print("\n\n### 5. requisitionFlexFields - salary and FTE if published\n")
    flex_names, flex_present = {}, 0
    for r in recs:
        ff = r.get("requisitionFlexFields")
        if not ff:
            continue
        flex_present += 1
        if isinstance(ff, list):
            for item in ff:
                if isinstance(item, dict):
                    nm = item.get("Prompt") or item.get("Name") or item.get("AttributeName")
                    if nm:
                        flex_names[str(nm)] = flex_names.get(str(nm), 0) + 1
        elif isinstance(ff, dict):
            for k in ff:
                flex_names[k] = flex_names.get(k, 0) + 1
    print(f"  present on {flex_present}/{len(recs)} records")
    for k, n in sorted(flex_names.items(), key=lambda x: -x[1])[:40]:
        print(f"    {n:>5}  {k}")
    if not flex_names and flex_present:
        sample = next((r["requisitionFlexFields"] for r in recs if r.get("requisitionFlexFields")), None)
        print(f"    shape not recognised. Sample: {json.dumps(sample)[:400]}")

    # ---------- 6. qualifications block ----------
    print("\n\n### 6. ExternalQualificationsStr - is it a real segmented block?\n")
    qual = [strip_html(r.get("ExternalQualificationsStr")) for r in recs]
    have = [q for q in qual if q]
    lens = sorted(len(q) for q in have)
    print(f"  present and non-empty: {len(have)}/{len(recs)} ({len(have)/len(recs)*100:.0f}%)")
    if lens:
        print(f"  chars  min {lens[0]}  median {lens[len(lens)//2]}  max {lens[-1]}")
    desc = [strip_html(r.get("ExternalDescriptionStr")) for r in recs]
    dlens = sorted(len(d) for d in desc if d)
    if dlens:
        print(f"  description chars  median {dlens[len(dlens)//2]}  max {dlens[-1]}")
    print("\n  --- three full qualifications blocks, verbatim ---")
    for q in have[:3]:
        print(f"\n  {q[:1200]}")

    # ---------- 7. experience vocabulary ----------
    print("\n\n" + "=" * 78)
    print("### 7. EXPERIENCE VOCABULARY - employers' own words")
    print("Every sentence mentioning the experience bar, grouped by frequency.")
    print("NOT classified. Read this to write the inclusion rules.")
    print("=" * 78 + "\n")

    freq, records_with = {}, 0
    for r in recs:
        text = strip_html(r.get("ExternalQualificationsStr")) or strip_html(r.get("ExternalDescriptionStr"))
        hit = False
        for s in sentences(text):
            low = s.lower()
            if any(c in low for c in _EXP_CUES):
                key = " ".join(s.split())[:220]
                freq[key] = freq.get(key, 0) + 1
                hit = True
        if hit:
            records_with += 1

    print(f"  {records_with}/{len(recs)} records ({records_with/len(recs)*100:.0f}%) contain "
          f"at least one experience sentence")
    print(f"  {len(freq)} distinct sentences\n")

    print("  --- REPEATED (appears in 2+ postings; boilerplate, and the rules "
          "will hinge on these) ---\n")
    rep = [(k, n) for k, n in freq.items() if n > 1]
    for k, n in sorted(rep, key=lambda x: -x[1])[:70]:
        print(f"  {n:>4}x  {k}")
    print(f"\n  ({len(rep)} repeated sentences total)")

    print("\n\n  --- ONE-OFF SAMPLE (40 of the singletons; the long tail the "
          "rules must not break on) ---\n")
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



# ==========================================================================
# MAPPING - Oracle field shape into the normalized contract.
#
# Every Oracle field name in this file lives HERE, in the adapter. Nothing
# above the contract knows this source exists.
#
# Every rule below is derived from a measured survey of 851 captured records,
# not from documentation and not from a field name. Where a rule rests on an
# observation rather than a guarantee, the observation is stated and guarded.
# ==========================================================================

# Measured, 851 records: every value read "City, WA, United States".
_LOC = re.compile(r"^\s*([^,]+?)\s*,\s*([A-Z]{2})\s*(?:,|$)")

# Measured: 1,595 numeric salary values, min 17.00, max 148.35, none above
# 10,000. The 17.00 floor tracks WA minimum wage. These are hourly rates.
# GUARD: a value above this ceiling means the assumption no longer holds on
# that record - flag it rather than publish an hourly rate that is really an
# annual one. Silently annualising pay is a documented failure mode elsewhere
# and it destroys the field this audience decides on.
HOURLY_SANITY_CEILING = 2000.0


def _flex(rec):
    """requisitionFlexFields -> {prompt: value}. Prompt names are configured
    per employer, so a second Oracle tenant may name them differently. That is
    a config mapping, not a second adapter. --survey reveals them."""
    out = {}
    ff = rec.get("requisitionFlexFields")
    if isinstance(ff, list):
        for item in ff:
            if isinstance(item, dict):
                name = item.get("Prompt") or item.get("Name") or item.get("AttributeName")
                if name:
                    out[str(name).strip()] = item.get("Value")
    elif isinstance(ff, dict):
        out = {str(k): v for k, v in ff.items()}
    return out


def _pick(d, *needles):
    for k, v in d.items():
        low = k.lower()
        if all(n in low for n in needles):
            return v
    return None


def _days_since(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y"):
        try:
            t = time.strptime(date_str[:len(time.strftime(fmt))], fmt)
            return int((time.time() - time.mktime(t)) / 86400)
        except (ValueError, OverflowError):
            continue
    return None


def map_record(raw, tenant, retrieved_at):
    """One Oracle detail record -> one normalized record."""
    r = model.new_record()
    warnings = []

    # Employer flex fields, read once. Prompt names are per-employer config, not
    # a second adapter (see _flex). Kroger names differ entirely from Providence,
    # so several fallbacks below read from here rather than from a fixed column.
    flex = _flex(raw)

    # ---- identity ----
    r["source_id"] = PLATFORM
    r["source_job_id"] = str(raw.get("RequisitionNumber")
                             or raw.get("RequisitionId")
                             or raw.get("Id") or "") or None

    # ---- employer ----
    # LegalEmployer is the operating entity; the config label is the brand the
    # job seeker recognises. Prefer the source's own value where present.
    # Kroger leaves LegalEmployer and Organization null but carries the real
    # recognisable brand ("Fred Meyer Jewelers", "QFC") in flex 'Banner Name' -
    # a job seeker knows the banner, not "The Kroger Family of Companies". Fall
    # back to it ahead of the generic tenant label.
    r["company_name"] = (raw.get("LegalEmployer")
                         or raw.get("Organization")
                         or _pick(flex, "banner")
                         or tenant.get("label"))
    r["employer_domain"] = tenant.get("employer_domain")

    # ---- role ----
    r["title"] = raw.get("Title")
    r["description_html"] = raw.get("ExternalDescriptionStr")
    r["description_text"] = strip_html(raw.get("ExternalDescriptionStr"))

    # Measured: ExternalQualificationsStr is EMPTY on 100% of 851 records.
    # It was previously recorded as a segmented qualifications block on the
    # strength of the field NAME appearing in an inspect listing. It is not.
    # Requirements live in the description body and must be segmented by the
    # extractor. Populate only if a tenant actually fills it.
    qual = strip_html(raw.get("ExternalQualificationsStr"))
    r["qualifications"] = [qual] if qual else []
    # Same field, kept UNstripped, so the extractor can read its <li>/<p> item
    # boundaries. Empty on Providence, populated on 100% of Kroger - which is why
    # section detection was 0% on Kroger until the extractor was given this input.
    r["qualifications_html"] = raw.get("ExternalQualificationsStr") or None

    # ---- place ----
    r["location_raw"] = raw.get("PrimaryLocation")
    m = _LOC.match(r["location_raw"] or "")
    if m:
        r["city"], r["state"] = m.group(1).strip(), m.group(2)
    elif r["location_raw"]:
        warnings.append(f"location did not parse: {r['location_raw']!r}")
    # market stays null - the geography model is deliberately unsettled.

    # ---- terms ----
    # JobType and WorkerType are both null on Kroger; JobSchedule carries the
    # real value ("Part time"). Added as a fallback, not a replacement -
    # Providence populates the first two.
    r["employment_type"] = (raw.get("JobType") or raw.get("WorkerType")
                            or raw.get("JobSchedule"))
    r["shift_raw"] = raw.get("JobShift")

    lo, lo_ok = model.parse_money(_pick(flex, "minimum", "salary"))
    hi, hi_ok = model.parse_money(_pick(flex, "maximum", "salary"))
    if lo_ok or hi_ok:
        r["salary_min"], r["salary_max"] = lo, hi
        r["salary_is_stated"] = True
        biggest = max(v for v in (lo, hi) if v is not None)
        if biggest > HOURLY_SANITY_CEILING:
            # Do not publish a period we cannot stand behind.
            r["pay_period"] = "UNKNOWN"
            warnings.append(f"salary {biggest} exceeds hourly ceiling - period "
                            f"not asserted on {r['source_job_id']}")
        else:
            r["pay_period"] = tenant.get("pay_period", "HOURLY")
    # else: withheld ('See Posting'). is_stated stays False, values stay None.

    fte, fte_ok = model.parse_money(_pick(flex, "fte"))
    if fte_ok:
        r["fte"] = fte

    # ---- time ----
    r["posted_at"] = raw.get("ExternalPostedStartDate") or raw.get("PostedDate")
    # first_seen / last_seen are NOT set here. They are facts about this
    # pipeline's history with the posting, not facts in the vendor record, and
    # they are applied from persisted state in mode_normalize.
    r["freshness_state"] = model.freshness_from_days(_days_since(r["posted_at"]))

    # ---- apply ----
    # Constructed from the confirmed candidate-experience URL shape. The three
    # apply URLs used to identify this tenant all took this form.
    if r["source_job_id"]:
        r["apply_url"] = (
            f"https://{tenant['host']}/hcmUI/CandidateExperience/"
            f"{tenant.get('language','en')}/sites/{tenant['site_number']}"
            f"/job/{raw.get('Id') or r['source_job_id']}"
        )
    r["apply_class"] = "ATS"

    # ---- source taxonomy, verbatim, never merged with our category[] ----
    r["source_category"] = raw.get("Category")
    r["source_function"] = raw.get("JobFunction")

    # ---- derived: ours, and empty until the extractor exists ----
    # education_flag is the ONE derived value taken here, because the employer
    # states it directly in StudyLevel rather than leaving it to a parse.
    # StudyLevel is null on Kroger; the same fact lives in flex 'Education Level'
    # ("High school graduate"). Fallback, not a replacement.
    r["education_flag"] = raw.get("StudyLevel") or _pick(flex, "education")

    # ---- provenance ----
    r["source_url"] = r["apply_url"]
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = tenant.get("terms_reference")

    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


def mode_normalize(tenant):
    """Map every captured detail record into the contract. Reads disk, writes
    disk, no network. Re-runnable at zero cost - which is the entire reason raw
    is kept separately from normalized."""
    recs = load_details(tenant)
    p = paths(tenant)
    out_dir = os.path.join(ROOT, "out", PLATFORM, tenant["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.localtime(os.path.getmtime(p["detail"])))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Persisted seen-state. first_seen is written once and never rewritten;
    # last_seen advances every run. This file is the pipeline's memory of the
    # board and is what any future expiry rule measures against - it is NOT
    # derivable from the raw capture, so it is the one piece of state worth
    # keeping outside it.
    state_path = os.path.join(out_dir, "seen_state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    else:
        seen_state = {}
    known_before = len(seen_state)

    mapped, all_warnings, invalid = [], [], []
    new_this_run = 0
    for raw in recs:
        rec, warns = map_record(raw, tenant, retrieved)
        if model.seen_key(rec) not in seen_state:
            new_this_run += 1
        model.apply_seen_state(rec, seen_state, now)
        problems = model.validate(rec)
        if problems:
            invalid.append((rec.get("source_job_id"), problems))
        mapped.append(rec)
        all_warnings.extend(warns)

    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(seen_state, fh, ensure_ascii=False, indent=1)

    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in mapped:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("=" * 74)
    print(f"NORMALIZE - {tenant['key']}")
    print(f"{len(recs)} raw records -> {len(mapped)} normalized")
    print(f"schema {model.SCHEMA_VERSION} -> {out_path}")
    print("=" * 74)

    print("\n### FILL RATE - what the contract actually carries\n")
    for f, n, pct in model.fill_report(mapped):
        bar = "#" * int(pct / 100 * 28)
        print(f"  {n:>5}  {pct:>5.1f}%  {f:<22} {bar}")

    print("\n### SALARY\n")
    stated = [r for r in mapped if r["salary_is_stated"]]
    withheld = len(mapped) - len(stated)
    print(f"  stated   : {len(stated)}")
    print(f"  withheld : {withheld}   (employer published no number)")
    if stated:
        mins = sorted(r["salary_min"] for r in stated if r["salary_min"] is not None)
        maxs = sorted(r["salary_max"] for r in stated if r["salary_max"] is not None)
        if mins:
            print(f"  min  range {mins[0]:.2f} - {mins[-1]:.2f}   median {mins[len(mins)//2]:.2f}")
        if maxs:
            print(f"  max  range {maxs[0]:.2f} - {maxs[-1]:.2f}   median {maxs[len(maxs)//2]:.2f}")
        periods = {}
        for r in stated:
            periods[r["pay_period"]] = periods.get(r["pay_period"], 0) + 1
        print(f"  pay_period: {periods}")

    print("\n### SEEN STATE\n")
    print(f"  known before this run : {known_before}")
    print(f"  new this run          : {new_this_run}")
    print(f"  tracked now           : {len(seen_state)}")
    missing = len(seen_state) - len(mapped)
    if missing > 0:
        print(f"  in state but NOT in this capture: {missing}")
        print("  (candidates for expiry. No closed state exists yet - setting it")
        print("   needs the index diff, which is a separate change.)")
    print(f"  state file: {state_path}")

    print("\n### FRESHNESS\n")
    fr = {}
    for r in mapped:
        fr[r["freshness_state"]] = fr.get(r["freshness_state"], 0) + 1
    for k, n in sorted(fr.items(), key=lambda x: -x[1]):
        print(f"  {n:>5}  {k}")

    print("\n### DEDUPE\n")
    hashes = {}
    for r in mapped:
        hashes[r["dedupe_hash"]] = hashes.get(r["dedupe_hash"], 0) + 1
    dupes = {k: v for k, v in hashes.items() if v > 1}
    print(f"  {len(hashes)} distinct hashes from {len(mapped)} records")
    print(f"  {len(dupes)} hashes with collisions, "
          f"{sum(dupes.values()) - len(dupes)} records above the first")
    if dupes:
        print("  (same company + title + location. Real on a large employer -")
        print("   multiple openings for one role. NOT automatically an error.)")

    print("\n### SOURCE TAXONOMY carried through (employer's own labels)\n")
    for field in ("source_function", "source_category"):
        vals = {}
        for r in mapped:
            v = r.get(field)
            if v:
                vals[v] = vals.get(v, 0) + 1
        print(f"  {field}: {len(vals)} distinct")
        for k, n in sorted(vals.items(), key=lambda x: -x[1])[:12]:
            print(f"    {n:>5}  {k}")
        print()

    print("### VALIDATION\n")
    if not invalid:
        print(f"  all {len(mapped)} records pass")
    else:
        print(f"  {len(invalid)} FAILED")
        seen = {}
        for _jid, probs in invalid:
            for pr in probs:
                seen[pr] = seen.get(pr, 0) + 1
        for pr, n in sorted(seen.items(), key=lambda x: -x[1])[:15]:
            print(f"    {n:>5}  {pr}")

    if all_warnings:
        print(f"\n### MAPPING WARNINGS ({len(all_warnings)})\n")
        seen = {}
        for w in all_warnings:
            seen[w] = seen.get(w, 0) + 1
        for w, n in sorted(seen.items(), key=lambda x: -x[1])[:15]:
            print(f"  {n:>4}x  {w}")

    print("\nNothing here is classified. experience_condition and category[] are")
    print("null by design - those are the extractor's job, not the adapter's.")
    log(tenant, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def mode_report(tenant):
    p = paths(tenant)
    jobs = load_index(tenant) if os.path.isdir(p["index"]) else []
    scoped = [j for j in jobs if in_scope(j, tenant)]
    details = len([f for f in os.listdir(p["detail"])]) if os.path.isdir(p["detail"]) else 0
    finder_extra = tenant.get("finder_extra") or {}
    print(f"tenant          : {tenant['key']}")
    print(f"NLx WA jobs     : {tenant.get('nlx_wa_jobs')}  (expected, from facet)")
    print(f"finder_extra    : {finder_extra or '(none - full-board capture)'}")
    if finder_extra:
        print(f"                  ^ SERVER-SIDE SCOPED capture. index below is the")
        print(f"                    {finder_extra} subset, NOT the whole board.")
    print(f"index captured  : {len(jobs)}")
    print(f"in scope        : {len(scoped)}")
    print(f"detail on disk  : {details}")
    print(f"raw path        : {p['base']}")
    return 0


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Oracle Fusion ORC adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify endpoint on this tenant")
    g.add_argument("--inspect", action="store_true", help="print real field names from one record")
    g.add_argument("--index", action="store_true", help="enumerate the whole board")
    g.add_argument("--detail", action="store_true", help="fetch detail for in-scope records")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--survey", action="store_true", help="read the captured corpus: structure + experience vocabulary")
    g.add_argument("--normalize", action="store_true", help="map captured records into the normalized contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "index", "detail", "report", "survey", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
