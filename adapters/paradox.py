"""
Paradox (Olivia) careers-board adapter - No-Experience Job Network.

SCOPE: fetch and write raw job JSON to disk. Nothing else. No experience logic
(that is normalize.enrich with this tenant's forked openers).

PLATFORM NAMING - read before adding a tenant. Named for the READ SURFACE. careers.{brand}.com
is a Paradox/Olivia widget (cdn.olivia.paradox.ai) backed by a JSON jobs API; the apply flow
is Paradox conversational ("Olivia"). Confirmed 2026-09-17 by Chrome network trace + cold Python.
SERVES a diverse portfolio on the SAME shape (per-brand careers host): Shake Shack, Chipotle,
Inspire Brands (Arby's/BWW/Sonic/Dunkin/Jimmy John's), Panda Express.

FETCH SHAPE (reverse-engineered + verified in Chrome + COLD from Python 2026-09-17):
  data   POST {careers_host}/api/get-jobs?radius=15&page_number=N&enable_kilometers=false
         body {} ; needs a primed session (GET {careers_host}/jobs for cookies) + Referer +
         Origin headers (cold 403s without them). Returns {jobs:[...], facets, totalJob}, 10/page.
         The job DESCRIPTION is INLINE in the list record - NO separate detail fetch (single-pass).
  scope  CLIENT-SIDE on job.locations[].stateAbbr in markets (+ countryAbbr == 'US'). A field
         read, not the site's geo-radius (radius= param) which bleeds across state/national lines.
         Page to totalJob; totalJob is a DIAGNOSTIC cross-check, not the stop condition.

INVARIANTS honored: vendor total is a DIAGNOSTIC (completeness = page-to-empty); a transient
failure truncates + aborts WITHOUT writing a partial set as complete; config is data (careers
host + market abbreviations live in config, no branching on tenant identity).

Usage:
  python -m adapters.paradox --tenant shake_shack --probe
  python -m adapters.paradox --tenant shake_shack --inspect
  python -m adapters.paradox --tenant shake_shack --index
  python -m adapters.paradox --tenant shake_shack --report
  python -m adapters.paradox --tenant shake_shack --normalize
"""
import argparse
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "paradox")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except Exception:  # pragma: no cover
    import requests as http
    _IMPERSONATE = {}

PLATFORM = "paradox"
DELAY_SECONDS = 0.4
PAGE_SIZE = 10           # vendor-fixed page size
MAX_PAGES = 400          # safety stop, not a business rule
TIMEOUT = 30


def load_tenant(name):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    tenants = cfg.get(PLATFORM, {})
    if name not in tenants:
        known = ", ".join(k for k in tenants if not k.startswith("_"))
        sys.exit(f"tenant '{name}' not in {CONFIG_PATH} [{PLATFORM}]. Known: {known}")
    t = dict(tenants[name])
    t["key"] = name
    return t


def paths(tenant):
    base = os.path.join(RAW_ROOT, tenant["key"])
    return {"base": base,
            "index": os.path.join(base, "records.jsonl"),   # in-scope jobs w/ description
            "run": os.path.join(base, "run_log.jsonl")}


def log(tenant, event, **fields):
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------
# fetch - primed session (cookies) + Referer/Origin (cold 403s without them)
# --------------------------------------------------------------------------

_SESSION = None


def _session(t):
    global _SESSION
    if _SESSION is None:
        _SESSION = http.Session(**_IMPERSONATE)
        try:
            _SESSION.get(t["careers_host"].rstrip("/") + "/jobs", timeout=TIMEOUT)
        except Exception:
            pass
    return _SESSION


def _headers(t):
    host = t["careers_host"].rstrip("/")
    return {"Referer": host + "/jobs", "Origin": host,
            "Content-Type": "application/json", "Accept": "application/json"}


# abbr -> full state name for the server-side facet (filter[state][0]=Washington). Only our
# scope markets are needed; extend if a new market is added.
STATE_FULLNAME = {"WA": "Washington", "TX": "Texas"}


def fetch_page(t, n, state_full=None):
    """One page. When state_full is given, scope SERVER-SIDE via the Paradox state facet
    (filter[state][0]=<FullName>) - clean, no giant client-side scan, no geo bleed."""
    host = t["careers_host"].rstrip("/")
    path = t.get("api_path", "/api/get-jobs")
    url = f"{host}{path}?radius=15&page_number={n}&enable_kilometers=false"
    if state_full:
        url += "&" + urllib.parse.quote("filter[state][0]") + "=" + urllib.parse.quote(state_full)
    return _session(t).post(url, json={}, timeout=TIMEOUT, headers=_headers(t))


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _posted_date(job):
    """customFields is a list of {name,value} (or occasionally a dict); dig out a posted date."""
    cf = job.get("customFields")
    if isinstance(cf, dict):
        return cf.get("postedDate") or cf.get("posted_date")
    if isinstance(cf, list):
        for f in cf:
            if isinstance(f, dict) and re.search(r"post", str(f.get("name") or f.get("key") or ""), re.I):
                return f.get("value")
    return job.get("postedDate") or job.get("datePosted")


def _markets(t):
    return {m.upper() for m in (t.get("markets") or [])}


def in_scope_location(job, t):
    """Return the first location whose stateAbbr is a target market (US only), else None."""
    want = _markets(t)
    for loc in job.get("locations") or []:
        if (loc.get("countryAbbr") or "US").upper() != "US":
            continue
        st = (loc.get("stateAbbr") or "").upper()
        if not want or st in want:
            return loc
    return None


def strip_html(s):
    if not s:
        return None
    txt = htmllib.unescape(re.sub(r"<[^>]+>", " ", s))
    return " ".join(txt.split()) or None


def total_jobs(payload):
    return payload.get("totalJob") if isinstance(payload, dict) else None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def mode_probe(t):
    print(f"tenant : {t['key']}  ({t.get('label','')})")
    print(f"host   : {t['careers_host']}   markets : {sorted(_markets(t))}")
    ok = True
    for mkt in sorted(_markets(t)):
        full = STATE_FULLNAME.get(mkt.upper(), mkt)
        r = fetch_page(t, 1, full)
        if r.status_code != 200:
            print(f"  {mkt}: status {r.status_code} FAIL"); ok = False; continue
        j = r.json()
        jobs = j.get("jobs", [])
        loc = (jobs[0].get("locations") or [{}])[0] if jobs else {}
        print(f"  {mkt} (filter[state]={full}): totalJob {total_jobs(j)}  page1 {len(jobs)}  "
              f"first={jobs[0].get('title','')[:40] if jobs else '-'} @ {loc.get('city')},{loc.get('stateAbbr')}")
    print("\nProbe OK." if ok else "\nProbe FAILED.")
    log(t, "probe", ok=ok)
    return 0 if ok else 1


def _walk(t):
    """One SERVER-SIDE-scoped pass PER market (filter[state][0]=<FullName>): page that state to
    empty. No giant national scan, no geo bleed. Jobs deduped across markets (a multi-state
    posting is kept once, tagged with the first market that returned it)."""
    kept, seen = [], set()
    grand_total = 0
    for mkt in sorted(_markets(t)):
        full = STATE_FULLNAME.get(mkt.upper(), mkt)
        mkt_total = None
        for page in range(1, MAX_PAGES + 1):
            def _f(pg=page, st=full):
                return fetch_page(t, pg, st)
            r = fetch_paged(_f, label=f"{mkt} p{page}: ")
            j = r.json()
            mkt_total = total_jobs(j) or mkt_total
            jobs = j.get("jobs", [])
            if not jobs:
                break
            for x in jobs:
                uid = x.get("uniqueID") or x.get("requisitionID")
                if uid in seen:
                    continue
                seen.add(uid)
                # server already scoped to this state; pick the location matching the market,
                # else fall back to the first location.
                loc = in_scope_location(x, t) or (x.get("locations") or [{}])[0]
                kept.append({"uniqueID": uid, "requisitionID": x.get("requisitionID"),
                             "title": x.get("title"), "description": x.get("description"),
                             "employmentType": x.get("employmentType"),
                             "originalURL": x.get("originalURL"), "companyName": x.get("companyName"),
                             "location": loc,
                             "postedAt": _posted_date(x)})
            if len(jobs) < PAGE_SIZE:
                break
            time.sleep(DELAY_SECONDS)
        print(f"  {mkt}: {mkt_total} on the board -> cumulative kept {len(kept)}")
        grand_total += (mkt_total or 0)
    return kept, grand_total


def mode_index(t):
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    try:
        kept, total = _walk(t)
    except Truncated as e:
        print(f"\n!! ABORT index: {e}. Partial capture DISCARDED (prior data kept).")
        log(t, "index_abort", detail=str(e))
        return 1
    with open(p["index"], "w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nindex complete: board {total}, in-scope {len(kept)} -> {p['index']}")
    log(t, "index", board_total=total, in_scope=len(kept))
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.exists(p["index"]):
        return []
    with open(p["index"], "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def mode_inspect(t):
    recs = load_index(t) or _walk(t)[0]
    if not recs:
        print("no in-scope records to inspect"); return 1
    r = recs[0]
    print(f"record : {r.get('requisitionID')}  {r.get('title')}")
    desc = htmllib.unescape(r.get("description") or "")
    heads = re.findall(r"(?is)<(?:b|strong|h[1-6])[^>]*>\s*([A-Z][^<]{2,50}?):?\s*</", desc)
    reqish = [h.strip() for h in heads
              if re.search(r"qualif|requir|experien|skill|educ|essential|who|looking", h, re.I)]
    print(f"requirement-ish headings (derive openers from these): {reqish[:12]}")
    print(f"\ntext head: {strip_html(desc)[:220]}")
    return 0


def _emp_type(v):
    if not v:
        return None
    key = str(v).strip().upper().replace("-", "_").replace(" ", "_")
    return {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "CONTRACTOR": "Contract",
            "TEMPORARY": "Temporary", "INTERN": "Internship"}.get(key, str(v).strip().title())


_ISO_RX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MDY_RX = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def _iso_date(v):
    """Return YYYY-MM-DD, or None when the value is not a real date.

    The Paradox `postedAt` field is NOT reliably a date across this platform's
    tenants: a genuine date (ISO or M/D/YY) on Arby's/Jimmy John's/Sonic, a Workday
    requisition id ('JR13558-1') on Shake Shack, a marketing label ('BWW Extern') on
    BWW. An unparseable value written to the timestamptz `posted_at` column makes
    Postgres 22007-reject the ENTIRE upsert row, silently dropping the job (Shake Shack:
    0 rows ever reached the DB). So anything that isn't a real date must become None
    (posted_at is legitimately nullable - the pipeline omits datePosted when absent),
    never a raw passthrough."""
    if not v:
        return None
    s = str(v).strip()
    m = _ISO_RX.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _MDY_RX.match(s)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= da <= 31:
            yr = ("20" + yr) if len(yr) == 2 else yr
            return f"{yr}-{mo:02d}-{da:02d}"
    return None


def _abs_apply_url(original, t):
    """Make the Paradox apply link ABSOLUTE. originalURL is absolute for some tenants (Chipotle:
    'https://jobs.chipotle.com/...') but RELATIVE for others (Shake Shack/Sonic/Arby's/BWW/Jimmy
    John's: 'slug/job/ID'). A relative href on a noprobjobs.com job page resolves against OUR host
    -> a dead No Prob Jobs URL, never the employer -> the Apply button 404s. Prefix the tenant's
    careers_host so Apply always leaves the site to the real ATS."""
    if not original:
        return None
    if re.match(r"^https?://", original, re.I):
        return original                                      # already absolute (Chipotle) — leave it
    host = (t.get("careers_host") or "").rstrip("/")
    return host + "/" + original.lstrip("/") if host else original


def map_record(rec, t, retrieved_at):
    r = model.new_record()
    warnings = []
    loc = rec.get("location") or {}
    r["source_id"] = PLATFORM
    r["source_job_id"] = rec.get("uniqueID") or rec.get("requisitionID")
    r["company_name"] = t.get("company_name") or rec.get("companyName") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = rec.get("title")

    r["description_html"] = rec.get("description")
    r["description_text"] = strip_html(rec.get("description"))
    r["qualifications"] = []
    r["qualifications_html"] = None

    r["city"] = loc.get("city")
    r["state"] = (loc.get("stateAbbr") or "").upper() or None
    r["location_raw"] = loc.get("locationText") or loc.get("cityStateAbbr") \
        or ", ".join(x for x in [loc.get("city"), (loc.get("stateAbbr") or "")] if x) or None
    r["lat"] = loc.get("latitude")
    r["lng"] = loc.get("longitude")

    r["employment_type"] = _emp_type(rec.get("employmentType"))
    r["shift_raw"] = None
    r["posted_at"] = _iso_date(rec.get("postedAt"))
    r["freshness_state"] = "UNKNOWN"

    apply = _abs_apply_url(rec.get("originalURL"), t)
    r["apply_url"] = apply
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = None
    r["source_function"] = None
    r["source_url"] = apply
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    if not r["state"]:
        warnings.append(f"{r['source_job_id']}: no state resolved")
    return r, warnings


def mode_report(t):
    from collections import Counter
    recs = load_index(t)
    by_state = Counter((r.get("location") or {}).get("stateAbbr") for r in recs)
    with_desc = sum(1 for r in recs if (r.get("description") or "").strip())
    print(f"tenant        : {t['key']}")
    print(f"markets       : {sorted(_markets(t))}")
    print(f"in-scope      : {len(recs)}   by state: {dict(by_state)}")
    print(f"with desc     : {with_desc}/{len(recs)}")
    return 0


def mode_normalize(t):
    recs = load_index(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = paths(t)
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(
        os.path.getmtime(p["index"]))) if os.path.exists(p["index"]) else now

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for rec in recs:
        r, w = map_record(rec, t, retrieved)
        model.apply_seen_state(r, seen_state, now)
        r["is_new"] = True if known_before == 0 else r["first_seen"] == now
        probs = model.validate(r)
        if probs:
            invalid.append((r.get("source_job_id"), probs))
        mapped.append(r)
        warns.extend(w)

    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(seen_state, fh, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in mapped:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{len(recs)} records -> {len(mapped)} normalized -> {out_path}")
    print("\nFILL RATE\n")
    for f, n, pct in model.fill_report(mapped):
        print(f"  {n:>5}  {pct:>5.1f}%  {f}")
    print(f"\nvalidation failures: {len(invalid)}")
    if warns:
        print(f"mapping warnings: {len(warns)} (e.g. {warns[0]})")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Paradox (Olivia) careers-board adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify API + per-page scope + totalJob")
    g.add_argument("--inspect", action="store_true", help="one in-scope record: description + headings")
    g.add_argument("--index", action="store_true", help="page the board, keep in-scope, write records")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()
    t = load_tenant(a.tenant)
    return {"probe": mode_probe, "inspect": mode_inspect, "index": mode_index,
            "report": mode_report, "normalize": mode_normalize}[
        next(k for k in ("probe", "inspect", "index", "report", "normalize")
             if getattr(a, k))](t)


if __name__ == "__main__":
    sys.exit(main())
