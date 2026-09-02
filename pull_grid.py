#!/usr/bin/env python3
"""
Function + geo query grid — No-Experience Job Network

Tests sourcing by occupation rather than by experience phrase. Per searchapi's
own docs the `q` parameter accepts a location clause ("software engineer jobs
in San Francisco"), so this pulls one query per category with the market named
in the query string, and keeps the `location` parameter set as well.

Experience filtering is deliberately NOT in the query. The point of the test is
whether occupation + geo sources real local inventory that can then be filtered
for no-experience / entry-level language after ingestion.

Each query lands in its own capture directory so analyze_pull.py and
compare_pulls.py both work on it unchanged:

    grid_seattle/
      warehouse/raw/seattle/page_01.json
      security/raw/seattle/page_01.json
      ...

Stdlib only. Run:
    $env:SEARCHAPI_KEY="..."
    python pull_grid.py --market seattle --out ./grid_seattle
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://www.searchapi.io/api/v1/search"
TERMS_REFERENCE = "https://www.searchapi.io/terms"

MARKETS = {
    "seattle": ("Seattle, Washington, United States", "Seattle"),
    "tacoma": ("Tacoma, Washington, United States", "Tacoma"),
    "dallas": ("Dallas, Texas, United States", "Dallas"),
    "chicago": ("Chicago, Illinois, United States", "Chicago"),
}

# The eight categories. Terms are the plain category words — override with
# --queries to test different phrasings.
DEFAULT_TERMS = [
    "administrative",
    "customer service",
    "sales",
    "retail",
    "warehouse",
    "construction",
    "security",
    "facilities",
]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fetch(params, timeout=45):
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    safe_url = url.replace(params.get("api_key", "\x00"), "REDACTED")
    return json.loads(body), safe_url


def pull_one(term, market, location, city, api_key, max_pages, outdir, delay):
    q = f"{term} jobs in {city}"
    market_dir = os.path.join(outdir, slug(term), "raw", market)
    os.makedirs(market_dir, exist_ok=True)

    pages, token, total = [], None, 0
    for page_no in range(1, max_pages + 1):
        params = {
            "engine": "google_jobs",
            "q": q,
            "location": location,
            "hl": "en",
            "gl": "us",
            "api_key": api_key,
        }
        if token:
            params["next_page_token"] = token
        try:
            data, safe_url = fetch(params)
        except Exception as exc:
            print(f"    page {page_no} FAILED: {exc}", file=sys.stderr)
            pages.append({"page": page_no, "error": str(exc)})
            break

        retrieved_at = datetime.now(timezone.utc).isoformat()
        path = os.path.join(market_dir, f"page_{page_no:02d}.json")
        with open(path, "w") as f:
            json.dump({
                "_provenance": {
                    "source_id": "searchapi.google_jobs",
                    "source_url": safe_url,
                    "retrieved_at": retrieved_at,
                    "terms_reference": TERMS_REFERENCE,
                    "market": market,
                    "location_requested": location,
                    "query": q,
                    "query_term": term,
                    "page": page_no,
                },
                "response": data,
            }, f, indent=2)

        n = len(data.get("jobs") or [])
        total += n
        token = (data.get("pagination") or {}).get("next_page_token") or data.get("next_page_token")
        pages.append({"page": page_no, "jobs": n, "file": path})
        print(f"    page {page_no}: {n} jobs")
        if n == 0 or not token:
            print(f"    pagination exhausted after page {page_no}")
            break
        time.sleep(delay)
    return q, total, pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="seattle", help="single market key")
    ap.add_argument("--out", default="./grid_out")
    ap.add_argument("--queries", default=",".join(DEFAULT_TERMS),
                    help="comma-separated function terms")
    # 5 pages: the entry-level pull held 97-100% in-state through page 3 and
    # decayed from page 4. Deeper pages cost calls and return less local.
    ap.add_argument("--max-pages", type=int, default=5)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    api_key = os.environ.get("SEARCHAPI_KEY")
    if not api_key:
        sys.exit("SEARCHAPI_KEY not set in environment.")
    if args.market not in MARKETS:
        sys.exit(f"Unknown market '{args.market}'. Known: {list(MARKETS)}")

    location, city = MARKETS[args.market]
    terms = [t.strip() for t in args.queries.split(",") if t.strip()]
    os.makedirs(args.out, exist_ok=True)

    manifest = {
        "run_started_utc": datetime.now(timezone.utc).isoformat(),
        "market": args.market,
        "location_requested": location,
        "pattern": "{term} jobs in {city}",
        "max_pages_per_query": args.max_pages,
        "queries": {},
    }
    print(f"Market: {args.market} ({location})")
    print(f"Pattern: \"<term> jobs in {city}\"  |  {len(terms)} terms, "
          f"up to {args.max_pages} pages each "
          f"(max {len(terms) * args.max_pages} API calls)\n")

    grand = 0
    for term in terms:
        print(f"  {term.upper()}")
        q, total, pages = pull_one(term, args.market, location, city,
                                   api_key, args.max_pages, args.out, args.delay)
        manifest["queries"][slug(term)] = {"term": term, "q": q,
                                           "jobs": total, "pages": pages}
        grand += total
        print(f"    -> {total} records\n")

    manifest["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Done. {grand} raw records across {len(terms)} queries.")
    print(f"Output: {args.out}")
    print("Next: zip the output directory and upload it for analysis.")


if __name__ == "__main__":
    main()
