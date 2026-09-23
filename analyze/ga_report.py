"""GA4 engagement / demographics snapshot — read-only pull from the Data API.

Prints who is actually ENGAGING with noprobjobs.com: by state, city, language, device,
and (if Google Signals ever populates) age/gender/interests. Read-only; touches nothing.

    python -m analyze.ga_report                 # last 28 days, all reports
    python -m analyze.ga_report --days 90        # wider window
    python -m analyze.ga_report --property 553393665
    python -m analyze.ga_report --json           # raw rows as JSON (for piping)

Auth: reuses the SAME service account as the Indexing API — .env.local GOOGLE_INDEXING_KEY_FILE
(path) or GOOGLE_INDEXING_KEY_JSON (inline). That SA must be a Viewer on the GA4 property
(Admin -> Property Access Management) and the "Google Analytics Data API" must be enabled in the
SA's Cloud project. Both were set up 2026-09-23; see the ga4-property memory.

Notes baked into the reporting, not the data:
  * Age/Gender/Interests come from Google Signals; they read "(no data)" until Signals is enabled
    AND traffic clears Google's privacy threshold. Empty is expected on a low-traffic new property.
  * Owner test traffic (Vancouver WA) massively skews engagement time / desktop sessions. Use
    --exclude-city to strip a city (e.g. Vancouver) from every report for a cleaner read.

Deps: google-auth + requests (already installed, same as indexing.py).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_LOCAL = os.path.join(ROOT, ".env.local")

SCOPE = ["https://www.googleapis.com/auth/analytics.readonly"]
DEFAULT_PROPERTY = os.environ.get("GA4_PROPERTY_ID") or "553393665"   # no_prob_jobs
ENDPOINT = "https://analyticsdata.googleapis.com/v1beta/properties/{}:runReport"


def _env_val(name):
    try:
        env = open(ENV_LOCAL, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=\s*(.*?)\s*$', env, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def _load_key():
    """SA key dict from GOOGLE_INDEXING_KEY_FILE (path) or GOOGLE_INDEXING_KEY_JSON (inline)."""
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


def _fmt_dur(seconds):
    """Total engagement seconds -> compact h/m/s."""
    s = int(round(float(seconds)))
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


class GA:
    def __init__(self, prop, token, start, end, exclude_city=None):
        self.url = ENDPOINT.format(prop)
        self.hdr = {"Authorization": "Bearer " + token}
        self.start, self.end = start, end
        self.exclude_city = exclude_city
        import requests
        self.session = requests.Session()

    def report(self, dims, mets, limit=25, order_metric=None):
        body = {
            "dateRanges": [{"startDate": self.start, "endDate": self.end}],
            "dimensions": [{"name": d} for d in dims],
            "metrics": [{"name": m} for m in mets],
            "limit": limit,
        }
        # Server-side exclusion so the dropped city's sessions leave the region/country/device
        # AGGREGATES too, not just its own row. A client-side row filter can't do that.
        if self.exclude_city:
            body["dimensionFilter"] = {"notExpression": {"filter": {
                "fieldName": "city",
                "stringFilter": {"value": self.exclude_city, "matchType": "EXACT"}}}}
        if order_metric:
            body["orderBys"] = [{"metric": {"metricName": order_metric}, "desc": True}]
        r = self.session.post(self.url, headers=self.hdr, json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {json.dumps(r.json().get('error', r.text))[:400]}")
        return r.json()


def _rows(data):
    for row in data.get("rows", []):
        dims = [v["value"] for v in row["dimensionValues"]]
        mets = [v["value"] for v in row["metricValues"]]
        yield dims, mets


def print_engagement(ga, title, dim):
    """A geo/segment table with derived engagement-rate % and avg engagement/user."""
    mets = ["activeUsers", "engagedSessions", "engagementRate", "userEngagementDuration", "keyEvents"]
    data = ga.report([dim], mets, order_metric="activeUsers")
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    rows = list(_rows(data))
    if not rows:
        print("  (no data)")
        return
    print(f"  {'segment':<22}{'users':>7}{'eng.sess':>10}{'eng.rate':>10}{'avg/user':>10}{'conv':>7}")
    print("  " + "-" * 64)
    for d, m in rows:
        users, esess, erate, edur, conv = m
        u = int(users) or 1
        avg = _fmt_dur(float(edur) / u)
        rate = f"{float(erate) * 100:.0f}%"
        print(f"  {d[0][:21]:<22}{users:>7}{esess:>10}{rate:>10}{avg:>10}{conv:>7}")


def print_simple(ga, title, dim, mets):
    data = ga.report([dim], mets, order_metric=mets[0])
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    rows = list(_rows(data))
    if not rows:
        print("  (no data)  <- Google Signals not populating (off or below threshold)"
              if dim in ("userAgeBracket", "userGender", "brandingInterest") else "  (no data)")
        return
    print(f"  {'segment':<24}" + "".join(f"{m:>14}" for m in mets))
    for d, m in rows:
        print(f"  {d[0][:23]:<24}" + "".join(f"{v:>14}" for v in m))


def main():
    ap = argparse.ArgumentParser(description="GA4 engagement/demographics snapshot (read-only)")
    ap.add_argument("--days", type=int, default=28, help="trailing window in days (default 28)")
    ap.add_argument("--property", default=DEFAULT_PROPERTY, help="GA4 property id")
    ap.add_argument("--exclude-city", default=None,
                    help="drop this city from every table (e.g. Vancouver = owner test traffic)")
    ap.add_argument("--json", action="store_true", help="dump raw country/region/city rows as JSON")
    args = ap.parse_args()

    info = _load_key()
    if not info:
        print("no GOOGLE_INDEXING_KEY_FILE / GOOGLE_INDEXING_KEY_JSON in .env.local", file=sys.stderr)
        return 2

    start = f"{args.days}daysAgo"
    ga = GA(args.property, _token(info), start, "today", exclude_city=args.exclude_city)
    print(f"GA4 property {args.property}  |  window {start}..today")
    if args.exclude_city:
        print(f"(excluding city everywhere: {args.exclude_city})")

    if args.json:
        out = {}
        for dim in ("country", "region", "city"):
            out[dim] = [{"seg": d[0], "metrics": m} for d, m in _rows(
                ga.report([dim], ["activeUsers", "engagedSessions", "keyEvents"], order_metric="activeUsers"))]
        print(json.dumps(out, indent=2))
        return 0

    print_engagement(ga, "BY STATE / REGION", "region")
    print_engagement(ga, "BY CITY", "city")
    print_engagement(ga, "BY COUNTRY", "country")
    print_simple(ga, "BY LANGUAGE", "language", ["activeUsers", "engagedSessions", "keyEvents"])
    print_simple(ga, "BY DEVICE", "deviceCategory", ["activeUsers", "engagedSessions", "keyEvents"])
    print_simple(ga, "AGE (Google Signals)", "userAgeBracket", ["activeUsers", "keyEvents"])
    print_simple(ga, "GENDER (Google Signals)", "userGender", ["activeUsers", "keyEvents"])
    print_simple(ga, "INTERESTS (Google Signals)", "brandingInterest", ["activeUsers", "keyEvents"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
