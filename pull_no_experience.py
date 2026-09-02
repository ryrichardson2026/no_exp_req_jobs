#!/usr/bin/env python3
"""
First job pull — No-Experience Job Network
Part III, Immediate item 3. Method per "First pull — method" in the master doc.

Query on the words "no experience". No industry selected.
Markets: Seattle, Tacoma, Dallas, Chicago.

Writes RAW, UNMODIFIED responses to disk. No normalization, no filtering,
no field renaming happens here. That is deliberate: the raw capture is the
evidence, and the analyzer reads it separately. Nothing is discarded.

Stdlib only. Run:
    export SEARCHAPI_KEY=...
    python3 pull_no_experience.py --out ./pull_2026-08-25
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://www.searchapi.io/api/v1/search"
TERMS_REFERENCE = "https://www.searchapi.io/terms"

# Canonical location strings. searchapi echoes back `location_used` in the
# response — the analyzer checks that echo against what we asked for, because
# a silently-substituted location is one of the documented aggregator defects.
MARKETS = {
    "seattle": "Seattle, Washington, United States",
    "tacoma": "Tacoma, Washington, United States",
    "dallas": "Dallas, Texas, United States",
    "chicago": "Chicago, Illinois, United States",
}


def fetch(params, timeout=45):
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    # Return the redacted URL for provenance — never write the key to disk.
    safe_url = url.replace(params.get("api_key", "\x00"), "REDACTED")
    return json.loads(body), safe_url


def pull_market(market, location, query, api_key, max_pages, outdir, delay):
    market_dir = os.path.join(outdir, "raw", market)
    os.makedirs(market_dir, exist_ok=True)

    pages = []
    token = None
    for page_no in range(1, max_pages + 1):
        params = {
            "engine": "google_jobs",
            "q": query,
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
            print(f"  [{market}] page {page_no} FAILED: {exc}", file=sys.stderr)
            pages.append({"page": page_no, "error": str(exc)})
            break

        retrieved_at = datetime.now(timezone.utc).isoformat()
        path = os.path.join(market_dir, f"page_{page_no:02d}.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "_provenance": {
                        "source_id": "searchapi.google_jobs",
                        "source_url": safe_url,
                        "retrieved_at": retrieved_at,
                        "terms_reference": TERMS_REFERENCE,
                        "market": market,
                        "location_requested": location,
                        "query": query,
                        "page": page_no,
                    },
                    "response": data,
                },
                f,
                indent=2,
            )

        n = len(data.get("jobs") or [])
        token = (data.get("pagination") or {}).get("next_page_token") or data.get("next_page_token")
        print(f"  [{market}] page {page_no}: {n} jobs -> {path}")
        pages.append({"page": page_no, "jobs": n, "file": path, "retrieved_at": retrieved_at})

        if n == 0 or not token:
            print(f"  [{market}] pagination exhausted after page {page_no}")
            break
        time.sleep(delay)

    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./pull_out", help="output directory")
    ap.add_argument("--query", default="no experience", help='q string; default per doc')
    ap.add_argument("--max-pages", type=int, default=10, help="10 results/page")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between calls")
    ap.add_argument("--markets", default=",".join(MARKETS), help="comma list")
    args = ap.parse_args()

    api_key = os.environ.get("SEARCHAPI_KEY")
    if not api_key:
        sys.exit("SEARCHAPI_KEY not set in environment.")

    selected = [m.strip() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in selected if m not in MARKETS]
    if unknown:
        sys.exit(f"Unknown market(s): {unknown}. Known: {list(MARKETS)}")

    os.makedirs(args.out, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    manifest = {
        "run_started_utc": started,
        "query": args.query,
        "engine": "google_jobs",
        "provider": "searchapi.io",
        "max_pages_per_market": args.max_pages,
        "markets": {},
    }

    print(f'Query: "{args.query}"  |  markets: {selected}')
    for market in selected:
        print(f"\n{market.upper()}")
        manifest["markets"][market] = {
            "location_requested": MARKETS[market],
            "pages": pull_market(
                market, MARKETS[market], args.query, api_key,
                args.max_pages, args.out, args.delay,
            ),
        }

    manifest["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    mpath = os.path.join(args.out, "manifest.json")
    with open(mpath, "w") as f:
        json.dump(manifest, f, indent=2)

    total = sum(
        p.get("jobs", 0)
        for m in manifest["markets"].values()
        for p in m["pages"]
    )
    print(f"\nDone. {total} raw job records across {len(selected)} markets.")
    print(f"Manifest: {mpath}")
    print("Next: zip the output directory and upload it for analysis.")


if __name__ == "__main__":
    main()
