"""
Target adapter - No-Experience Job Network. TWO-SOURCE, ONE IDENTITY.

Target is the first record in the build assembled from two endpoints:

  DISCOVERY  POST https://corporate.target.com/api/jobsearch  (Target's own
             Azure Cognitive Search index, form-encoded, cookieless). Returns the
             COMPLETE WA requisition list with structured location, pay, taxonomy
             and a requisitionid in Workday's R0000... format - but NO description
             prose. This is the discovery source: it settles WHICH reqs exist and
             carries the structured fields Workday's listing does not.

  DETAIL     GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}  (the same
             Workday CXS endpoint adapters/workday.py uses). Returns the full
             jobDescription. This is the detail source.

WHY THIS IS ONE SOURCE, NOT TWO. From the contract's view source_id is `target`:
one source that makes two requests, exactly as the Workday adapter makes a listing
call and then a detail call. source_url on the record is the Workday job URL a
person would open; the discovery request URL is written to the run log so the pair
stays traceable. No per-field provenance - that stays available as a purely
additive change if a field's origin is ever disputed.

WHY A SEPARATE FILE, AND WHY THE WORKDAY DETAIL CODE IS DUPLICATED HERE.
corporate.target.com is NOT Workday - a different host, protocol, encoding and
result shape - so mixing its quirks into workday.py would break "adapters own
their source's quirks". The Workday detail fetch (session, base_urls, fetch_detail)
is duplicated from adapters/workday.py ON PURPOSE, the same way workday.py
duplicates structure from oracle_orc.py: a Target change must never be able to
break the Workday adapter. The duplication is the point.

MAPPING - discovery's STRUCTURED fields beat Workday prose:
  * basepaymin/basepaymax/basepayfrequency -> salary_min/max + pay_period with
    salary_is_stated True. Workday's jobPostingInfo carries pay only as prose.
  * city + stateabbreviated -> city/state directly, sidestepping both Target
    location string formats AND the "N Locations" multi-store gap.
  * jobarea -> source_function, primarycategory -> source_category (field reads).
  * description/qualifications come from the Workday detail record.

Usage:
  python -m adapters.target --tenant target --probe
  python -m adapters.target --tenant target --discovery
  python -m adapters.target --tenant target --detail
  python -m adapters.target --tenant target --normalize
  python -m adapters.target --tenant target --report
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
RAW_ROOT = os.path.join(ROOT, "raw", "target")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "target"          # this is source_id - one identity for both requests
DELAY_SECONDS = 1.0          # record: 1-2s; corporate API tolerated 0.5-0.6s in test
TIMEOUT = 45
MAX_PAGES = 200              # safeguard; WA is ~15 pages, national would be far more

# The corporate search API expects the WHOLE form, not just the fields that carry a
# value - unused keys are sent empty. That full-form requirement is a SOURCE QUIRK
# and lives here in the adapter, not in config; config carries only the parameters
# that actually mean something (config.discovery.form overrides these defaults).
DISCOVERY_FORM_DEFAULTS = {
    "q": "", "currentPage": "1", "state": "", "city": "", "country": "",
    "hierarchy": "", "jobcategories": "", "remotetype": "", "workersubtype": "",
    "scheduletype": "", "basepayfrequency": "", "organization": "",
    "locationname": "", "jobaddress": "", "profiles": "", "internshipType": "",
    "jobfamily": "", "subFamilies": "", "filtercondition": "", "compgrade": "",
    "culture": "en-us",
}

# basepayfrequency -> contract pay_period vocabulary (model.PAY_PERIOD).
FREQ_TO_PERIOD = {
    "hourly": "HOURLY", "daily": "DAILY", "weekly": "WEEKLY", "biweekly": "WEEKLY",
    "monthly": "MONTHLY", "annual": "ANNUAL", "annually": "ANNUAL",
    "yearly": "ANNUAL", "year": "ANNUAL", "salaried": "ANNUAL",
    # Target labels salaried leadership base pay 'Salary' (measured: 1 WA record,
    # a Store Director band). It is an annual figure, same as 'salaried'.
    "salary": "ANNUAL",
}


def load_tenant(name):
    """Target's detail IS Workday, so its host/tenant/site coordinates live under
    the 'workday' section alongside the Workday-only tenants. This adapter reads
    that same entry plus its 'discovery' block. source_id is still `target`."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get("workday", {})
    if name not in tenants:
        sys.exit(f"tenant '{name}' not under 'workday' in {CONFIG_PATH}. "
                 f"Known: {', '.join(tenants) or '(none)'}")
    t = dict(tenants[name])
    t["key"] = name
    if "discovery" not in t:
        sys.exit(f"tenant '{name}' has no 'discovery' block - this adapter needs "
                 f"the corporate search API config.")
    return t


# ---------------------------------------------------------------------------
# Workday DETAIL fetch - duplicated from adapters/workday.py on purpose (see top).
# ---------------------------------------------------------------------------

def base_urls(t):
    style = t.get("url_style", "myworkdayjobs")
    lang = t.get("language", "en-US")
    host = t["host"]
    if style == "myworkdaysite":
        careers = f"https://{host}/{lang}/recruiting/{t['tenant']}/{t['site']}"
    else:
        careers = f"https://{host}/{lang}/{t['site']}"
    cxs = f"https://{host}/wday/cxs/{t['tenant']}/{t['site']}"
    return careers, cxs


def open_session(t):
    """GET the careers page to establish Workday session cookies before the detail
    GETs. Cloudflare fronts the host, so curl-cffi with a Chrome fingerprint is
    required. Verified on Target: session GET 200, no CSRF token needed, detail
    GETs then return 200."""
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
    return s, r.status_code


def fetch_detail(s, t, external_path):
    _, cxs = base_urls(t)
    path = external_path if external_path.startswith("/") else "/" + external_path
    return s.get(f"{cxs}{path}", timeout=TIMEOUT, **_IMPERSONATE)


def ext_path_from_applyurl(applyurl, t):
    """Workday externalPath from the discovery record's applyurl. The apply URL is
    https://{host}/{site}/job/<slug>_<reqid>/apply ; the CXS detail path is the
    segment after the site slug with the trailing /apply removed. Verified: this
    path fed to fetch_detail returned 200 with jobPostingInfo on 10/10 sampled
    reqs. Returns None if the URL does not carry the expected shape."""
    if not isinstance(applyurl, str) or "/job/" not in applyurl:
        return None
    marker = f"/{t['site']}/job/"
    idx = applyurl.find(marker)
    if idx == -1:
        # host/site slug differs from config; fall back to the generic /job/ split
        idx = applyurl.find("/job/")
        tail = applyurl[idx:]
    else:
        tail = applyurl[idx + len(f"/{t['site']}"):]
    if tail.endswith("/apply"):
        tail = tail[: -len("/apply")]
    return tail or None


def base_reqid_from_applyurl(applyurl):
    """The BASE Workday requisition id (R0000...) from the applyurl slug.

    Single-location postings carry a plain base id as their discovery
    requisitionid (R0000451296). MULTI-location postings carry a COMPOSITE id -
    base + a per-store suffix, e.g. R0000450583-98004-5213 - one discovery row per
    store, but all sharing ONE Workday requisition and one detail record whose
    jobReqId is the bare base. Joining discovery->detail on the composite id misses
    every multi-location posting; joining on the base id (which is what jobReqId is)
    resolves them. The applyurl slug always ends '..._R0000XXXX/apply', so the base
    is the last R0000... token in the URL."""
    if not isinstance(applyurl, str):
        return None
    hits = re.findall(r"R0000\d+", applyurl)
    return hits[-1] if hits else None


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


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s))[:120]


# ---------------------------------------------------------------------------
# DISCOVERY - Target corporate search API
# ---------------------------------------------------------------------------

def discovery_session():
    s = http.Session()
    s.headers.update({
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://corporate.target.com",
        "referer": "https://corporate.target.com/careers/job-search",
        "accept": "application/json",
    })
    return s


def discovery_form(t, page):
    d = t["discovery"]
    form = dict(DISCOVERY_FORM_DEFAULTS)
    form.update(d.get("form") or {})
    form[d.get("page_param", "currentPage")] = str(page)
    return form


def fetch_discovery_page(s, t, page):
    d = t["discovery"]
    return s.post(d["url"], data=discovery_form(t, page), timeout=TIMEOUT,
                  **_IMPERSONATE)


def discovery_docs(payload):
    """One result's job fields live under `document`. Return the list of documents."""
    return [r.get("document") or {} for r in (payload.get("results") or [])]


def discovery_count(payload):
    return payload.get("count")


# ---------------------------------------------------------------------------
# paths / log
# ---------------------------------------------------------------------------

def paths(t):
    base = os.path.join(RAW_ROOT, t["key"])
    return {"base": base,
            "discovery": os.path.join(base, "discovery"),
            "detail": os.path.join(base, "detail"),
            "run": os.path.join(base, "run_log.jsonl")}


def log(t, event, **fields):
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event,
           "source_id": PLATFORM}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def load_discovery(t):
    p = paths(t)
    if not os.path.isdir(p["discovery"]):
        sys.exit("no discovery on disk - run --discovery first")
    docs = []
    for fn in sorted(os.listdir(p["discovery"])):
        if fn.endswith(".json"):
            with open(os.path.join(p["discovery"], fn), "r", encoding="utf-8") as fh:
                docs.extend(discovery_docs(json.load(fh)))
    return docs


def load_detail_map(t):
    """{requisitionid: jobPostingInfo} from the captured Workday detail records."""
    p = paths(t)
    if not os.path.isdir(p["detail"]):
        sys.exit("no detail records - run --detail first")
    out = {}
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            try:
                body = json.load(fh)
            except Exception:
                continue
        info = body.get("jobPostingInfo") or body
        rid = info.get("jobReqId") or fn[:-5]
        out[rid] = info
    return out


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def map_record(doc, info, t, retrieved_at):
    """discovery document (doc) + Workday detail (info) -> normalized contract.
    Structured discovery fields are preferred; description comes from the detail."""
    r = model.new_record()
    warnings = []
    info = info or {}

    rid = doc.get("requisitionid") or info.get("jobReqId")

    r["source_id"] = PLATFORM
    r["source_job_id"] = str(rid) if rid else None
    r["company_name"] = t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = doc.get("title") or info.get("title")

    jd = info.get("jobDescription")
    r["description_html"] = jd
    r["description_text"] = strip_html(jd)
    # Workday has no segmented qualifications field - requirements live in the body.
    r["qualifications"] = []
    r["qualifications_html"] = None

    # location - discovery's STRUCTURED fields, no string-format guessing.
    r["location_raw"] = doc.get("jobaddress") or info.get("location")
    r["city"] = doc.get("city")
    r["state"] = doc.get("stateabbreviated")
    r["lat"] = doc.get("latitude")
    r["lng"] = doc.get("longitude")
    if not r["state"] and r["location_raw"]:
        warnings.append(f"no stateabbreviated on discovery record for {rid}")

    r["employment_type"] = doc.get("scheduletype") or info.get("timeType")
    r["shift_raw"] = None
    r["posted_at"] = doc.get("dateposted") or info.get("startDate") or info.get("postedOn")
    r["freshness_state"] = "UNKNOWN"

    # pay - discovery carries structured numbers; Workday carries only prose.
    lo, lo_stated = model.parse_money(doc.get("basepaymin"))
    hi, hi_stated = model.parse_money(doc.get("basepaymax"))
    if lo is not None or hi is not None:
        r["salary_min"] = lo
        r["salary_max"] = hi
        r["salary_is_stated"] = True
        freq = (doc.get("basepayfrequency") or "").strip().lower()
        r["pay_period"] = FREQ_TO_PERIOD.get(freq, "UNKNOWN")
        if r["pay_period"] == "UNKNOWN":
            warnings.append(f"salary stated but basepayfrequency unmapped: "
                            f"{doc.get('basepayfrequency')!r}")

    # apply / source url - the Workday job URL a person would open.
    ext = info.get("externalUrl")
    if not ext:
        au = doc.get("applyurl") or ""
        ext = au[:-len("/apply")] if au.endswith("/apply") else (au or None)
    r["apply_url"] = ext
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")

    # source taxonomy - field reads, so source_category_method stays None.
    r["source_category"] = doc.get("primarycategory")
    r["source_function"] = doc.get("jobarea")

    r["source_url"] = ext
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"],
                                         r["location_raw"])
    return r, warnings


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def mode_probe(t):
    d = t["discovery"]
    print(f"tenant     : {t['key']}  ({t.get('label','')})  source_id={PLATFORM}")
    print(f"discovery  : {d['method']} {d['url']}")
    print(f"form       : {d.get('form')}")
    print(f"detail via : {base_urls(t)[1]}{{externalPath}}\n")

    s = discovery_session()
    try:
        r = fetch_discovery_page(s, t, 1)
    except Exception as e:
        print(f"FAIL  discovery POST raised: {type(e).__name__}: {e}")
        return 1
    print(f"discovery status : {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return 1
    payload = r.json()
    docs = discovery_docs(payload)
    count = discovery_count(payload)
    print(f"declared count   : {count}")
    print(f"page 1 returned  : {len(docs)}")
    if not docs:
        print("\n200 but zero results - check the form params.")
        return 1

    doc0 = docs[0]
    rid = doc0.get("requisitionid")
    print(f"\nfirst reqid      : {rid}")
    print(f"applyurl         : {doc0.get('applyurl')}")

    # one detail fetch to prove the join end to end
    ws, status = open_session(t)
    print(f"\nworkday session  : {status}")
    ep = ext_path_from_applyurl(doc0.get("applyurl"), t)
    print(f"derived path     : {ep}")
    if status != 200 or not ep:
        print("cannot test detail join")
        return 1
    dd = fetch_detail(ws, t, ep)
    print(f"detail status    : {dd.status_code}, {len(dd.content)} bytes")
    if dd.status_code == 200:
        info = dd.json().get("jobPostingInfo") or {}
        jrid = info.get("jobReqId")
        jd = info.get("jobDescription") or ""
        print(f"detail jobReqId  : {jrid}   match={jrid == rid}")
        print(f"jobDescription   : {len(jd)} chars")
        print("\nProbe OK. Discovery returns records and the detail join resolves.")
    log(t, "probe", discovery_url=d["url"], count=count, returned=len(docs),
        detail_status=dd.status_code)
    return 0


def mode_discovery(t):
    s = discovery_session()
    p = paths(t)
    os.makedirs(p["discovery"], exist_ok=True)
    d = t["discovery"]

    page, seen, count = 1, 0, None
    while page <= MAX_PAGES:
        r = fetch_discovery_page(s, t, page)
        if r.status_code != 200:
            print(f"stopped at page {page}: status {r.status_code}")
            log(t, "discovery_error", page=page, status=r.status_code)
            break
        payload = r.json()
        docs = discovery_docs(payload)
        if count is None:
            count = discovery_count(payload)
            print(f"declared count: {count}")
        if not docs:
            print(f"empty page {page} - done")
            break
        with open(os.path.join(p["discovery"], f"page_{page:04d}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        seen += len(docs)
        print(f"  page {page:>3}  +{len(docs):>3}  running {seen}")
        page += 1
        time.sleep(DELAY_SECONDS)

    print(f"\ndiscovery complete: {seen} of {count} -> {p['discovery']}")
    # The discovery request URL is logged so the two-source pair stays traceable.
    log(t, "discovery", discovery_url=d["url"], form=d.get("form"),
        declared=count, captured=seen, pages=page - 1)
    return 0


def mode_detail(t):
    ws, status = open_session(t)
    if status != 200:
        print(f"workday session GET {status} - stopping")
        return 1
    p = paths(t)
    os.makedirs(p["detail"], exist_ok=True)

    docs = load_discovery(t)
    print(f"discovery: {len(docs)} records to resolve against the Workday board")

    done = skipped = failed = notfound = 0
    for i, doc in enumerate(docs, 1):
        rid = doc.get("requisitionid")
        ep = ext_path_from_applyurl(doc.get("applyurl"), t)
        if not rid or not ep:
            failed += 1
            log(t, "detail_skip", req=rid, reason="no reqid or path")
            continue
        out = os.path.join(p["detail"], f"{safe_name(rid)}.json")
        if os.path.exists(out):
            skipped += 1
            continue
        r = fetch_detail(ws, t, ep)
        if r.status_code != 200:
            failed += 1
            notfound += (r.status_code == 404)
            print(f"  [{i}/{len(docs)}] {rid} status {r.status_code}"
                  f"{'  (404 - stale search index vs live board)' if r.status_code == 404 else ''}")
            log(t, "detail_error", req=rid, status=r.status_code)
        else:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(r.text)
            done += 1
            if done % 25 == 0:
                print(f"  [{i}/{len(docs)}] {done} fetched")
        time.sleep(DELAY_SECONDS)

    print(f"\ndetail complete: {done} fetched, {skipped} on disk, "
          f"{failed} failed ({notfound} of them 404)")
    log(t, "detail", discovered=len(docs), fetched=done, skipped=skipped,
        failed=failed, notfound=notfound)
    return 0


def mode_normalize(t):
    docs = load_discovery(t)
    detail = load_detail_map(t)
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

    mapped, invalid, warns, no_detail = [], [], [], 0
    for doc in docs:
        # Detail is keyed by Workday jobReqId (the BASE id). Discovery multi-location
        # rows carry a composite id, so join on the base id from the applyurl and
        # fall back to the discovery id for any single-location row.
        base = base_reqid_from_applyurl(doc.get("applyurl"))
        info = detail.get(base) or detail.get(doc.get("requisitionid"))
        if info is None:
            no_detail += 1
        rec, w = map_record(doc, info, t, retrieved)
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

    print(f"{len(docs)} discovery x {len(detail)} detail -> {len(mapped)} "
          f"normalized -> {out_path}")
    print(f"records with no matching detail: {no_detail}")
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
    log(t, "normalize", records=len(mapped), invalid=len(invalid),
        no_detail=no_detail)
    return 0


def mode_report(t):
    p = paths(t)
    docs = load_discovery(t) if os.path.isdir(p["discovery"]) else []
    detail = len(os.listdir(p["detail"])) if os.path.isdir(p["detail"]) else 0
    print(f"tenant          : {t['key']}   source_id={PLATFORM}")
    print(f"discovery form  : {t['discovery'].get('form')}")
    print(f"nlx_wa_jobs     : {t.get('nlx_wa_jobs')}  (expected)")
    print(f"discovery recs  : {len(docs)}")
    print(f"detail on disk  : {detail}")
    print(f"raw path        : {p['base']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Target two-source adapter "
                                             "(corporate discovery + Workday detail)")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    for m, h in (("probe", "discovery page 1 + one end-to-end detail join"),
                 ("discovery", "page the corporate search API to the end"),
                 ("detail", "fetch Workday detail for every discovered req"),
                 ("report", "counts from disk"),
                 ("normalize", "map discovery+detail into the contract")):
        g.add_argument(f"--{m}", action="store_true", help=h)
    a = ap.parse_args()

    t = load_tenant(a.tenant)
    for m in ("probe", "discovery", "detail", "report", "normalize"):
        if getattr(a, m):
            return globals()[f"mode_{m}"](t)


if __name__ == "__main__":
    sys.exit(main())
