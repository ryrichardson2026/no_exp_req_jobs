"""
SuccessFactors RMK (career-site-builder) adapter - No-Experience Job Network.

SCOPE: fetch and write raw HTML/parsed records to disk (--pull), then map that
raw into the normalized contract (--normalize). No experience logic, no
classification - those run downstream on the contract shape.

PORTED from the tested reference pull_sf_rmk.py: the fetch-with-5xx/429-retry,
the startrow search cursor, find_links (the /job/ href regex, which implicitly
excludes /go/ category feeds), parse_labels, parse_section, parse_jsonld and
visible_text. Structure follows adapters/radancy_tb.py (module-level PLATFORM,
HERE/ROOT/CONFIG_PATH/RAW_ROOT, load_tenant reading tenants.json keyed
platform-section -> tenant, paths(), log(), the argparse main()).

STDLIB ONLY. No curl_cffi, requests or bs4 - these RMK pages are server-rendered
HTML and are parsed with re/html, exactly as the reference does.

PLATFORM NAMING - the key names the CODE PATH (one verified fetch shape), not a
vendor finding. "successfactors_rmk" is the SuccessFactors Recruiting Marketing
(career-site-builder) server-rendered listing: a /search/ page walked by a
startrow cursor, /job/{slug}/{posting_id}/ detail pages. Two ids per posting -
the RMK posting id in the URL and the SuccessFactors requisition number on the
page. Any tenant whose fetch shape differs gets its own key. Endpoints in config
are UNVERIFIED platform convention until --probe/--inspect confirm them live.

Usage:
  python -m adapters.successfactors_rmk --tenant cintas --probe
  python -m adapters.successfactors_rmk --tenant cintas --inspect
  python -m adapters.successfactors_rmk --tenant cintas --pull
  python -m adapters.successfactors_rmk --tenant cintas --normalize
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
RAW_ROOT = os.path.join(ROOT, "raw", "successfactors_rmk")

# The adapter imports the contract. The contract never imports an adapter.
sys.path.insert(0, ROOT)
from normalize import model  # noqa: E402

PLATFORM = "successfactors_rmk"
UA = "noprobjobs-pull/1.0 (+https://noprobjobs.com)"
DELAY_SECONDS = 1.0
DETAIL_PAUSE_SECONDS = 0.5
MAX_PAGES = 200          # safety stop, not a business rule
TIMEOUT = 30
RETRIES = 4
BACKOFF = 3

# Job links: /job/{City-Title-Slug-ST-ZIP}/{posting_id}/ - the RMK posting id is
# 6-14 digits. The regex only matches /job/, so /go/ category feeds are excluded
# by construction (the implicit /go/ exclusion the reference relies on).
# The slug class is [^"/?]+ : one path segment, everything up to the next "/" or
# "?". That already tolerates PERCENT-ENCODED bytes (%28, %29, %2C, ...) in the
# slug - a real row is `...-%284-Day-Workweek%29-WA-99201` - since %/hex are not
# excluded and an encoded slash (%2F) carries no literal "/". Written explicitly
# as [\w%%.,()+-] | %%hex so the intent is on the record, not incidental.
JOB_HREF = re.compile(r'href="(/job/((?:%[0-9A-Fa-f]{2}|[^"/?])+)/(\d{6,14}))/?"')
SCRIPT_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t\r\f\v]+")

# US state reference data - fixed, not tenant config. Used to split a clean
# "City, ST ZIP" Location value into city/state for the contract.
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
# config / paths / logging - radancy_tb conventions
# ---------------------------------------------------------------------------

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
# fetch - stdlib, ported retry (429 + 5xx backoff). Raises RuntimeError on a
# persistent failure so the caller can ABORT rather than write a partial set.
# ---------------------------------------------------------------------------

def fetch(url, retries=RETRIES, backoff=BACKOFF):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"{url} -> {last}")
        except Exception as e:
            last = str(e)
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"{url} -> gave up after {retries}: {last}")


# ---------------------------------------------------------------------------
# parsing - all pure functions on strings (no network), so tests drive them on
# fixture HTML directly.
# ---------------------------------------------------------------------------

def search_url(t, startrow):
    """Search page URL for a startrow cursor. startrow is REQUIRED - a walk that
    ignores it re-fetches page 1 forever (the top failure mode)."""
    p = dict(t.get("search_params") or {})
    p["startrow"] = startrow
    return t["endpoints"]["search"] + "?" + urllib.parse.urlencode(p)


def find_links(raw, host):
    """Unique job links on a search page, in document order. Dedupe on posting id.
    /go/ category feeds never match the /job/ regex, so they are excluded."""
    out, seen = [], set()
    for path, slug, pid in JOB_HREF.findall(raw):
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"posting_id": pid, "slug": slug, "url": host + path + "/"})
    return out


def visible_text(raw):
    """Strip markup to newline-preserving text. Cheap, adequate for label scraping."""
    s = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", s, flags=re.I)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    s = WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def parse_jsonld(raw):
    for block in SCRIPT_LD.findall(raw):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return None


def parse_labels(text, labels):
    """Label -> value on the same line. Values on RMK sit inline after the colon.
    `labels` is {contract_key: "Label Text"} from config."""
    got = {}
    for key, label in labels.items():
        m = re.search(re.escape(label) + r"\s*:?[ \t]*([^\n]*)", text)
        if m:
            v = m.group(1).strip(" :​")
            if v:
                got[key] = v
    return got


def parse_title(raw, text):
    m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    t = html.unescape(m.group(1)).strip() if m else None
    if t:
        t = re.split(r"\s+Job Details\s*\|", t)[0].strip()
    m2 = re.search(r"^\s*Title:\s*([^\n]+)", text, re.M)
    return (m2.group(1).strip() if m2 else t)


def parse_location(text):
    m = re.search(r"^\s*Location:\s*\n?\s*([^\n]+)", text, re.M)
    return m.group(1).strip() if m else None


def parse_section(text, heading, stop_headings):
    """VISIBLE-TEXT body between one heading (on its own line) and the next known
    heading. Used for description_text."""
    start = re.search(r"^\s*" + re.escape(heading) + r"\s*$", text, re.M)
    if not start:
        return None
    rest = text[start.end():]
    ends = [m.start() for h in stop_headings
            for m in re.finditer(r"^\s*" + re.escape(h) + r"\s*$", rest, re.M)]
    return rest[:min(ends)].strip() if ends else rest.strip()


def section_html_map(raw, headings):
    """Raw-HTML slice per heading: from the heading's first occurrence to the next
    heading's occurrence, in document order. Best-effort 'raw section HTML' for
    description_html. Headings not present are skipped."""
    positions = sorted((raw.find(h), h) for h in headings if raw.find(h) != -1)
    out = {}
    for idx, (i, h) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(raw)
        out[h] = raw[i:end].strip()
    return out


def split_location(loc):
    """(city, state2) from a clean 'City, ST' / 'City, ST ZIP' / 'City, State'
    Location value; (None, None) when it will not cleanly resolve."""
    if not loc:
        return None, None
    parts = [x.strip() for x in loc.split(",")]
    if len(parts) < 2:
        return None, None
    city = parts[0] or None
    tail = parts[1]
    tok = tail.split()[0] if tail.split() else ""
    state = None
    if len(tok) == 2 and tok.upper() in _STATE_CODES:
        state = tok.upper()
    else:
        state = US_STATE_TO_CODE.get(tail.lower())
    return city, state


def state_from_slug(slug):
    """State code from a job-URL slug shaped {City}-{Title-Slug}-{ST}-{ZIP}.
    Percent-decoded first, then the trailing '-ST-ZIP' is read. None when the
    slug does not end in a resolvable state+ZIP pair."""
    s = urllib.parse.unquote(slug or "")
    m = re.search(r"-([A-Za-z]{2})-\d{5}(?:-\d{4})?$", s)
    if m and m.group(1).upper() in _STATE_CODES:
        return m.group(1).upper()
    return None


def filter_in_market(links, state):
    """CLIENT-SIDE geo verification of what actually came back, on top of the
    server scope. Keep rows whose slug-parsed state == `state`; DROP + count rows
    that clearly resolve to a different state; keep indeterminate rows (their
    state is re-checked after the detail fetch via the Location label). Returns
    (kept, dropped). Empty `state` -> no filter (keep everything)."""
    if not state:
        return list(links), 0
    kept, dropped = [], 0
    for l in links:
        st = state_from_slug(l.get("slug"))
        if st and st != state:
            dropped += 1
            continue
        kept.append(l)
    return kept, dropped


def geo_scope_ok(t):
    """Acceptance #5: --pull may only run when the tenant carries a VERIFIED geo
    scope (or is explicitly marked exempt). A national un-scoped pull is refused
    BEFORE any fetch - a full-board crawl written as an in-market capture would
    poison the downstream completeness guard."""
    gs = t.get("geo_scope") or {}
    return bool(gs.get("verified") or gs.get("exempt"))


def parse_job(t, raw):
    """Parse one job page into a raw record dict. Pure - no network, no I/O."""
    text = visible_text(raw)
    labels = t.get("labeled_fields") or {}
    headings = t.get("section_headings") or {}

    rec = {
        "title": parse_title(raw, text),
        "location_text": parse_location(text),
        "jsonld": parse_jsonld(raw),
    }
    rec.update(parse_labels(text, labels))

    heads = list(headings.values())
    sec_text, sec_html = {}, {}
    html_map = section_html_map(raw, heads)
    for key, h in headings.items():
        body = parse_section(text, h, [x for x in heads if x != h])
        if body:
            sec_text[key] = body
        if html_map.get(h):
            sec_html[key] = html_map[h]
    rec["sections_text"] = sec_text
    rec["sections_html"] = sec_html
    rec["visible_text"] = text
    return rec


# ---------------------------------------------------------------------------
# mapping - raw record -> normalized contract. Every SF-RMK field name lives
# here. No experience extraction, no classification (a later stage fills them).
# ---------------------------------------------------------------------------

def map_record(raw, t, now):
    """Raw SF-RMK record -> model.new_record()-shaped contract record.
    `now` is the ISO timestamp used for retrieved_at/first_seen/last_seen so the
    record validates standalone (a test can call this and get validate() == [])."""
    r = model.new_record()
    warnings = []

    r["source_id"] = PLATFORM
    # source_job_id is the POSTING id (URL id), NOT the requisition number. The
    # req number reuses across reposts; the posting id is the stable per-posting
    # key. The req number has no contract slot and is intentionally dropped here.
    r["source_job_id"] = str(raw.get("posting_id") or "") or None

    r["company_name"] = t.get("employer_name") or t.get("company_name")
    r["employer_domain"] = t.get("employer_domain")
    r["title"] = raw.get("title")

    heads = list((t.get("section_headings") or {}).keys())
    st = raw.get("sections_text") or {}
    sh = raw.get("sections_html") or {}
    text_parts = [st[k] for k in heads if st.get(k)]
    html_parts = [sh[k] for k in heads if sh.get(k)]
    r["description_html"] = "\n\n".join(html_parts) or None
    r["description_text"] = "\n\n".join(text_parts) or None

    loc = raw.get("location_text")
    r["location_raw"] = loc
    city, state = split_location(loc)
    if city:
        r["city"] = city
    if state:
        r["state"] = state
    elif loc:
        warnings.append(f"state did not resolve: {loc!r}")

    # STRUCTURED shift on this platform: a labeled 'Shift' field distinct from
    # 'Schedule'. Take the label verbatim - do NOT parse the body for shift.
    r["shift_raw"] = raw.get("shift")
    r["employment_type"] = raw.get("schedule")

    r["apply_url"] = t["endpoints"]["apply_pattern"].format(posting_id=r["source_job_id"])
    r["apply_class"] = t.get("apply_class", "ATS")
    r["source_class"] = t.get("source_class", "direct-employer")

    # source taxonomy: Job Category verbatim, a field read (no method tag).
    r["source_category"] = raw.get("job_category")
    r["source_function"] = raw.get("job_segment")

    r["source_url"] = raw.get("source_url")
    r["retrieved_at"] = raw.get("retrieved_at") or now
    r["terms_reference"] = t.get("terms_reference")

    # Standalone-valid defaults: both seen timestamps set, is_new a bool. A
    # cross-run seen_state overrides these in mode_normalize.
    r["first_seen"] = now
    r["last_seen"] = now
    r["is_new"] = False

    r["dedupe_hash"] = model.dedupe_hash(r["company_name"], r["title"], r["location_raw"])
    model.order_salary(r)
    return r, warnings


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def mode_probe(t):
    """Fetch search page 1 AND page 2 (startrow=page_size); assert zero posting-id
    overlap. A startrow walk that ignores the cursor is the top failure mode."""
    size = int(t.get("page_size") or 25)
    url1 = search_url(t, 0)
    print(f"tenant   : {t['key']}  ({t.get('label','')})")
    print(f"search   : {url1}")
    try:
        raw1 = fetch(url1)
    except RuntimeError as e:
        print(f"FAIL  {e}")
        return 1
    links1 = find_links(raw1, t["host"])
    print(f"job links page 1 : {len(links1)}")
    print(f"configured page_size : {size}")
    if len(links1) != size:
        print("  page_size does not match page-1 links. Fix it before --pull or the")
        print("  startrow walk will skip or repeat rows.")
    m = re.search(r"([\d,]+)\s*(?:jobs?|results?|matches)", visible_text(raw1), re.I)
    print(f"result count : {m.group(0) if m else 'not found - read it manually once'}")
    for l in links1[:3]:
        print(f"  {l['posting_id']}  {l['slug'][:60]}")

    if not links1:
        print("  no job links on page 1 - the /job/ href pattern may differ. Stop.")
        return 1

    try:
        raw2 = fetch(search_url(t, size))
    except RuntimeError as e:
        print(f"FAIL page 2  {e}")
        return 1
    links2 = find_links(raw2, t["host"])
    overlap = {x["posting_id"] for x in links1} & {x["posting_id"] for x in links2}
    print(f"job links page 2 : {len(links2)} | overlap with page 1: {len(overlap)} (want 0)")
    if overlap:
        print("  STARTROW DEFECT - page 2 repeats page 1. The cursor is not advancing.")
        return 1
    print("\nProbe OK.")
    log(t, "probe", page1=len(links1), page2=len(links2), overlap=len(overlap))
    return 0


def mode_inspect(t):
    """Fetch page 1, then the first job page; print which labeled fields, sections
    and JSON-LD were caught, so the map is fixable before a pull."""
    try:
        raw = fetch(search_url(t, 0))
    except RuntimeError as e:
        print(f"FAIL  {e}")
        return 1
    links = find_links(raw, t["host"])
    if not links:
        print("no job links found. The /job/ href pattern may differ on this tenant.")
        return 1
    target = links[0]
    print(f"inspecting {target['url']}\n")
    try:
        page = fetch(target["url"])
    except RuntimeError as e:
        print(f"FAIL  {e}")
        return 1
    rec = parse_job(t, page)

    print(f"  {'OK ' if rec.get('title') else 'MISS'} title            {str(rec.get('title'))[:60]}")
    print(f"  {'OK ' if rec.get('location_text') else 'MISS'} location_text    {str(rec.get('location_text'))[:60]}")
    print(f"  {'OK ' if rec.get('jsonld') else 'MISS'} jsonld           "
          f"{'JobPosting present' if rec.get('jsonld') else 'none - label parsing is the only path'}")
    print("\nlabeled fields:")
    for k in (t.get("labeled_fields") or {}):
        v = rec.get(k)
        print(f"  {'OK ' if v else 'MISS'} {k:<26} {str(v)[:50]}")
    print("\nsections:")
    for k in (t.get("section_headings") or {}):
        v = (rec.get("sections_text") or {}).get(k)
        print(f"  {'OK ' if v else 'MISS'} {k:<26} {len(v) if v else 0} chars")
    if rec.get("jsonld"):
        print("\njsonld keys:", sorted(rec["jsonld"].keys()))
    return 0


def mode_pull(t):
    """Walk search pages by startrow (dedupe on posting id) -> GET each job page ->
    parse -> write raw records.jsonl.

    HARD RULE: on a PERSISTENT list-page failure after retries, ABORT (return
    non-zero, write NOTHING) - a truncation written as complete defeats the
    downstream completeness guard. A single detail-page failure is skipped as a
    per-record gap."""
    # Acceptance #5: refuse BEFORE any fetch if the geo scope is not verified.
    if not geo_scope_ok(t):
        print("!! REFUSING --pull: no verified geo scope (geo_scope.verified) and "
              "not marked exempt. Verify a live geo scope — count materially below "
              "national, rows in-market — before --pull.")
        log(t, "pull_refused", reason="geo_scope_unverified")
        return 1

    p = paths(t)
    os.makedirs(p["base"], exist_ok=True)
    size = int(t.get("page_size") or 25)
    host = t["host"]
    state = t.get("state")

    # 1) collect the full link set FIRST. A list-page failure aborts here, before
    #    any records file is written.
    found, seen_ids, startrow = [], set(), 0
    for _ in range(MAX_PAGES):
        try:
            raw = fetch(search_url(t, startrow))
        except RuntimeError as e:
            print(f"\n!! ABORT: list page (startrow {startrow}) failed persistently: {e}",
                  file=sys.stderr)
            print("   Partial capture DISCARDED; records.jsonl NOT written. "
                  "Re-run when the source recovers.", file=sys.stderr)
            log(t, "pull_abort", startrow=startrow, detail=str(e),
                collected_before_abort=len(found))
            return 1
        links = find_links(raw, host)
        fresh = [l for l in links if l["posting_id"] not in seen_ids]
        if not fresh:
            break
        for l in fresh:
            seen_ids.add(l["posting_id"])
        found.extend(fresh)
        print(f"  list {len(found)} (startrow {startrow})", file=sys.stderr)
        startrow += size
        time.sleep(DELAY_SECONDS)

    # 1b) CLIENT-SIDE geo filter on the returned rows (always, on top of the
    #     server scope): drop rows whose slug resolves to a non-target state.
    total_found = len(found)
    found, dropped_list = filter_in_market(found, state)
    if state:
        print(f"  client-side {state} filter (list): {total_found} rows, "
              f"dropped {dropped_list} non-{state}", file=sys.stderr)

    # 2) detail fetch. A single failure is a skipped per-record gap, not an abort.
    n, skipped, dropped_detail = 0, 0, 0
    with open(p["records"], "w", encoding="utf-8") as fh:
        for l in found:
            try:
                page = fetch(l["url"])
            except RuntimeError as e:
                print(f"  skip {l['posting_id']}: {e}", file=sys.stderr)
                skipped += 1
                continue
            rec = parse_job(t, page)
            # Re-verify state from the Location label for rows the slug could not
            # resolve at list stage. Drop + count any that land out of market.
            if state:
                st = state_from_slug(l["slug"]) or split_location(rec.get("location_text"))[1]
                if st and st != state:
                    dropped_detail += 1
                    continue
            rec.update({
                "tenant_key": t["key"],
                "platform": PLATFORM,
                "posting_id": l["posting_id"],
                "slug": l["slug"],
                "source_url": l["url"],
                "apply_url": t["endpoints"]["apply_pattern"].format(posting_id=l["posting_id"]),
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 25 == 0:
                print(f"  detail {n}/{len(found)}", file=sys.stderr)
            time.sleep(DETAIL_PAUSE_SECONDS)

    print(f"pull complete: {total_found} postings, {n} written, "
          f"{dropped_list + dropped_detail} dropped non-{state or '?'}, "
          f"{skipped} detail failures -> {p['records']}")
    log(t, "pull", postings=total_found, written=n,
        dropped_out_of_market=dropped_list + dropped_detail, detail_failures=skipped)
    return 0


def load_records(t):
    f = paths(t)["records"]
    if not os.path.exists(f):
        sys.exit("no records.jsonl on disk - run --pull first")
    with open(f, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mode_normalize(t):
    """Map raw records into the contract. Derived fields (experience_condition,
    category, credentials, evidence_clauses) are left at new_record() defaults
    BY DESIGN - a later stage fills them."""
    raws = load_records(t)
    out_dir = os.path.join(ROOT, "out", PLATFORM, t["key"])
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "normalized.jsonl")

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    state_path = os.path.join(out_dir, "seen_state.json")
    seen_state = {}
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            seen_state = json.load(fh)
    known_before = len(seen_state)

    mapped, invalid, warns = [], [], []
    for raw in raws:
        rec, w = map_record(raw, t, now)
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

    print(f"{len(raws)} raw -> {len(mapped)} normalized -> {out_path}")
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
        uw = {}
        for w in warns:
            uw[w] = uw.get(w, 0) + 1
        for w, n in sorted(uw.items(), key=lambda x: -x[1])[:10]:
            print(f"  {n:>4}x  {w}")
    log(t, "normalize", records=len(mapped), invalid=len(invalid))
    return 0


def main():
    ap = argparse.ArgumentParser(description="SuccessFactors RMK adapter - stdlib only")
    ap.add_argument("--tenant", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="fetch search p1+p2, assert cursor advances")
    g.add_argument("--inspect", action="store_true", help="print caught fields/sections/JSON-LD")
    g.add_argument("--pull", action="store_true", help="walk startrow + fetch job pages to disk")
    g.add_argument("--normalize", action="store_true", help="map raw into the contract")
    a = ap.parse_args()

    tenant = load_tenant(a.tenant)
    for mode in ("probe", "inspect", "pull", "normalize"):
        if getattr(a, mode):
            return globals()[f"mode_{mode}"](tenant)


if __name__ == "__main__":
    sys.exit(main())
