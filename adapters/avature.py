"""
Avature ATS (native career portal) adapter - No-Experience Job Network.

SCOPE: fetch and write raw HTML to disk. Nothing else. No experience logic
(that is normalize.enrich with this tenant's forked openers).

PLATFORM NAMING - read before adding a tenant. Named for the READ SURFACE. Avature
serves the search + job-detail pages server-rendered from careers.{host}; the apply
flow ("It only takes 90 seconds to apply") is native Avature. Confirmed 2026-09-17
by Chrome validation of the live site (see [[validate-website-in-chrome-before-probe]]).

FETCH SHAPE (reverse-engineered + verified in Chrome + COLD from Python 2026-09-17):
  scope  SERVER-SIDE via the State facet: POST {search_url} form field
         state_field = markets[MARKET]  (a per-instance Avature field id + option value,
         e.g. Unifi state field "733", Washington "6307", Texas "6303"). One search per
         market, results combined. The result set is already state-clean - no client
         filter, no geo-radius (the website's WHERE box is a distance radius that bleeds
         across state/country lines; the State FACET is the true scope - proven on
         PrimeFlight where WHERE=Washington returned 34 across WA/OR/BC/ID/AB/MT).
  index  POST {search_url}  data {state_field:value, jobOffset:N}
         -> HTML with <article class="article--result"> cards; each has an <h3> title
         link href=".../careers/JobDetail/{slug}/{id}". Page by jobOffset (page size is
         fixed at ~20; jobRecordsPerPage is ignored by the vendor) to an empty page.
         totalCount ("N results") is a DIAGNOSTIC, never a stop condition.
  detail GET {detail_base}JobDetail/{slug}/{id}  (Referer = careers_url, paced) -> the
         job page; the requirements HTML is the "Requirements and Description" section,
         inside <div class="article__content__view__field">. No JSON-LD.

BOT-THROTTLE: the detail route 403/"Sorry"-pages rapid-fire requests. A primed session
(GET careers_url first, cookies kept), a Referer header, and DELAY_SECONDS pacing make it
reliable (6/6 cold-tested). fetch_paged retries 5xx and aborts on truncation.

INVARIANTS honored: vendor total is a DIAGNOSTIC (completeness = page-to-empty); a
transient failure truncates + aborts WITHOUT writing a partial set as complete; config
is data (state field id + option values live in config, no branching on tenant identity).

Usage:
  python -m adapters.avature --tenant unifi --probe
  python -m adapters.avature --tenant unifi --inspect
  python -m adapters.avature --tenant unifi --index
  python -m adapters.avature --tenant unifi --detail
  python -m adapters.avature --tenant unifi --report
  python -m adapters.avature --tenant unifi --normalize
"""
import argparse
import html as htmllib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "avature")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {"impersonate": "chrome"}
except Exception:  # pragma: no cover - curl_cffi is a hard dep of the pipeline
    import requests as http
    _IMPERSONATE = {}

PLATFORM = "avature"
DELAY_SECONDS = 1.2       # detail-route throttle floor (6/6 reliable at this pace)
PAGE_SIZE = 20           # vendor-fixed; jobRecordsPerPage is ignored
MAX_PAGES = 100          # safety stop, not a business rule
TIMEOUT = 30

# Airport IATA -> (city, state). Reference data (not tenant logic): the search list and
# detail page carry only "United States" for location; the market facet fixes the STATE,
# this fixes the CITY from the code in the posting title (" - SEA", " - GEG").
AIRPORT_CITY = {
    "SEA": "SeaTac", "GEG": "Spokane", "PAE": "Everett", "BLI": "Bellingham",
    "PSC": "Pasco", "YKM": "Yakima", "PUW": "Pullman", "ALW": "Walla Walla",
    "AUS": "Austin", "DFW": "Dallas", "DAL": "Dallas", "IAH": "Houston",
    "HOU": "Houston", "SAT": "San Antonio", "ELP": "El Paso", "LBB": "Lubbock",
    "MFE": "McAllen", "HRL": "Harlingen", "CRP": "Corpus Christi", "BRO": "Brownsville",
}

# --------------------------------------------------------------------------
# config / paths / log
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
        "index": os.path.join(base, "index.jsonl"),   # in-scope postings, one JSON/line
        "detail": os.path.join(base, "detail"),         # {id}.json per in-scope job
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
# fetch - primed session (cookies) + Referer + pacing to beat the throttle.
# --------------------------------------------------------------------------

_SESSION = None


def _session(t):
    global _SESSION
    if _SESSION is None:
        _SESSION = http.Session(**_IMPERSONATE)
        # prime cookies from the careers landing page
        try:
            _SESSION.get(t["careers_url"], timeout=TIMEOUT)
        except Exception:
            pass
    return _SESSION


def fetch_search(t, market_value, offset):
    data = {t["state_field"]: market_value, "jobOffset": str(offset),
            "jobRecordsPerPage": str(PAGE_SIZE)}
    return _session(t).post(t["search_url"], data=data, timeout=TIMEOUT,
                            headers={"Referer": t["careers_url"]})


def fetch_detail(t, url):
    return _session(t).get(url, timeout=TIMEOUT, headers={"Referer": t["careers_url"]})


# --------------------------------------------------------------------------
# parsing - pure functions on strings (no network)
# --------------------------------------------------------------------------

_CARD_RX = re.compile(
    r'<a\s+href="(?P<url>https?://[^"]*/JobDetail/(?P<slug>[A-Za-z0-9\-]+)/(?P<id>\d+))"\s*>\s*'
    r'(?P<title>[^<]+?)\s*</a>', re.S)
_TOTAL_RX = re.compile(r'([\d,]+)\s*results', re.I)
_POSTED_RX = re.compile(r'Posted\s+(\d{1,2}-[A-Za-z]{3}-\d{4})')


def parse_cards(html_text):
    """Each result -> {url, slug, id, title}. De-duped by id, order preserved."""
    out, seen = [], set()
    for m in _CARD_RX.finditer(html_text):
        jid = m.group("id")
        if jid in seen:
            continue
        seen.add(jid)
        out.append({"url": m.group("url"), "slug": m.group("slug"),
                    "id": jid, "title": htmllib.unescape(m.group("title").strip())})
    return out


def stated_total(html_text):
    m = _TOTAL_RX.search(html_text)
    return int(m.group(1).replace(",", "")) if m else None


def _match_div(html_text, start):
    """Return html_text[start:end] where end is the close of the div opened at start-1
    (depth-balanced). Robust to nested divs inside the description."""
    depth, k = 1, start
    while k < len(html_text) and depth > 0:
        nd = html_text.find("<div", k)
        cd = html_text.find("</div", k)
        if cd < 0:
            return html_text[start:]
        if nd != -1 and nd < cd:
            depth += 1
            k = nd + 4
        else:
            depth -= 1
            k = cd + 5
            if depth == 0:
                return html_text[start:cd]
    return html_text[start:]


def extract_description(detail_html):
    """The requirements HTML = the 'Requirements and Description' section body, inside
    <div class="article__content__view__field">. Depth-balanced so nested markup is kept."""
    anchor = detail_html.find("Requirements and Description")
    search_from = anchor if anchor >= 0 else 0
    j = detail_html.find("article__content__view__field", search_from)
    if j < 0:
        j = detail_html.find("article__content__view", search_from)
    if j < 0:
        return None
    start = detail_html.find(">", j) + 1
    body = _match_div(detail_html, start).strip()
    return body or None


def strip_html(s):
    if not s:
        return None
    txt = re.sub(r"<[^>]+>", " ", s)
    txt = htmllib.unescape(txt)
    return " ".join(txt.split()) or None


def _airport_code(title):
    """Trailing IATA code in a posting title: 'Ramp Agent - GEG', '... - SEA (FT)'."""
    for m in re.finditer(r"\b([A-Z]{3})\b", title or ""):
        if m.group(1) in AIRPORT_CITY:
            return m.group(1)
    return None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def _markets(t):
    return t.get("markets") or {}


def mode_probe(t):
    print(f"tenant : {t['key']}  ({t.get('label','')})")
    print(f"search : {t['search_url']}")
    print(f"state field : {t.get('state_field')}   markets : {_markets(t)}")
    print()
    ok = True
    for mkt, val in _markets(t).items():
        r = fetch_search(t, val, 0)
        if r.status_code != 200:
            print(f"  {mkt}: status {r.status_code} FAIL"); ok = False; continue
        cards = parse_cards(r.text)
        total = stated_total(r.text)
        print(f"  {mkt} (value {val}): stated total {total}  page-1 cards {len(cards)}")
        if cards:
            c = cards[0]
            print(f"     first: {c['id']}  {c['title'][:60]}  airport={_airport_code(c['title'])}")
    print("\nProbe OK." if ok else "\nProbe FAILED.")
    log(t, "probe", ok=ok)
    return 0 if ok else 1


def _walk_market(t, mkt, val):
    """Page one market by jobOffset to an empty page. Returns list of card dicts (state-tagged)."""
    kept, seen = [], set()
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        r = fetch_paged(lambda: fetch_search(t, val, offset), label=f"{mkt} offset {offset}: ")
        cards = parse_cards(r.text)
        posted = dict(zip([c["id"] for c in cards], _POSTED_RX.findall(r.text)))
        fresh = [c for c in cards if c["id"] not in seen]
        if not fresh:
            break
        for c in fresh:
            seen.add(c["id"])
            c["state"] = mkt
            c["posted_at"] = posted.get(c["id"])
            kept.append(c)
        print(f"  {mkt} page {page+1}: {len(cards)} cards, cumulative {len(kept)}")
        if len(cards) < PAGE_SIZE:
            break
        time.sleep(DELAY_SECONDS)
    return kept


def mode_index(t):
    """Scope server-side per market (State facet), page each to empty, write the union."""
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    kept = []
    try:
        for mkt, val in _markets(t).items():
            kept.extend(_walk_market(t, mkt, val))
            time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT index: {e}. Partial capture DISCARDED (prior data kept).")
        log(t, "index_abort", detail=str(e))
        return 1
    with open(p["index"], "w", encoding="utf-8") as fh:
        for c in kept:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nindex complete: {len(kept)} in-scope across markets {list(_markets(t))} -> {p['index']}")
    log(t, "index", in_scope=len(kept), markets=list(_markets(t)))
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.exists(p["index"]):
        return []
    with open(p["index"], "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def mode_inspect(t):
    """One in-scope detail: confirm the description parses + peek at heading structure."""
    idx = load_index(t)
    if not idx:
        mkt, val = next(iter(_markets(t).items()))
        idx = _walk_market(t, mkt, val)
    if not idx:
        print("no postings to inspect"); return 1
    c = idx[0]
    print(f"posting : {c['id']}  {c['title']}")
    r = fetch_detail(t, c["url"])
    print(f"detail status : {r.status_code}")
    desc = extract_description(r.text)
    print(f"description extracted: {bool(desc)}  html_chars={len(desc or '')}")
    if desc:
        heads = re.findall(r"(?is)<(?:b|strong|h[1-6]|p)[^>]*>\s*([A-Z][^<]{2,45}?):?\s*</", desc)
        reqish = [h.strip() for h in heads
                  if re.search(r"qualif|requir|experien|skill|educ|essential|who|looking", h, re.I)]
        print(f"requirement-ish headings (derive openers from these): {reqish[:12]}")
        print(f"\ntext head: {strip_html(desc)[:220]}")
    return 0


def mode_detail(t):
    """Fetch + cache each in-scope job detail. Incremental: cached files are not re-fetched."""
    p = paths(t)
    os.makedirs(p["detail"], exist_ok=True)
    idx = load_index(t)
    if not idx:
        print("no index on disk - run --index first"); return 1
    fetched = failed = cached = 0
    for i, c in enumerate(idx, 1):
        dest = os.path.join(p["detail"], c["id"] + ".json")
        if os.path.exists(dest):
            cached += 1
            continue
        try:
            r = fetch_paged(lambda: fetch_detail(t, c["url"]), label=f"detail {i}/{len(idx)}: ")
        except Truncated as e:
            print(f"\n!! ABORT detail: {e}. Stopping (kept prior cache).")
            log(t, "detail_abort", detail=str(e)); return 1
        desc = extract_description(r.text)
        if not desc:
            failed += 1
        rec = {"id": c["id"], "title": c["title"], "url": c["url"], "slug": c["slug"],
               "state": c.get("state"), "posted_at": c.get("posted_at"),
               "description_html": desc}
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
    live = {c["id"] for c in load_index(t)}       # only in-scope survivors
    out = []
    for fn in sorted(os.listdir(p["detail"])):
        if not fn.endswith(".json") or fn[:-5] not in live:
            continue
        with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def map_record(rec, t, retrieved_at):
    """Avature detail record -> normalized contract. Every field name lives here."""
    r = model.new_record()
    warnings = []
    r["source_id"] = PLATFORM
    r["source_job_id"] = rec.get("id")
    r["company_name"] = t.get("company_name") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = rec.get("title")

    r["description_html"] = rec.get("description_html")
    r["description_text"] = strip_html(rec.get("description_html"))
    r["qualifications"] = []            # requirements live in the description; openers sectionize
    r["qualifications_html"] = None

    st = (rec.get("state") or "").strip().upper() or None
    code = _airport_code(rec.get("title"))
    city = AIRPORT_CITY.get(code) if code else None
    r["state"] = st
    r["city"] = city
    r["location_raw"] = ", ".join(x for x in [city or code, st] if x) or None
    r["lat"] = None
    r["lng"] = None

    r["employment_type"] = None
    r["shift_raw"] = None
    r["posted_at"] = rec.get("posted_at")
    r["freshness_state"] = "UNKNOWN"

    r["apply_url"] = rec.get("url")
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = None
    r["source_function"] = None
    r["source_url"] = rec.get("url")
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    if not r["state"]:
        warnings.append(f"{rec.get('id')}: no state resolved")
    return r, warnings


def mode_report(t):
    idx = load_index(t)
    det = _detail_records(t)
    with_desc = sum(1 for d in det if (d.get("description_html") or "").strip())
    from collections import Counter
    by_state = Counter(c.get("state") for c in idx)
    print(f"tenant         : {t['key']}")
    print(f"markets        : {_markets(t)}")
    print(f"in-scope index : {len(idx)}   by state: {dict(by_state)}")
    print(f"detail cached  : {len(det)}   with description: {with_desc}/{len(det)}")
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
        print(f"mapping warnings: {len(warns)} (e.g. {warns[0]})")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Avature native career-portal adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="verify search endpoint + per-market counts")
    g.add_argument("--inspect", action="store_true", help="one in-scope detail: description + headings")
    g.add_argument("--index", action="store_true", help="page each market to empty, write in-scope index")
    g.add_argument("--detail", action="store_true", help="fetch+cache each in-scope job detail")
    g.add_argument("--report", action="store_true", help="counts from what is on disk")
    g.add_argument("--normalize", action="store_true", help="map captured records into the contract")
    a = ap.parse_args()
    t = load_tenant(a.tenant)
    return {"probe": mode_probe, "inspect": mode_inspect, "index": mode_index,
            "detail": mode_detail, "report": mode_report, "normalize": mode_normalize}[
        next(k for k in ("probe", "inspect", "index", "detail", "report", "normalize")
             if getattr(a, k))](t)


if __name__ == "__main__":
    sys.exit(main())
