"""GSC indexation snapshot — records the indexed/impression trend each run so job-page
indexation can be watched climbing over time. Best-effort: never raises, never affects the
pull/publish (hooked into run_pull._finish the same way indexing.py hooks into _publish).

Reuses the Indexing API service account — which MUST be a verified GSC *Owner* for the Indexing
API to work at all — with the read-only webmasters scope, so no extra credential is needed.

Writes one JSON line per run to out/runs/gsc_status.jsonl (a durable time series) and prints a
one-line summary. Signals recorded:
  * site_clicks / site_impressions      — whole-site Search Analytics, trailing 28d
  * job_pages_with_impressions          — distinct /jobs/ pages Google has surfaced (the key
    trend: a page must be indexed to get an impression, so this climbs as indexation improves)
  * job_impressions / job_clicks        — volume on those job pages
  * sitemap_submitted / sitemap_indexed — from the Sitemaps API (indexed is often 0/lagging)
  * sample{}                            — URL Inspection coverageState + lastCrawlTime for a few
    fixed URLs (home, state hub, all-jobs hub), so a crawl finally landing is visible per-URL

Key: .env.local GOOGLE_INDEXING_KEY_FILE (path) or GOOGLE_INDEXING_KEY_JSON (inline).
Deps: google-auth (already used by indexing.py); stdlib urllib for the REST calls.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_LOCAL = os.path.join(ROOT, ".env.local")
LOG = os.path.join(ROOT, "out", "runs", "gsc_status.jsonl")

SITE = os.environ.get("GSC_SITE_URL") or "sc-domain:noprobjobs.com"
SITE_ENC = urllib.parse.quote(SITE, safe="")
SCOPE = ["https://www.googleapis.com/auth/webmasters.readonly"]
SA_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + SITE_ENC
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

# A few fixed URLs inspected each run for coverageState + lastCrawl (URL Inspection quota is
# 2000/day; this handful is negligible). The indexed homepage, the state hub, the all-jobs hub.
SAMPLE = [
    "https://noprobjobs.com/",
    "https://noprobjobs.com/washington/",
    "https://noprobjobs.com/jobs/",
]


def _env_val(name):
    try:
        env = open(ENV_LOCAL, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*?)\s*$", env, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def _load_key():
    path = _env_val("GOOGLE_INDEXING_KEY_FILE")
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    inline = _env_val("GOOGLE_INDEXING_KEY_JSON")
    if inline:
        return json.loads(inline)
    return None


def _token(info):
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPE)
    creds.refresh(Request())
    return creds.token


def _post(url, body, token):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token}, method="GET")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def snapshot(stamp=None):
    """The one call run_pull makes. Never raises — returns the recorded dict (or an error dict)."""
    try:
        return _run(stamp)
    except Exception as e:
        print(f"[gsc_status] skipped (non-fatal): {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _run(stamp):
    info = _load_key()
    if not info:
        print("[gsc_status] no GOOGLE_INDEXING_KEY_FILE / GOOGLE_INDEXING_KEY_JSON in .env.local - skipping")
        return {"ok": False, "reason": "no key"}

    token = _token(info)
    now = datetime.now(timezone.utc)
    stamp = stamp or now.strftime("%Y%m%dT%H%M%SZ")
    # Search Analytics data lags ~2-3 days; end the window 2 days back and trail 28 days.
    end = now.date() - timedelta(days=2)
    start = end - timedelta(days=28)
    sd, ed = start.isoformat(), end.isoformat()
    rec = {"stamp": stamp, "recorded_at": now.isoformat(), "window": [sd, ed], "ok": True}

    # whole-site totals
    try:
        row = (_post(SA_BASE + "/searchAnalytics/query",
                     {"startDate": sd, "endDate": ed, "dimensions": []}, token).get("rows") or [{}])[0]
        rec["site_clicks"] = int(row.get("clicks", 0))
        rec["site_impressions"] = int(row.get("impressions", 0))
    except Exception as e:
        rec["site_error"] = f"{type(e).__name__}: {e}"

    # job pages with >=1 impression (a page must be indexed to earn an impression)
    try:
        rows = _post(SA_BASE + "/searchAnalytics/query",
                     {"startDate": sd, "endDate": ed, "dimensions": ["page"],
                      "dimensionFilterGroups": [{"filters": [
                          {"dimension": "page", "operator": "contains", "expression": "/jobs/"}]}],
                      "rowLimit": 5000}, token).get("rows") or []
        rec["job_pages_with_impressions"] = len(rows)
        rec["job_impressions"] = int(sum(r["impressions"] for r in rows))
        rec["job_clicks"] = int(sum(r["clicks"] for r in rows))
    except Exception as e:
        rec["job_error"] = f"{type(e).__name__}: {e}"

    # sitemap submitted/indexed
    try:
        subs = idx = 0
        for s in (_get(SA_BASE + "/sitemaps", token).get("sitemap") or []):
            for c in (s.get("contents") or []):
                subs += int(c.get("submitted", 0))
                idx += int(c.get("indexed", 0))
        rec["sitemap_submitted"] = subs
        rec["sitemap_indexed"] = idx
    except Exception as e:
        rec["sitemap_error"] = f"{type(e).__name__}: {e}"

    # URL Inspection sample — per-URL coverage + last crawl
    sample = {}
    for u in SAMPLE:
        try:
            r = _post(INSPECT, {"inspectionUrl": u, "siteUrl": SITE, "languageCode": "en-US"}, token)
            s = r.get("inspectionResult", {}).get("indexStatusResult", {})
            sample[u] = {"coverage": s.get("coverageState"), "verdict": s.get("verdict"),
                         "lastCrawl": s.get("lastCrawlTime")}
        except Exception as e:
            sample[u] = {"error": f"{type(e).__name__}: {e}"}
    rec["sample"] = sample

    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[gsc_status] log write skipped: {e}")

    print(f"[gsc_status] job pages w/ impressions={rec.get('job_pages_with_impressions', '?')} "
          f"(imp {rec.get('job_impressions', '?')}, clk {rec.get('job_clicks', '?')}) | "
          f"site imp {rec.get('site_impressions', '?')} clk {rec.get('site_clicks', '?')} | "
          f"sitemap indexed {rec.get('sitemap_indexed', '?')}/{rec.get('sitemap_submitted', '?')}")
    return rec


def trend():
    """Print the recorded time series as a table (python -m analyze.gsc_status --trend)."""
    if not os.path.exists(LOG):
        print("no snapshots yet (out/runs/gsc_status.jsonl). Run a pull or `python -m analyze.gsc_status`.")
        return
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    print(f"{'recorded (UTC)':<21}{'jobPgsImp':>10}{'jobImp':>8}{'siteImp':>9}{'siteClk':>8}{'smIdx/sub':>12}   home/wa/jobs lastCrawl")
    print("-" * 100)
    for r in rows[-40:]:
        ra = (r.get("recorded_at") or r.get("stamp") or "")[:19]
        sm = f"{r.get('sitemap_indexed','?')}/{r.get('sitemap_submitted','?')}"
        s = r.get("sample") or {}
        def _lc(u):
            v = (s.get(u) or {}).get("lastCrawl")
            return v[:10] if v else "-"
        crawl = f"{_lc('https://noprobjobs.com/')}/{_lc('https://noprobjobs.com/washington/')}/{_lc('https://noprobjobs.com/jobs/')}"
        print(f"{ra:<21}{r.get('job_pages_with_impressions','?'):>11}{r.get('job_impressions','?'):>8}"
              f"{r.get('site_impressions','?'):>9}{r.get('site_clicks','?'):>8}{sm:>12}   {crawl}")


if __name__ == "__main__":
    import sys
    if "--trend" in sys.argv[1:]:
        trend()
    else:
        print(json.dumps(snapshot(), indent=2, ensure_ascii=False))
