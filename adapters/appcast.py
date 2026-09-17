"""
Appcast job-search careers-site adapter (server-rendered HTML) - No-Experience Job Network.

SCOPE: fetch and write raw HTML/records to disk. Nothing else. No experience logic
(that is normalize.enrich with this tenant's forked openers).

PLATFORM NAMING - read before adding a tenant. Named for the READ SURFACE: a WordPress
careers site running the Appcast job-search plugin (wp-content/plugins/appcast-jobsearch-plugin).
The APPLY flow may be a different vendor (Aramark = Paradox chat) - that is not the read
surface. Confirmed 2026-09-17 by the plugin script + a cold fetch.

FETCH SHAPE (reverse-engineered + verified COLD from Python 2026-09-17, cookieless):
  index  GET https://{host}/calc-results/?searchlocation={State}&searchradius={r}&mypage={N}
         -> an HTML FRAGMENT of result cards. SERVER-SIDE location scope (searchlocation=
         Washington returns only WA). Page mypage=1..N until a page yields no cards.
         Card: <li class="Results__list__item" id="result-{jobid}"><a href="/job/{slug}/
         {city-state}/{jobid}/"> <h3 class="Results__list__title">Title</h3>
         <p class="career-area">Area | Specialty</p>
         <p class="location">City, ST | <span class="jobid">Job ID #{id}</span></p>
  detail GET https://{host}{href}  (server-rendered). The full posting is the
         <div class="Desc__copy ..."> container, with <h2> sections: Job Description,
         Job Responsibilities, Qualifications, Education. Requirements live under
         'Qualifications' (the opener anchor).

INVARIANTS honored: page-to-empty is completeness (no vendor total trusted); a transient
5xx truncates + aborts WITHOUT writing a partial set as complete (paginate.fetch_paged);
config is data (no branching on tenant identity).

Usage:
  python -m adapters.appcast --tenant aramark --probe
  python -m adapters.appcast --tenant aramark --inspect
  python -m adapters.appcast --tenant aramark --index
  python -m adapters.appcast --tenant aramark --detail
  python -m adapters.appcast --tenant aramark --report
  python -m adapters.appcast --tenant aramark --normalize
"""
import argparse
import html as _html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")
RAW_ROOT = os.path.join(ROOT, "raw", "appcast")

sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402
from adapters.paginate import fetch_paged, Truncated  # noqa: E402

PLATFORM = "appcast"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0 Safari/537.36")
DELAY_SECONDS = 1.0
MAX_PAGES = 200
TIMEOUT = 45
US_STATE_CODES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA",
    "ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK",
    "OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
}


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
    return {"base": base, "index": os.path.join(base, "index.jsonl"),
            "detail": os.path.join(base, "detail"), "run": os.path.join(base, "run_log.jsonl")}


def log(tenant, event, **fields):
    p = paths(tenant)
    os.makedirs(p["base"], exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update(fields)
    with open(p["run"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# --- fetch: urllib wrapped to a .status_code response that never raises, so
# paginate.fetch_paged can retry/abort uniformly ---

class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return self._body


def _http(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return _Resp(getattr(r, "status", 200), r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return _Resp(e.code, e.read().decode("utf-8", "replace") if e.fp else "")


def search_url(t, searchloc, mypage):
    params = {"searchlocation": searchloc,
              "searchradius": str(t.get("search_radius", 50)),
              "mypage": mypage}
    params.update(t.get("search_extra") or {})
    return f"https://{t['host']}/calc-results/?" + urllib.parse.urlencode(params)


# --- parsing (pure) ---

_CARD_RX = re.compile(
    r'<li[^>]*class="[^"]*Results__list__item[^"]*"[^>]*id="result-([^"]+)"[^>]*>(.*?)</li>',
    re.S | re.I)
_HREF_RX = re.compile(r'href="(/job/[^"]+)"', re.I)
_TITLE_RX = re.compile(r'class="[^"]*Results__list__title[^"]*"[^>]*>(.*?)</h3>', re.S | re.I)
_AREA_RX = re.compile(r'class="[^"]*career-area[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_LOC_RX = re.compile(r'class="[^"]*location[^"]*"[^>]*>(.*?)</p>', re.S | re.I)


def _clean(s):
    if s is None:
        return None
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip() or None


def parse_cards(html):
    """Result cards -> list of {jobid, href, title, career_area, location_raw, city, state}."""
    out = []
    for jobid, block in _CARD_RX.findall(html):
        href = (_HREF_RX.search(block) or [None])
        href = _HREF_RX.search(block)
        title = _TITLE_RX.search(block)
        area = _AREA_RX.search(block)
        loc = _LOC_RX.search(block)
        # location text is "City, ST | Job ID #NNN" - take the part before the pipe
        loc_txt = _clean(loc.group(1)) if loc else None
        if loc_txt:
            loc_txt = loc_txt.split("|")[0].strip()
        city, state = None, None
        if loc_txt:
            m = re.search(r"^(.*?),\s*([A-Z]{2})\b", loc_txt)
            if m:
                city, state = m.group(1).strip(), m.group(2)
        out.append({
            "jobid": jobid.strip(),
            "href": href.group(1) if href else None,
            "title": _clean(title.group(1)) if title else None,
            "career_area": (_clean(area.group(1)) or "").split("|")[0].strip() or None if area else None,
            "location_raw": loc_txt, "city": city, "state": state,
        })
    return out


def extract_description(detail_html):
    """The <div class="Desc__copy ..."> container (full posting HTML)."""
    m = re.search(r'<div[^>]*class="[^"]*Desc__copy[^"]*"[^>]*>', detail_html, re.I)
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    tag_rx = re.compile(r"<(/?)div\b[^>]*>", re.I)
    for tm in tag_rx.finditer(detail_html, start):
        depth += -1 if tm.group(1) else 1
        if depth == 0:
            i = tm.start()
            break
    else:
        i = len(detail_html)
    return detail_html[start:i].strip() or None


def strip_html(s):
    if not s:
        return None
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", _html.unescape(txt)).strip() or None


def in_scope(rec, tenant):
    """Server-side searchlocation already scopes; double-check the parsed state is a
    launched/target state when a filter is configured (belt and suspenders)."""
    f = tenant.get("location_filter") or {}
    want = {s.upper() for s in (f.get("state_codes") or [])}
    if not want:
        return True
    return (rec.get("state") or "").upper() in want


# --- modes ---

def _searchlocations(t):
    return t.get("scope_params", {}).get("searchlocations") or ["Washington"]


def mode_probe(t):
    print(f"tenant : {t['key']}  ({t.get('label','')})")
    print(f"host   : {t['host']}   searchlocations: {_searchlocations(t)}")
    loc = _searchlocations(t)[0]
    r = _http(search_url(t, loc, 1))
    print(f"\nstatus : {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300]); return 1
    cards = parse_cards(r.text)
    print(f"cards on page 1 ({loc}) : {len(cards)}")
    if cards:
        c = cards[0]
        print(f"first: {c['jobid']}  {c['title']}  [{c['location_raw']}]  cat={c['career_area']}")
        print(f"       href={c['href']}")
    # advance check
    if len(cards) >= 1:
        time.sleep(DELAY_SECONDS)
        r2 = _http(search_url(t, loc, 2))
        c2 = parse_cards(r2.text)
        same = {x["jobid"] for x in cards} == {x["jobid"] for x in c2}
        print(f"page 2: {len(c2)} cards, identical to page 1: {same}")
        if c2 and same:
            print("  PAGINATION DEFECT - mypage not advancing. Stop."); return 1
    print("\nProbe OK.")
    log(t, "probe", status=r.status_code, page1=len(cards))
    return 0


def mode_inspect(t):
    loc = _searchlocations(t)[0]
    cards = parse_cards(_http(search_url(t, loc, 1)).text)
    if not cards:
        print("no cards to inspect"); return 1
    c = cards[0]
    print(f"card: {c}")
    html = _http(f"https://{t['host']}{c['href']}").text
    desc = extract_description(html)
    print(f"\ndetail Desc__copy extracted: {bool(desc)}  html_chars={len(desc or '')}")
    if desc:
        heads = re.findall(r"<h[1-5][^>]*>\s*([A-Za-z][^<]{2,40}?)\s*</h[1-5]>", desc)
        print(f"section headings (opener candidates): {heads[:10]}")
        print(f"\ntext head: {strip_html(desc)[:220]}")
    return 0


def mode_index(t):
    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    kept, seen = [], set()
    try:
        for loc in _searchlocations(t):
            for page in range(1, MAX_PAGES + 1):
                r = fetch_paged(lambda: _http(search_url(t, loc, page)), label=f"{loc} p{page}: ")
                cards = parse_cards(r.text)
                fresh = [c for c in cards if c["jobid"] not in seen]
                for c in fresh:
                    seen.add(c["jobid"])
                    if in_scope(c, t):
                        c["searchlocation"] = loc
                        kept.append(c)
                print(f"  {loc} page {page}: {len(cards)} cards ({len(fresh)} new), kept {len(kept)}")
                if not cards or not fresh:
                    break
                time.sleep(DELAY_SECONDS)
    except Truncated as e:
        print(f"\n!! ABORT index: {e}. Partial capture DISCARDED.")
        log(t, "index_abort", detail=str(e)); return 1
    with open(p["index"], "w", encoding="utf-8") as fh:
        for c in kept:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nindex complete: {len(kept)} in-scope -> {p['index']}")
    log(t, "index", in_scope=len(kept))
    return 0


def load_index(t):
    p = paths(t)
    if not os.path.exists(p["index"]):
        return []
    with open(p["index"], "r", encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def mode_detail(t):
    p = paths(t)
    os.makedirs(p["detail"], exist_ok=True)
    idx = load_index(t)
    if not idx:
        print("no index - run --index first"); return 1
    fetched = cached = failed = 0
    for i, c in enumerate(idx, 1):
        dest = os.path.join(p["detail"], c["jobid"] + ".json")
        if os.path.exists(dest):
            cached += 1
            continue
        try:
            r = fetch_paged(lambda: _http(f"https://{t['host']}{c['href']}"), label=f"detail {i}/{len(idx)}: ")
        except Truncated as e:
            print(f"\n!! ABORT detail: {e}."); log(t, "detail_abort", detail=str(e)); return 1
        desc = extract_description(r.text)
        if not desc:
            failed += 1
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump({**c, "description_html": desc}, fh, ensure_ascii=False)
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
    live = {c["jobid"] for c in load_index(t)}
    out = []
    for fn in sorted(os.listdir(p["detail"])):
        if fn.endswith(".json") and fn[:-5] in live:
            with open(os.path.join(p["detail"], fn), "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out


def map_record(rec, t, retrieved_at):
    r = model.new_record()
    warnings = []
    r["source_id"] = PLATFORM
    r["source_job_id"] = rec.get("jobid")
    r["company_name"] = t.get("company_name") or t.get("label")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = rec.get("title")
    r["description_html"] = rec.get("description_html")
    r["description_text"] = strip_html(rec.get("description_html"))
    r["qualifications"] = []
    r["qualifications_html"] = None
    r["location_raw"] = rec.get("location_raw")
    r["city"] = rec.get("city")
    st = (rec.get("state") or "").strip().upper()
    r["state"] = st if st in US_STATE_CODES else None
    if not r["state"]:
        warnings.append(f"{rec.get('jobid')}: no state")
    r["lat"] = None
    r["lng"] = None
    r["employment_type"] = None
    r["shift_raw"] = None
    r["posted_at"] = None
    r["freshness_state"] = "UNKNOWN"
    url = f"https://{t['host']}{rec.get('href')}"
    r["apply_url"] = url
    r["apply_class"] = "ATS"
    r["source_class"] = t.get("source_class", "direct-employer")
    r["source_category"] = rec.get("career_area")
    r["source_function"] = None
    r["source_url"] = url
    r["retrieved_at"] = retrieved_at
    r["terms_reference"] = t.get("terms_reference")
    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    return r, warnings


def mode_report(t):
    idx = load_index(t)
    det = _detail_records(t)
    with_desc = sum(1 for d in det if (d.get("description_html") or "").strip())
    from collections import Counter
    print(f"tenant         : {t['key']}")
    print(f"searchlocations: {_searchlocations(t)}")
    print(f"in-scope index : {len(idx)}   by state: {dict(Counter(c.get('state') for c in idx))}")
    print(f"detail cached  : {len(det)}   with description: {with_desc}/{len(det)}")
    return 0


def mode_normalize(t):
    det = _detail_records(t)
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
    ap = argparse.ArgumentParser(description="Appcast careers-site adapter - raw capture only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true")
    g.add_argument("--inspect", action="store_true")
    g.add_argument("--index", action="store_true")
    g.add_argument("--detail", action="store_true")
    g.add_argument("--report", action="store_true")
    g.add_argument("--normalize", action="store_true")
    a = ap.parse_args()
    t = load_tenant(a.tenant)
    for m in ("probe", "inspect", "index", "detail", "report", "normalize"):
        if getattr(a, m):
            return globals()[f"mode_{m}"](t)


if __name__ == "__main__":
    sys.exit(main())
