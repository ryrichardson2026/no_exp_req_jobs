"""Google Indexing API submitter — run AFTER a successful publish.

Notifies Google of:
  * NEW job pages     -> URL_UPDATED   (live now, not previously known to us)
  * RETIRED job pages -> URL_DELETED   (in the bake's retired[]: retire.mjs deleted the file so
                                        the route 404s). NOT on mere expiry — a 410 page still
                                        exists in its window, so it is never submitted as deleted.

Design:
  * "new pages only" — we diff the current live set against a small local state file, so only
    genuinely new URLs are pinged. Existing pages are discovered by Google via the sitemap; we do
    not backfill the whole site (that would blow the daily quota). The FIRST run bootstraps: it
    seeds the known-live set and submits nothing.
  * quota-capped per CALENDAR DAY (DAILY_CAP, Pacific-midnight reset, persisted + shared across
    same-day runs) with un-submitted URLs left un-recorded so they retry next run.
  * best-effort: ANY error is logged and swallowed. Indexing can never affect the pull/publish.

Key: .env.local GOOGLE_INDEXING_KEY_FILE (path to the SA json) or GOOGLE_INDEXING_KEY_JSON (inline).
Deps: google-auth + requests (already installed). Stdlib-only import at module load; the heavy
imports are inside functions so a missing dep degrades to a logged skip, never a crash.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_LOCAL = os.path.join(ROOT, ".env.local")
MANIFEST = os.path.join(ROOT, "prerender", "out", "_lifecycle.json")
STATE = os.path.join(ROOT, "out", "runs", "indexing_state.json")

SITE = (os.environ.get("SITE_URL") or "https://noprobjobs.com").rstrip("/")
SCOPE = ["https://www.googleapis.com/auth/indexing"]
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
# Submission cap = the Indexing API publish quota, confirmed 200/day in Cloud Console
# (APIs & Services -> Indexing API -> Quotas). Both URL_UPDATED and URL_DELETED draw from it.
DAILY_CAP = 200

# Google's quota is per CALENDAR DAY, resetting at Pacific midnight (the account's project
# timezone). The drawdown is tracked in the state file as {"date","used"} and SHARED across every
# run on the same PT day — so same-day re-runs (a kill/fix republish) draw the SAME 200 budget
# instead of each getting a fresh 200. That per-run-reset bug drew 121x HTTP 429 on 2026-09-26.


def _today_pt():
    """US-Pacific calendar date, dependency-free. zoneinfo needs a tz database that the Windows
    pull host lacks (and `tzdata` isn't installed) — importing ZoneInfo there raises and would
    silently disable indexing. US DST = 2nd Sunday of March to 1st Sunday of November: PDT UTC-7
    else PST UTC-8. Day-grain is all a calendar-day quota bucket needs, so the ~2am switch is
    approximated at the UTC hour of the transition."""
    u = datetime.now(timezone.utc)
    y = u.year

    def nth_sunday(month, n):                     # date of the n-th Sunday of (y, month)
        first = datetime(y, month, 1, tzinfo=timezone.utc)
        first_sun = 1 + (6 - first.weekday()) % 7   # Mon=0..Sun=6
        return first_sun + 7 * (n - 1)

    dst_start = datetime(y, 3, nth_sunday(3, 2), 10, tzinfo=timezone.utc)   # ~2am PST -> PDT
    dst_end = datetime(y, 11, nth_sunday(11, 1), 9, tzinfo=timezone.utc)    # ~2am PDT -> PST
    offset = -7 if dst_start <= u < dst_end else -8
    return (u + timedelta(hours=offset)).strftime("%Y-%m-%d")


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


def _load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return None


def _save_state(live, deleted, submitted=None, quota=None):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    d = {"live": sorted(live), "deleted": sorted(deleted),
         "saved_at": datetime.now(timezone.utc).isoformat()}
    if submitted is not None:
        # Every URL ever POSTed to the Indexing API. Distinct from `live` (known-exists): the
        # bootstrap seeds `live` without submitting, so `submitted` is what the backlog-fill
        # dedupes against so each page is pinged once, never re-spammed.
        d["submitted"] = sorted(submitted)
    if quota is not None:
        # {"date": PT YYYY-MM-DD, "used": n} — the per-calendar-day quota drawdown, shared across
        # every run on that PT day so the real 200/day Google quota is never overshot.
        d["quota"] = quota
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2)


def submit_after_publish():
    """The one call run_pull makes after a successful deploy. Never raises — returns a summary."""
    try:
        return _run()
    except Exception as e:
        print(f"[indexing] skipped (non-fatal): {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _run():
    info = _load_key()
    if not info:
        print("[indexing] no GOOGLE_INDEXING_KEY_FILE / GOOGLE_INDEXING_KEY_JSON in .env.local - skipping")
        return {"ok": False, "reason": "no key"}

    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    cur_live = {SITE + p for p in manifest.get("live", [])}
    cur_retired = {SITE + p for p in manifest.get("retired", [])}

    state = _load_state()
    # Per-calendar-day quota drawdown (Pacific). used_today carries across same-day runs; it resets
    # to 0 once the PT date rolls over. This run may spend at most DAILY_CAP - used_today.
    today = _today_pt()
    qstate = (state or {}).get("quota") or {}
    used_today = qstate.get("used", 0) if qstate.get("date") == today else 0
    # Bootstrap: no prior state -> seed known-live, submit nothing (the sitemap already exposes
    # existing pages; we only ping Google for pages that become new AFTER this point).
    if state is None:
        # Seed known-live + retired, submit nothing THIS run. submitted={} so subsequent runs
        # treat the whole live set as backlog and fill the daily quota until it's cleared.
        _save_state(cur_live, cur_retired, submitted=set(), quota={"date": today, "used": 0})
        print(f"[indexing] bootstrap: seeded {len(cur_live)} live + {len(cur_retired)} retired URLs, submitted 0")
        return {"ok": True, "bootstrap": True, "seeded_live": len(cur_live)}

    prev_live = set(state.get("live", []))
    prev_deleted = set(state.get("deleted", []))
    submitted = set(state.get("submitted", []))      # every URL ever POSTed to the Indexing API
    new_pages = sorted(cur_live - prev_live)
    to_delete = sorted(cur_retired - prev_deleted)

    if not new_pages and not to_delete and cur_live <= submitted:
        # nothing new/retired AND every live page already notified -> idle day, spend nothing.
        _save_state(cur_live, prev_deleted & cur_retired, submitted & (cur_live | cur_retired),
                    quota={"date": today, "used": used_today})
        print("[indexing] nothing to submit (0 new, 0 newly-retired, backlog cleared)")
        return {"ok": True, "updated": 0, "deleted": 0, "backlog": 0}

    import requests
    token = _token(info)
    session = requests.Session()

    def publish(url, typ):
        r = session.post(ENDPOINT,
                         headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                         data=json.dumps({"url": url, "type": typ}), timeout=30)
        return r.status_code, r.text

    budget = max(0, DAILY_CAP - used_today)   # per-calendar-day remainder, not a fresh 200 per run
    start_budget = budget
    submitted_new, submitted_del, submitted_backlog = [], [], []
    upd_ok = upd_fail = del_ok = del_fail = bl_ok = bl_fail = 0

    # Deletions first — a retired page should stop being served promptly.
    for url in to_delete:
        if budget <= 0:
            break
        code, body = publish(url, "URL_DELETED"); budget -= 1
        if code == 200:
            del_ok += 1; submitted_del.append(url)
        else:
            del_fail += 1; print(f"[indexing] URL_DELETED {code}: {url}  {body[:120]}")
    # Then genuinely NEW pages (this publish added them).
    for url in new_pages:
        if budget <= 0:
            break
        code, body = publish(url, "URL_UPDATED"); budget -= 1
        if code == 200:
            upd_ok += 1; submitted_new.append(url)
        else:
            upd_fail += 1; print(f"[indexing] URL_UPDATED {code}: {url}  {body[:120]}")

    # BACKLOG FILL — spend the REST of the daily quota on live pages Google was never notified
    # about (the bootstrap seeded `live` as known but submitted nothing; the sitemap alone was too
    # slow to get a new domain crawled). Newest first by the trailing job number so fresh jobs are
    # crawled first. Each page is submitted ONCE (recorded in `submitted`); once the backlog is
    # cleared this loop is empty and daily volume is just new+retired — known URLs are never re-spammed.
    def _jobnum(u):
        m = re.search(r"-(\d+)/?$", u)
        return int(m.group(1)) if m else 0
    already = submitted | set(submitted_new)
    backlog = sorted(cur_live - already, key=_jobnum, reverse=True)
    backlog_total = len(backlog)
    for url in backlog:
        if budget <= 0:
            break
        code, body = publish(url, "URL_UPDATED"); budget -= 1
        if code == 200:
            bl_ok += 1; submitted_backlog.append(url)
        else:
            bl_fail += 1
            if bl_fail <= 3:
                print(f"[indexing] backlog {code}: {url}  {body[:120]}")

    # New known-live = still live AND (previously known OR just submitted-new). `submitted` grows
    # with everything POSTed, pruned to what is still live/retired so it can't grow unbounded.
    new_known_live = cur_live & (prev_live | set(submitted_new))
    new_deleted = (prev_deleted | set(submitted_del)) & cur_retired
    new_submitted = (submitted | set(submitted_new) | set(submitted_backlog) | set(submitted_del)) \
        & (cur_live | cur_retired)
    sent = start_budget - budget                 # POSTs made THIS run
    used_after = used_today + sent               # total drawn against TODAY's PT quota
    _save_state(new_known_live, new_deleted, new_submitted, quota={"date": today, "used": used_after})

    backlog_left = backlog_total - bl_ok
    print(f"[indexing] new ok={upd_ok} fail={upd_fail} | retired ok={del_ok} fail={del_fail} | "
          f"backlog ok={bl_ok} fail={bl_fail} (remaining {backlog_left}) | "
          f"quota used {used_after}/{DAILY_CAP} today ({sent} this run, {used_today} earlier)")
    return {"ok": True, "updated": upd_ok, "deleted": del_ok, "backlog": bl_ok,
            "update_fail": upd_fail, "delete_fail": del_fail,
            "backlog_remaining": backlog_left,
            "quota_used_today": used_after, "quota_sent_this_run": sent, "quota_day": today}


if __name__ == "__main__":
    # Manual run / test: same path run_pull uses after a publish.
    print(json.dumps(submit_after_publish(), indent=2))
