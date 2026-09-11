"""Shared paginating-fetch helper for every crawl adapter.

ONE rule, enforced in ONE place: a transient upstream failure (a 500/502/503/504
load-balancer blip, a 429 throttle) is retried with exponential backoff; if a page
STILL fails, the crawl is TRUNCATED and the caller must abort WITHOUT writing.

Why this lives in shared code, against the otherwise-deliberate "each adapter owns its
own fetch/log" fork (Finding 42): retry/abort is infrastructure, not extraction
vocabulary. A short read that reports success is worse than a failure - every downstream
gate (movement, density, the completeness halt) trusts the record count a source reports,
so a truncation written as complete defeats all of them at once. This swallow-then-write-
partial shape had been copied into all six adapters; centralising it here means one
implementation to verify, and the onboarding SOP (/add-tenant) points adapter seven at
fetch_paged so it can't be reintroduced.

Usage in an adapter's index/discovery loop (page- or offset-cursored alike):

    from adapters.paginate import fetch_paged, Truncated
    try:
        while ...:
            r = fetch_paged(lambda: fetch_page(...), label=f"page {page}: ")
            ...  # process a guaranteed-200 response, persist the raw page, advance
    except Truncated as e:
        print(f"\\n!! ABORT: {e}. Partial capture DISCARDED (prior data kept).")
        log(tenant, "index_abort", detail=str(e))
        return 1        # run_pull reads non-zero as FAILED (source broke), not SKIPPED

Because Truncated is raised mid-loop, the post-loop write is skipped automatically -
there is no code path left that writes a partial set as if it were complete.
"""
import time

# Transient upstream statuses worth a retry. 429 = throttle; 5xx = server/LB blip.
RETRY_STATUS = frozenset({500, 502, 503, 504, 429})
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0      # seconds, doubled each attempt: 2s, 4s, 8s


class Truncated(Exception):
    """A page still failed after retries. The caller MUST NOT write a partial capture:
    catch this, skip the write, and return non-zero so the run marks the source FAILED
    (distinct from a SKIPPED short-enumerate, which means the pipeline is working)."""


def fetch_paged(fetch_fn, *, label=""):
    """Fetch one page, retrying transient RETRY_STATUS with exponential backoff.

    Returns the response once it is 200. Raises Truncated if it still fails after
    MAX_RETRIES, so a caller can never mistake a short read for a complete one.

    fetch_fn: a zero-arg callable returning a requests.Response - a closure over the
    caller's cursor (e.g. ``lambda: fetch_page(tenant, page)``). It is invoked once per
    attempt, so it re-fetches the SAME page on each retry.
    label: optional prefix for the progress line (e.g. "page 16: ").
    """
    r = fetch_fn()
    tries = 0
    while r.status_code in RETRY_STATUS and tries < MAX_RETRIES:
        tries += 1
        back = RETRY_BACKOFF * (2 ** (tries - 1))
        print(f"    {label}transient {r.status_code}, retry {tries}/{MAX_RETRIES} in {back:.0f}s")
        time.sleep(back)
        r = fetch_fn()
    if r.status_code != 200:
        raise Truncated(f"{label}status {r.status_code} after {tries} "
                        f"retr{'y' if tries == 1 else 'ies'}")
    return r
