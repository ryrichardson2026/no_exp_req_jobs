"""
UKG Pro Recruiting (UltiPro) JobBoard adapter - No-Experience Job Network.

SCOPE: fetch and write raw JSON/HTML to disk. Nothing else. No experience logic
(that is normalize.enrich with this tenant's forked openers).

PLATFORM NAMING - read before adding a tenant. Named for the READ SURFACE. The
apply flow is native UKG Pro ("I'm interested" -> oneclick-ui); the marketing
front end differs per employer (PrimeFlight = Drupal, Menzies = corporate site)
and is NOT the read surface. Confirmed 2026-09-16 by following the apply link.

FETCH SHAPE (reverse-engineered + verified COLD from Python 2026-09-16):
  index  POST https://{host}/{company_code}/JobBoard/{board_guid}/JobBoardView/LoadSearchResults
         body {"opportunitySearch":{"Top":N,"Skip":M,"QueryString":"",
               "OrderBy":[{"PropertyName":"PostedDate","Ascending":false}],"Filters":[]}}
         -> {"opportunities":[...],"totalCount":N,"locations":[...]}   (cookieless JSON)
         page by Top/Skip to totalCount. Top is capped by the vendor (~100 observed).
  scope  CLIENT-SIDE on opportunity.Locations[].Address.State.Code (== 'WA'/'TX') and
         .Country.Code (== 'USA'). A field read, not a token - no geo-drift, no radius.
         SCOPE BEFORE DETAIL: the national board is 400-500 records; detail is fetched
         ONLY for in-scope opportunities (SOP: no unscoped detail pull).
  detail GET https://{host}/{company_code}/JobBoard/{board_guid}/OpportunityDetail?opportunityId={Id}
         Returns the SPA HTML with the opportunity model embedded in a <script>; the
         full requirements description is the JSON-string "Description" field
         (unicode-escaped HTML). BriefDescription on the index is a truncated summary,
         so detail is required for the requirements section.

INVARIANTS honored: totalCount is a DIAGNOSTIC, never a stop condition (completeness =
page-to-empty via fetch_paged); a transient 5xx truncates + aborts WITHOUT writing a
partial set as complete; config is data (no branching on tenant identity).

Usage:
  python -m adapters.ultipro --tenant primeflight_tx --probe
  python -m adapters.ultipro --tenant primeflight_tx --inspect
  python -m adapters.ultipro --tenant primeflight_tx --index
  python -m adapters.ultipro --tenant primeflight_tx --detail
  python -m adapters.ultipro --tenant primeflight_tx --report
  python -m adapters.ultipro --tenant primeflight_tx --normalize
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "ultipro")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

PLATFORM = "ultipro"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0 Safari/537.36")
DELAY_SECONDS = 1.0
PAGE_SIZE = 100          # LoadSearchResults Top; vendor caps larger values to empty
MAX_PAGES = 200          # safety stop, not a business rule
TIMEOUT = 45


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

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
    return {
        "base": base,
        "index": os.path.join(base, "index.jsonl"),     # in-scope opportunities (one JSON/line)
        "detail": os.path.join(base, "detail"),          # {opportunityId}.json per in-scope job
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
# fetch - stdlib urllib wrapped to a response with .status_code that never
# raises on non-200, so paginate.fetch_paged can retry/abort uniformly.
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return self._body

    @property
    def content(self):
        return self._body.encode("utf-8", "replace")

    def json(self):
        return json.loads(self._body)


def _http(url, *, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json, text/html"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return _Resp(getattr(r, "status", 200), r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return _Resp(e.code, body)


def _board_base(t):
    return f"https://{t['host']}/{t['company_code']}/JobBoard/{t['board_guid']}"


def _search_body(skip, top):
    return {"opportunitySearch": {
        "Top": top, "Skip": skip, "QueryString": "",
        "OrderBy": [{"PropertyName": "PostedDate", "Ascending": False}],
        "Filters": [],
    }}


def fetch_search(t, skip, top=PAGE_SIZE):
    return _http(_board_base(t) + "/JobBoardView/LoadSearchResults",
                 method="POST", body=_search_body(skip, top))


def fetch_detail(t, opp_id):
    return _http(_board_base(t) + "/OpportunityDetail?opportunityId=" + opp_id)


# --------------------------------------------------------------------------
# parsing - pure functions on data/strings (no network)
# --------------------------------------------------------------------------

def opp_id(opp):
    return opp.get("Id") or opp.get("id")


def _opp_states(opp):
    out = set()
    for loc in opp.get("Locations") or []:
        st = ((loc.get("Address") or {}).get("State") or {}).get("Code")
        if st:
            out.add(st.upper())
    return out


def _opp_countries(opp):
    out = set()
    for loc in opp.get("Locations") or []:
        c = ((loc.get("Address") or {}).get("Country") or {}).get("Code")
        if c:
            out.add(c.upper())
    return out


def in_scope(opp, tenant):
    """Field-based location scope: any location whose State.Code is in match_any
    (and, when country is set, whose Country.Code matches). No token, no radius."""
    f = tenant.get("location_filter") or {}
    want = {s.upper() for s in (f.get("state_codes") or [])}
    if not want:
        return True
    if not (_opp_states(opp) & want):
        return False
    country = (f.get("country") or "").upper()
    if country and country not in _opp_countries(opp):
        return False
    return True


def extract_description(detail_html):
    """Pull the full requirements HTML from the embedded opportunity model.

    The OpportunityDetail page is a knockout SPA whose model is bootstrapped in a
    <script> as JSON; the description is the JSON-string "Description" field
    (unicode-escaped HTML). Scan from the key to the matching unescaped quote so a
    quote inside the HTML never truncates it."""
    key = '"Description":"'
    i = detail_html.find(key)
    if i < 0:
        return None
    j = i + len(key)
    buf = []
    while j < len(detail_html):
        c = detail_html[j]
        if c == "\\":
            buf.append(detail_html[j:j + 2]); j += 2; continue
        if c == '"':
            break
        buf.append(c); j += 1
    try:
        return json.loads('"' + "".join(buf) + '"')
    except json.JSONDecodeError:
        return None


def strip_html(s):
    if not s:
        return None
    out, depth = [], 0
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    txt = "".join(out)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#39;", "'"), ("&quot;", '"'),
                 ("&lt;", "<"), ("&gt;", ">"), ("&rsquo;", "'"), ("&ldquo;", '"'),
                 ("&rdquo;", '"'), ("&ndash;", "-"), ("&mdash;", "-")):
        txt = txt.replace(a, b)
    return " ".join(txt.split()) or None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def mode_probe(t):
    print(f"tenant : {t['key']}  ({t.get('label','')})")
    print(f"board  : {_board_base(t)}")
    print(f"scope  : {t.get('location_filter')}")
    print()
    r = fetch_search(t, 0)
    print(f"status : {r.status_code}")
    if r.status_code != 200:
        print(r.text[:400]); return 1
    try:
        d = r.json()
    except Exception:
        print("FAIL 200 but body is not JSON:"); print(r.text[:400]); return 1
    opps = d.get("opportunities", [])
    total = d.get("totalCount")
    print(f"page size (measured) : {len(opps)}   totalCount (DIAGNOSTIC only) : {total}")
    scoped = [o for o in opps if in_scope(o, t)]
    print(f"in scope on page 1   : {len(scoped)}/{len(opps)}")
    if opps:
        o = opps[0]
        print(f"\nfirst record: {opp_id(o)}  {(o.get('Title') or '')[:70]}")
        print(f"  states={sorted(_opp_states(o))} countries={sorted(_opp_countries(o))}")
    # advance check
    if total and total > len(opps):
        time.sleep(DELAY_SECONDS)
        r2 = fetch_search(t, len(opps))
        opps2 = r2.json().get("opportunities", []) if r2.status_code == 200 else []
        same = {opp_id(x) for x in opps} == {opp_id(x) for x in opps2}
        print(f"\npage 2 (skip {len(opps)}): {len(opps2)} records, identical to page 1: {same}")
        if same:
            print("  PAGINATION DEFECT - Skip is not advancing. Stop."); return 1
    print("\nProbe OK.")
    log(t, "probe", status=r.status_code, page_size=len(opps), total=total,
        in_scope_page1=len(scoped))
    return 0


def mode_inspect(t):
    """Fetch one in-scope opportunity's detail and confirm the description parses,
    with a peek at heading structure (calibrate openers from THIS employer)."""
    d = fetch_search(t, 0).json()
    scoped = [o for o in d.get("opportunities", []) if in_scope(o, t)]
    if not scoped:
        # widen: scan a few pages for the first in-scope
        skip, total = len(d.get("opportunities", [])), d.get("totalCount", 0)
        while skip < total and not scoped and skip < MAX_PAGES * PAGE_SIZE:
            page = fetch_search(t, skip).json().get("opportunities", [])
            scoped = [o for o in page if in_scope(o, t)]
            skip += PAGE_SIZE
    if not scoped:
        print("no in-scope opportunity found to inspect"); return 1
    o = scoped[0]
    print(f"opportunity : {opp_id(o)}  {o.get('Title')}")
    print(f"index fields: {sorted(o.keys())}")
    html = fetch_detail(t, opp_id(o)).text
    desc = extract_description(html)
    print(f"detail Description extracted: {bool(desc)}  html_chars={len(desc or '')}")
    if desc:
        import re
        heads = re.findall(r"(?is)<(?:b|strong|h[1-5]|p)[^>]*>\s*([A-Z][^<]{2,45}?)\s*</", desc)
        reqish = [h.strip() for h in heads
                  if re.search(r"qualif|requir|experien|skill|educ|respons|essential|what|who", h, re.I)]
        print(f"requirement-ish headings (derive openers from these): {reqish[:12]}")
        print(f"\ntext head: {strip_html(desc)[:200]}")
    return 0


def mode_index(t):
    """Page the whole board (cheap), keep only in-scope opportunities, write index.
    Scope BEFORE detail so the detail pull is never national."""
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    kept, seen_ids = [], set()
    total = None
    try:
        for page in range(MAX_PAGES):
            skip = page * PAGE_SIZE
            r = fetch_paged(lambda: fetch_search(t, skip), label=f"skip {skip}: ")
            d = r.json()
            total = d.get("totalCount", total)
            opps = d.get("opportunities", [])
            if not opps:
                break
            for o in opps:
                oid = opp_id(o)
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)
                if in_scope(o, t):
                    kept.append(o)
            print(f"  page {page+1}: {len(opps)} opps, cumulative in-scope {len(kept)} "
                  f"(board total {total})")
            if len(seen_ids) >= (total or 0):
                break
            time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT index: {e}. Partial capture DISCARDED (prior data kept).")
        log(t, "index_abort", detail=str(e))
        return 1
    # write AFTER a complete walk (outside the try) - a truncation skips this
    with open(p["index"], "w", encoding="utf-8") as fh:
        for o in kept:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"\nindex complete: board {total}, in-scope {len(kept)} -> {p['index']}")
    log(t, "index", board_total=total, in_scope=len(kept))
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.exists(p["index"]):
        return []
    with open(p["index"], "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def mode_detail(t):
    """Fetch + cache the OpportunityDetail for each in-scope opportunity. Incremental:
    a cached detail is not re-fetched (clean-capture/reconcile prunes departed jobs)."""
    p = paths(t)
    os.makedirs(p["detail"], exist_ok=True)
    idx = load_index(t)
    if not idx:
        print("no index on disk - run --index first"); return 1
    fetched = failed = cached = 0
    for i, o in enumerate(idx, 1):
        oid = opp_id(o)
        dest = os.path.join(p["detail"], oid + ".json")
        if os.path.exists(dest):
            cached += 1
            continue
        try:
            r = fetch_paged(lambda: fetch_detail(t, oid), label=f"detail {i}/{len(idx)}: ")
        except Truncated as e:
            print(f"\n!! ABORT detail: {e}. Stopping (kept prior cache).")
            log(t, "detail_abort", detail=str(e)); return 1
        desc = extract_description(r.text)
        if not desc:
            failed += 1
        rec = {"Id": oid, "Title": o.get("Title"),
               "RequisitionNumber": o.get("RequisitionNumber"),
               "description_html": desc, "index": o}
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        fetched += 1
        if i % 25 == 0:
            print(f"  detail {i}/{len(idx)}")
        time.sleep(DELAY_SECONDS)
    print(f"detail: {fetched} fetched, {cached} cached, {failed} with no description")
    log(t, "detail", fetched=fetched, cached=cached, no_description=failed)
    return 0


def _detail_records(t):
    p = paths(t)
    if not os.path.isdir(p["detail"]):
        return []
    out = []
    live = {opp_id(o) for o in load_index(t)}      # only in-scope survivors
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".json"):
            continue
        if fn[:-5] not in live:                      # zombie from a prior scope - skip
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def map_record(rec, t, retrieved_at):
    """UltiPro detail+index record -> normalized contract. Every field name lives here."""
    o = rec.get("index") or {}
    r = model.new_record()
    warnings = []
    r["source_id"] = PLATFORM
    r["source_job_id"] = rec.get("Id")
    r["company_name"] = t.get("company_name") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = rec.get("Title") or o.get("Title")

    r["description_html"] = rec.get("description_html")
    r["description_text"] = strip_html(rec.get("description_html"))
    # UltiPro carries no separate segmented qualifications block - requirements live
    # in the description; openers (config) sectionize it at enrich time.
    r["qualifications"] = []
    r["qualifications_html"] = None

    locs = o.get("Locations") or []
    addr = (locs[0].get("Address") if locs else {}) or {}
    r["location_raw"] = (locs[0].get("LocalizedDescription") if locs else None) \
        or ", ".join(x for x in [addr.get("City"), (addr.get("State") or {}).get("Code")] if x)
    r["city"] = addr.get("City")
    st = ((addr.get("State") or {}).get("Code") or "").strip().upper()
    r["state"] = st or None
    coords = (locs[0].get("Coordinates") if locs else {}) or {}
    r["lat"] = coords.get("Latitude")
    r["lng"] = coords.get("Longitude")

    r["employment_type"] = "Full-time" if o.get("FullTime") else (o.get("OpportunityType") or None)
    r["shift_raw"] = None
    r["posted_at"] = o.get("PostedDate")
    r["freshness_state"] = "UNKNOWN"

    detail_url = _board_base(t) + "/OpportunityDetail?opportunityId=" + str(rec.get("Id"))
    r["apply_url"] = detail_url
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = (o.get("JobCategoryName") or "").strip() or None
    r["source_function"] = None
    r["source_url"] = detail_url
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    if not r["state"]:
        warnings.append(f"{rec.get('Id')}: no state resolved")
    return r, warnings


def mode_report(t):
    idx = load_index(t)
    det = _detail_records(t)
    with_desc = sum(1 for d in det if (d.get("description_html") or "").strip())
    print(f"tenant           : {t['key']}")
    print(f"location filter  : {t.get('location_filter')}")
    print(f"in-scope index   : {len(idx)}")
    print(f"detail cached    : {len(det)}   with description: {with_desc}/{len(det)}")
    return 0


def mode_normalize(t):
    det = _detail_records(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    p = paths(t)
    src = p["index"]
    retrieved = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(
        os.path.getmtime(src))) if os.path.exists(src) else now

    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for rec in det:
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

    print(f"{len(det)} detail records -> {len(mapped)} normalized -> {out_path}")
    print("\nFILL RATE\n")
    for f, n, pct in model.fill_report(mapped):
        print(f"  {n:>5}  {pct:>5.1f}%  {f}")
    print(f"\nvalidation failures: {len(invalid)}")
    if warns:
        print(f"mapping warnings: {len(warns)}")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="UKG Pro (UltiPro) JobBoard adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify endpoint, page size, pagination, scope")
    g.add_argument("--inspect", action="store_true", help="one in-scope detail: description + headings")
    g.add_argument("--index", action="store_true", help="page the board, keep in-scope, write index")
    g.add_argument("--detail", action="store_true", help="fetch+cache OpportunityDetail per in-scope job")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()
    t = load_tenant(a.tenant)
    if a.probe:
        return mode_probe(t)
    if a.inspect:
        return mode_inspect(t)
    if a.index:
        return mode_index(t)
    if a.detail:
        return mode_detail(t)
    if a.report:
        return mode_report(t)
    if a.normalize:
        return mode_normalize(t)


if __name__ == "__main__":
    sys.exit(main())
