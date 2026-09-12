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
  * quota-capped per run (DAILY_CAP) with un-submitted URLs left un-recorded so they retry next run.
  * best-effort: ANY error is logged and swallowed. Indexing can never affect the pull/publish.

Key: .env.local GOOGLE_INDEXING_KEY_FILE (path to the SA json) or GOOGLE_INDEXING_KEY_JSON (inline).
Deps: google-auth + requests (already installed). Stdlib-only import at module load; the heavy
imports are inside functions so a missing dep degrades to a logged skip, never a crash.
"""
import json
import os
import re
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_LOCAL = os.path.join(ROOT, ".env.local")
MANIFEST = os.path.join(ROOT, "prerender", "out", "_lifecycle.json")
STATE = os.path.join(ROOT, "out", "runs", "indexing_state.json")

SITE = (os.environ.get("SITE_URL") or "https://noprobjobs.com").rstrip("/")
SCOPE = ["https://www.googleapis.com/auth/indexing"]
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
# Per-run submission cap = the Indexing API publish quota, confirmed 200/day in Cloud Console
# (APIs & Services -> Indexing API -> Quotas). Both URL_UPDATED and URL_DELETED draw from it.
DAILY_CAP = 200


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


def _save_state(live, deleted):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"live": sorted(live), "deleted": sorted(deleted),
                   "saved_at": datetime.now(timezone.utc).isoformat()}, fh, indent=2)


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
    # Bootstrap: no prior state -> seed known-live, submit nothing (the sitemap already exposes
    # existing pages; we only ping Google for pages that become new AFTER this point).
    if state is None:
        _save_state(cur_live, cur_retired)   # treat current retired as already-handled at seed time
        print(f"[indexing] bootstrap: seeded {len(cur_live)} live + {len(cur_retired)} retired URLs, submitted 0")
        return {"ok": True, "bootstrap": True, "seeded_live": len(cur_live)}

    prev_live = set(state.get("live", []))
    prev_deleted = set(state.get("deleted", []))
    new_pages = sorted(cur_live - prev_live)
    to_delete = sorted(cur_retired - prev_deleted)

    if not new_pages and not to_delete:
        # keep the known set current (drop pages that left live; prune deleted to still-retired)
        _save_state(cur_live, prev_deleted & cur_retired)
        print("[indexing] nothing to submit (0 new, 0 newly-retired)")
        return {"ok": True, "updated": 0, "deleted": 0}

    import requests
    token = _token(info)
    session = requests.Session()

    def publish(url, typ):
        r = session.post(ENDPOINT,
                         headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                         data=json.dumps({"url": url, "type": typ}), timeout=30)
        return r.status_code, r.text

    budget = DAILY_CAP
    submitted_new, submitted_del = [], []
    upd_ok = upd_fail = del_ok = del_fail = 0

    # Deletions first — a retired page should stop being served promptly.
    for url in to_delete:
        if budget <= 0:
            break
        code, body = publish(url, "URL_DELETED"); budget -= 1
        if code == 200:
            del_ok += 1; submitted_del.append(url)
        else:
            del_fail += 1; print(f"[indexing] URL_DELETED {code}: {url}  {body[:120]}")
    for url in new_pages:
        if budget <= 0:
            break
        code, body = publish(url, "URL_UPDATED"); budget -= 1
        if code == 200:
            upd_ok += 1; submitted_new.append(url)
        else:
            upd_fail += 1; print(f"[indexing] URL_UPDATED {code}: {url}  {body[:120]}")

    attempted = len(submitted_new) + len(submitted_del) + upd_fail + del_fail
    deferred = (len(new_pages) + len(to_delete)) - attempted
    # New known-live = still live AND (previously known OR just submitted). Un-submitted new pages
    # (quota cap or a transient failure) stay OUT, so they retry next run. Deleted = prior+new,
    # pruned to those still retired so the set can't grow without bound.
    new_known_live = cur_live & (prev_live | set(submitted_new))
    new_deleted = (prev_deleted | set(submitted_del)) & cur_retired
    _save_state(new_known_live, new_deleted)

    msg = f"[indexing] URL_UPDATED ok={upd_ok} fail={upd_fail} | URL_DELETED ok={del_ok} fail={del_fail}"
    if deferred > 0:
        msg += f" | deferred={deferred} (per-run cap {DAILY_CAP}; retries next run)"
    print(msg)
    return {"ok": True, "updated": upd_ok, "deleted": del_ok,
            "update_fail": upd_fail, "delete_fail": del_fail, "deferred": max(0, deferred)}


if __name__ == "__main__":
    # Manual run / test: same path run_pull uses after a publish.
    print(json.dumps(submit_after_publish(), indent=2))
