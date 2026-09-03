"""
normalize/sort_key.py - the freshness sort key.

Ordering is decided HERE, in the data layer, not in a template or an interface.
A caller asks this module how to order records; it does not reinvent the rule.

WHY THIS EXISTS
---------------
Roughly 9% of the applicable set comes from an employer whose board publishes no
posting date at all - a source gap, mapped as posted_at = None during the adapter
build (see adapters/compass_api.py). Under a plain newest-first sort on posted_at
those records sank to the bottom permanently, and that employer went invisible in
the default view. This key lifts them into a defined position using first_seen as
an INTERNAL proxy for ordering only.

THE PROHIBITION - this is the point of putting the rule here
------------------------------------------------------------
`first_seen` is a SORT INPUT ONLY. It must never reach a display surface.

  - It is not returned by any function that produces card or page content.
  - It is not emitted in JobPosting JSON-LD, in ANY property.
  - It is not passed to a template, a serializer, or an API response that feeds
    the interface.
  - It is never converted to a relative-time string ("added 3 days ago").

A record without posted_at renders NO DATE AT ALL. Not "listed recently", not a
muted placeholder. The date row is simply absent. first_seen is our churn-
detection timestamp (see normalize/model.py: apply_seen_state); this module puts
it to a second, internal-only use. It is not the posting date and must never be
presented as one.

This is a DATA RULE, not a UI convention. It is written here so it survives
someone later finding first_seen in the sort key and wondering why the field is
never shown - the answer is that showing it would present a pipeline-ingest
timestamp as an employer posting date, which is a lie about the record.

KNOWN LIMITATION - cold start (recorded, deliberately not solved)
-----------------------------------------------------------------
On a tenant's first import every record gets the same first_seen, so tier 1
carries no ordering signal until a second cycle brings genuinely new postings.
The ordering within tier 1 sharpens with each pull. This is cold-start
behaviour, not a defect, and this module does not attempt to compensate for it.

ORDERING CONTRACT
-----------------
freshness_key returns (tier, date):

  tier 0 -> record has a real posted_at
  tier 1 -> record has none; first_seen is used as an internal proxy

Newest-first means: sort DESCENDING on date WITHIN each tier, and rank tier 0
entirely above tier 1. No interleaving - a real posted_at outranks a proxy
regardless of which calendar date is more recent. The tier is returned as data,
not folded into the date, precisely so a caller can still tell whether a record
has a real posting date; collapsing the two is how the proxy leaks into display.

Because posted_at and first_seen are ISO-8601 strings (YYYY-MM-DD...), a plain
descending string sort is newest-first. Records missing BOTH dates yield date ""
and, under descending order, sort last within tier 1 - no default date is
substituted, the current time is not used, and the record is not dropped.

    # Correct usage - freshness_order() orders the two tiers independently and
    # concatenates them, never interleaved:
    #     ordered = freshness_order(records)
    # Do NOT reach for sorted(records, key=freshness_key, reverse=True): reverse
    # flips the tier as well as the date, ranking the proxy tier above the real
    # one.

Python stdlib only. Read-only against normalize/model.py and the adapters.
"""


def freshness_key(record) -> tuple[int, str]:
    """
    Returns (tier, date) for newest-first ordering.

    tier 0 -> record has a real posted_at
    tier 1 -> record has none; first_seen is used as an internal proxy

    Sort descending on date within each tier. Tier 0 always ranks above tier 1.
    A record missing both posted_at and first_seen returns (1, "") and sorts
    last within tier 1 - no default date, no current time, and never dropped.

    The date is returned verbatim, exactly as stored (an ISO-8601 string). This
    function does not read first_seen for any purpose other than ordering, and
    the value it returns for tier 1 must not be forwarded to a display surface -
    see the module docstring prohibition.
    """
    posted_at = record.get("posted_at")
    if posted_at:
        return (0, posted_at)

    first_seen = record.get("first_seen")
    if first_seen:
        return (1, first_seen)

    return (1, "")


def freshness_order(records):
    """Return records newest-first under the tier contract above.

    The two tiers are ordered independently and concatenated - tier 0 (real
    posted_at) entirely above tier 1 (first_seen proxy), each sorted descending
    on its date. This is the single correct way to consume freshness_key; a
    plain sorted(..., key=freshness_key, reverse=True) would rank tier 1 above
    tier 0, because reverse would flip the tier too.

    Does not mutate the input. A record missing both dates sorts last within
    tier 1 (its date is "") - never dropped. The caller must still honour the
    module prohibition: first_seen ordered these rows, it must not be shown.
    """
    t0 = sorted((r for r in records if freshness_key(r)[0] == 0),
                key=lambda r: freshness_key(r)[1], reverse=True)
    t1 = sorted((r for r in records if freshness_key(r)[0] == 1),
                key=lambda r: freshness_key(r)[1], reverse=True)
    return t0 + t1
