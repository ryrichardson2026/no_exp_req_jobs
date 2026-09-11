#!/usr/bin/env python3
"""
ADP Workforce Now recruiting puller. Stdlib only.
Single-call source: $select pulls description and qualifications inline,
so there is no detail fetch.

  python pull_adp.py configs/gensco.json --probe
  python pull_adp.py configs/gensco.json --inspect
  python pull_adp.py configs/gensco.json --pull --out raw/gensco.jsonl
  python pull_adp.py configs/gensco.json --normalize raw/gensco.jsonl --out norm/gensco.jsonl
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "noprobjobs-pull/1.0 (+https://noprobjobs.com)"
TAG = re.compile(r"<[^>]+>")

# Response envelope varies by ADP endpoint. Try these in order.
LIST_KEYS = ["jobRequisitions", "requisitions", "items", "value", "results", "data"]


def headers_from(cfg):
    h = {"User-Agent": UA, "Accept": "application/json"}
    for k, v in (cfg.get("headers") or {}).items():
        if k == "note" or not isinstance(v, str):
            continue
        h[k] = v
    return h


def get(url, hdrs, retries=4, backoff=3):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    raise RuntimeError(f"{url} -> non-JSON response ({len(body)} bytes). "
                                       f"Usually means the request was not authorized or scoped. "
                                       f"First 200 chars: {body[:200]!r}")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"{url} -> {last}")
        except RuntimeError:
            raise
        except Exception as e:
            last = str(e)
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"{url} -> gave up after {retries}: {last}")


def list_url(cfg, skip):
    p = dict(cfg["list_request"]["params"])
    p["$top"] = cfg["list_request"]["page_size"]
    if skip:
        p[cfg["list_request"]["pagination"]["cursor_param"]] = skip
    return cfg["endpoints"]["list"] + "?" + urllib.parse.urlencode(p, safe="$,/:")


def unwrap(payload):
    """Find the row list inside whatever envelope came back."""
    if isinstance(payload, list):
        return payload, "<root list>"
    if not isinstance(payload, dict):
        return [], "<unknown>"
    for k in LIST_KEYS:
        v = payload.get(k)
        if isinstance(v, list):
            return v, k
    for k, v in payload.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v, k
    return [], "<none found>"


def dig(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def to_text(s):
    if not s:
        return None
    if isinstance(s, dict):
        s = s.get("text") or s.get("value") or json.dumps(s)
    s = re.sub(r"<br\s*/?>", "\n", str(s), flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6])>", "\n", s, flags=re.I)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return "\n".join(l.strip() for l in s.split("\n")).strip()


def loc_strings(row):
    """workLocations / requisitionLocations shapes are unknown. Flatten anything stringy."""
    out = []
    for key in ("workLocations", "requisitionLocations"):
        v = row.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    for k in ("nameCode", "address", "locationName", "name"):
                        sub = item.get(k)
                        if isinstance(sub, str):
                            out.append(sub)
                        elif isinstance(sub, dict):
                            bits = [sub.get(x) for x in
                                    ("shortName", "cityName", "countrySubdivisionLevel1",
                                     "city", "state", "postalCode")]
                            bits = [b.get("codeValue") if isinstance(b, dict) else b for b in bits]
                            bits = [b for b in bits if isinstance(b, str)]
                            if bits:
                                out.append(", ".join(dict.fromkeys(bits)))
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ probe
def cmd_probe(cfg):
    hdrs = headers_from(cfg)
    url = list_url(cfg, 0)
    print(f"list endpoint: {url}\n")
    if "not yet captured" in (cfg.get("headers", {}).get("note") or "").lower():
        print("WARNING: config still flags headers as uncaptured. If scoping lives in a")
        print("header or cookie, this call may return the wrong tenant or nothing.\n")
    try:
        payload = get(url, hdrs)
    except RuntimeError as e:
        print(f"FAIL {e}")
        return 1
    rows, key = unwrap(payload)
    print(f"envelope key : {key}")
    print(f"rows returned: {len(rows)} (requested $top={cfg['list_request']['page_size']})")
    if isinstance(payload, dict):
        print(f"envelope keys: {sorted(payload.keys())}")
    if not rows:
        print("\nZero rows. Either the filter excludes everything or the request is unscoped.")
        return 1

    # Is this actually the right employer?
    print("\nfirst 5 rows:")
    for r in rows[:5]:
        print(f"  {r.get('reqId')}  {(r.get('publishedJobTitle') or r.get('jobTitle') or '')[:45]}")
        for l in loc_strings(r)[:1]:
            print(f"       {l[:60]}")
    print("\nCheck those titles and locations look like this employer. If they do not,")
    print("the request is not scoped and the headers still need capturing.")

    # pagination proof
    cur = cfg["list_request"]["pagination"]["cursor_param"]
    try:
        p2 = get(list_url(cfg, cfg["list_request"]["page_size"]), hdrs)
        r2, _ = unwrap(p2)
        ids1 = {r.get("reqId") for r in rows}
        ids2 = {r.get("reqId") for r in r2}
        print(f"\npage 2 via {cur}: {len(r2)} rows | overlap with page 1: {len(ids1 & ids2)} (want 0)")
        if ids1 and ids1 == ids2:
            print(f"  {cur} is being ignored. Find the real pagination parameter before --pull.")
    except RuntimeError as e:
        print(f"\npage 2 failed: {e}")
    return 0


# ------------------------------------------------------------------ inspect
def cmd_inspect(cfg):
    hdrs = headers_from(cfg)
    payload = get(list_url(cfg, 0), hdrs)
    rows, key = unwrap(payload)
    if not rows:
        print("no rows returned")
        return 1
    row = rows[0]
    print(f"envelope key: {key}\nrow keys: {sorted(row.keys())}\n")

    print("field_map resolution:")
    for contract, path in cfg["field_map"].items():
        v = dig(row, path)
        kind = type(v).__name__
        prev = to_text(v)[:45] if isinstance(v, str) else (f"<{kind}>" if v is not None else "")
        print(f"  {'OK ' if v not in (None, '') else 'MISS'} {contract:<22} <- {path:<22} {prev}")

    print("\nlocation shapes:")
    for k in ("workLocations", "requisitionLocations"):
        print(f"  {k}: {json.dumps(row.get(k))[:200]}")
    print(f"  flattened -> {loc_strings(row)}")

    qual = to_text(dig(row, cfg["field_map"]["qualifications_html"]))
    print(f"\njobQualifications: {len(qual) if qual else 0} chars")
    if qual:
        print("  first 300:")
        for line in qual[:300].split("\n"):
            print(f"    {line}")
        hits = re.findall(r"^\s*(Education|Experience|Knowledge|Certifications?|Licenses?|"
                          r"Minimum Requirements?|Preferred Requirements?)\s*:?\s*(.*)$",
                          qual, re.M | re.I)
        print("\n  labeled requirement lines:")
        if hits:
            for label, val in hits:
                print(f"    {label:<24} {val[:55]}")
        else:
            print("    none. Free prose, so the clause-level extractor does the work here.")
    return 0


# ------------------------------------------------------------------ pull
def cmd_pull(cfg, out_path, max_pages=500):
    hdrs = headers_from(cfg)
    rl = cfg["rate_limit"]
    delay = 1.0 / rl["requests_per_second"]
    size = cfg["list_request"]["page_size"]

    seen, skip, n = set(), 0, 0
    with open(out_path, "w") as f:
        for _ in range(max_pages):
            payload = get(list_url(cfg, skip), hdrs, rl["max_retries"], rl["backoff_seconds"])
            rows, _ = unwrap(payload)
            fresh = [r for r in rows if r.get("reqId") not in seen]
            if not fresh:
                break
            for r in fresh:
                seen.add(r.get("reqId"))
                f.write(json.dumps({
                    "tenant_key": cfg["tenant_key"],
                    "platform": cfg["platform"],
                    "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source_url": cfg["endpoints"]["listing_page"],
                    "tz": cfg["list_request"]["params"].get("tz"),
                    "record": r,
                }) + "\n")
                n += 1
            print(f"  {n} rows (skip {skip})", file=sys.stderr)
            skip += size
            time.sleep(delay)
    print(f"wrote {n} records -> {out_path}")
    return 0


# ------------------------------------------------------------------ normalize
def cmd_normalize(cfg, raw_path, out_path):
    """Contract fields only. No experience extraction, no classification."""
    rows = []
    with open(raw_path) as fin, open(out_path, "w") as fout:
        for line in fin:
            r = json.loads(line)
            rec = r["record"]
            locs = loc_strings(rec)
            desc = to_text(dig(rec, cfg["field_map"]["description_html"]))
            qual = to_text(dig(rec, cfg["field_map"]["qualifications_html"]))
            norm = {
                "tenant_key": r["tenant_key"],
                "platform": r["platform"],
                "employer_name": cfg["employer_name"],
                "market": cfg["market"],
                "state": cfg["state"],
                "retrieved_at": r["retrieved_at"],
                "posting_tz": r.get("tz"),
                "source_url": r["source_url"],
                "apply_url": r["source_url"],
                "source_job_id": dig(rec, cfg["field_map"]["source_job_id"]),
                "client_req_id": dig(rec, cfg["field_map"]["client_req_id"]),
                "title": dig(rec, cfg["field_map"]["title"]) or dig(rec, cfg["field_map"]["internal_title"]),
                "location_text": locs[0] if locs else None,
                "all_locations": locs or None,
                "description_text": "\n\n".join(x for x in (desc, qual) if x) or None,
                "qualifications_text": qual,
                "time_type": to_text(dig(rec, cfg["field_map"]["time_type"])),
                "work_level": to_text(dig(rec, cfg["field_map"]["work_level"])),
                "posted_text": dig(rec, cfg["field_map"]["posted_text"]),
            }
            fout.write(json.dumps(norm) + "\n")
            rows.append(norm)
    n = len(rows)
    print(f"normalized {n} -> {out_path}")
    if not n:
        return 0
    missing = {k: sum(1 for d in rows if d.get(k) in (None, "")) for k in rows[0]}
    print("null coverage (field: count):")
    for k, v in sorted(missing.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<22} {v}/{n}")
    labeled = sum(1 for d in rows if d.get("qualifications_text") and
                  re.search(r"^\s*(Experience|Minimum Requirements?)\b", d["qualifications_text"],
                            re.M | re.I))
    print(f"\npostings with a labeled experience or minimum-requirements opener: {labeled}/{n}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--normalize", metavar="RAW_JSONL")
    ap.add_argument("--out")
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    if a.probe:
        return cmd_probe(cfg)
    if a.inspect:
        return cmd_inspect(cfg)
    if a.pull:
        return cmd_pull(cfg, a.out or f"raw_{cfg['tenant_key']}.jsonl")
    if a.normalize:
        return cmd_normalize(cfg, a.normalize, a.out or f"norm_{cfg['tenant_key']}.jsonl")
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
