#!/usr/bin/env python3
"""
SuccessFactors RMK (career-site-builder) puller. Stdlib only.
Same four gates as pull_workday.py.

  python pull_sf_rmk.py configs/cintas.json --probe
  python pull_sf_rmk.py configs/cintas.json --inspect
  python pull_sf_rmk.py configs/cintas.json --pull --out raw/cintas.jsonl
  python pull_sf_rmk.py configs/cintas.json --normalize raw/cintas.jsonl --out norm/cintas.jsonl

Pages are server-rendered, so this parses HTML rather than calling an API.
--inspect prints what each selector actually caught so the map gets fixed
before a full pull runs against it.
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

JOB_HREF = re.compile(r'href="(/job/([^"/?]+)/(\d{6,14}))/?"')
SCRIPT_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t\r\f\v]+")


def fetch(url, retries=4, backoff=3):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
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


def search_url(cfg, startrow):
    p = dict(cfg["search_request"]["params"])
    p["startrow"] = startrow
    return cfg["endpoints"]["search"] + "?" + urllib.parse.urlencode(p)


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


def find_links(raw, host):
    """Unique job links on a search page, in document order."""
    out, seen = [], set()
    for path, slug, pid in JOB_HREF.findall(raw):
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"posting_id": pid, "slug": slug, "url": host + path + "/"})
    return out


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
    """Label -> value on the same line. Values on RMK sit inline after the colon."""
    got = {}
    for key, label in labels.items():
        m = re.search(re.escape(label) + r"\s*([^\n]*)", text)
        if m:
            v = m.group(1).strip(" :\u200b")
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
    """Text between one heading and the next known heading."""
    start = re.search(r"^\s*" + re.escape(heading) + r"\s*$", text, re.M)
    if not start:
        return None
    rest = text[start.end():]
    ends = [m.start() for h in stop_headings
            for m in re.finditer(r"^\s*" + re.escape(h) + r"\s*$", rest, re.M)]
    return rest[:min(ends)].strip() if ends else rest.strip()


def parse_job(cfg, raw):
    text = visible_text(raw)
    rec = {
        "title": parse_title(raw, text),
        "location_text": parse_location(text),
        "jsonld": parse_jsonld(raw),
    }
    rec.update(parse_labels(text, cfg["labeled_fields"]))
    heads = list(cfg["section_headings"].values())
    for key, h in cfg["section_headings"].items():
        rec[f"section_{key}"] = parse_section(text, h, [x for x in heads if x != h])
    rec["visible_text"] = text
    return rec


# ------------------------------------------------------------------ probe
def cmd_probe(cfg):
    url = search_url(cfg, 0)
    print(f"search url: {url}")
    try:
        raw = fetch(url)
    except RuntimeError as e:
        print(f"FAIL {e}")
        return 1
    links = find_links(raw, cfg["host"])
    print(f"job links on page 1: {len(links)}")
    print(f"configured page_size: {cfg['search_request']['page_size']}")
    if len(links) != cfg["search_request"]["page_size"]:
        print("  page_size in the config does not match what came back. Fix it before --pull,")
        print("  or the startrow walk will skip or repeat rows.")
    m = re.search(r"([\d,]+)\s*(?:jobs?|results?|matches)", visible_text(raw), re.I)
    print(f"result count on page: {m.group(0) if m else 'not found - read it manually once'}")
    for l in links[:3]:
        print(f"  {l['posting_id']}  {l['slug'][:60]}")
    nxt = fetch(search_url(cfg, cfg["search_request"]["page_size"]))
    nl = find_links(nxt, cfg["host"])
    overlap = {x["posting_id"] for x in links} & {x["posting_id"] for x in nl}
    print(f"page 2 links: {len(nl)} | overlap with page 1: {len(overlap)} (want 0)")
    return 0


# ------------------------------------------------------------------ inspect
def cmd_inspect(cfg):
    raw = fetch(search_url(cfg, 0))
    links = find_links(raw, cfg["host"])
    if not links:
        print("no job links found. The href pattern may differ on this tenant.")
        return 1
    target = links[0]
    print(f"inspecting {target['url']}\n")
    page = fetch(target["url"])
    rec = parse_job(cfg, page)

    print(f"  {'OK ' if rec.get('title') else 'MISS'} title            {str(rec.get('title'))[:60]}")
    print(f"  {'OK ' if rec.get('location_text') else 'MISS'} location_text    {str(rec.get('location_text'))[:60]}")
    print(f"  {'OK ' if rec.get('jsonld') else 'MISS'} jsonld           "
          f"{'JobPosting present' if rec.get('jsonld') else 'none - label parsing is the only path'}")
    print("\nlabeled fields:")
    for k in cfg["labeled_fields"]:
        v = rec.get(k)
        print(f"  {'OK ' if v else 'MISS'} {k:<26} {str(v)[:50]}")
    print("\nsections:")
    for k in cfg["section_headings"]:
        v = rec.get(f"section_{k}")
        n = len(v) if v else 0
        print(f"  {'OK ' if n else 'MISS'} {k:<26} {n} chars")
    if rec.get("jsonld"):
        print("\njsonld keys:", sorted(rec["jsonld"].keys()))
    return 0


# ------------------------------------------------------------------ pull
def cmd_pull(cfg, out_path, max_pages=200):
    rl = cfg["rate_limit"]
    delay = 1.0 / rl["requests_per_second"]
    size = cfg["search_request"]["page_size"]

    found, seen_ids, startrow = [], set(), 0
    for _ in range(max_pages):
        raw = fetch(search_url(cfg, startrow), rl["max_retries"], rl["backoff_seconds"])
        links = find_links(raw, cfg["host"])
        fresh = [l for l in links if l["posting_id"] not in seen_ids]
        if not fresh:
            break
        for l in fresh:
            seen_ids.add(l["posting_id"])
        found.extend(fresh)
        print(f"  list {len(found)} (startrow {startrow})", file=sys.stderr)
        startrow += size
        time.sleep(delay)

    n = 0
    with open(out_path, "w") as f:
        for l in found:
            try:
                page = fetch(l["url"], rl["max_retries"], rl["backoff_seconds"])
            except RuntimeError as e:
                print(f"  skip {l['posting_id']}: {e}", file=sys.stderr)
                continue
            rec = parse_job(cfg, page)
            rec.update({
                "tenant_key": cfg["tenant_key"],
                "platform": cfg["platform"],
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "posting_id": l["posting_id"],
                "slug": l["slug"],
                "source_url": l["url"],
                "apply_url": cfg["endpoints"]["apply_pattern"].format(posting_id=l["posting_id"]),
            })
            f.write(json.dumps(rec) + "\n")
            n += 1
            if n % 25 == 0:
                print(f"  detail {n}/{len(found)}", file=sys.stderr)
            time.sleep(rl["detail_pause_seconds"])
    print(f"wrote {n} records -> {out_path}")
    return 0


# ------------------------------------------------------------------ normalize
def cmd_normalize(cfg, raw_path, out_path):
    """Contract fields only. No experience extraction, no classification."""
    out, n = [], 0
    with open(raw_path) as fin, open(out_path, "w") as fout:
        for line in fin:
            r = json.loads(line)
            desc = "\n\n".join(x for x in (r.get("section_description"),
                                           r.get("section_requirements")) if x)
            norm = {
                "tenant_key": r["tenant_key"],
                "platform": r["platform"],
                "employer_name": cfg["employer_name"],
                "market": cfg["market"],
                "state": cfg["state"],
                "retrieved_at": r["retrieved_at"],
                "source_url": r["source_url"],
                "apply_url": r["apply_url"],
                "source_job_id": r["posting_id"],
                "requisition_number": r.get("requisition_number"),
                "title": r.get("title"),
                "location_text": r.get("location_text"),
                "description_text": desc or None,
                "time_type": r.get("schedule"),
                "shift": r.get("shift"),
                "job_category": r.get("job_category"),
                "organization": r.get("organization"),
                "employee_status": r.get("employee_status"),
                "metro": r.get("nearest_major_market"),
            }
            fout.write(json.dumps(norm) + "\n")
            out.append(norm)
            n += 1
    keys = [k for k in out[0]] if out else []
    missing = {k: sum(1 for d in out if d.get(k) in (None, "")) for k in keys}
    print(f"normalized {n} -> {out_path}")
    print("null coverage (field: count):")
    for k, v in sorted(missing.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<22} {v}/{n}")
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
