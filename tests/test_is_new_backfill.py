"""
Guards the single "new jobs" definition (normalize/model).

THE rule is effective_new_date(rec) = coalesce(posted_at, first_seen), minus
onboarding backfill (first_seen on/before the tenant's first-pull date, keyed on
employer_domain). Every surface reads that date and applies its own display WINDOW
against the PULL DATE (never now()): landing badge 7d, per-card badge 5d. The field,
the backfill exclusion and the pull-date clock are the rule; the window is the only
thing a surface may vary.

  python tests/test_is_new_backfill.py   (repo has no pytest)
"""
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from normalize import model  # noqa: E402

D = datetime.date
PULL = D(2026, 9, 16)          # the pull date = the clock, everywhere
BADGE_WINDOW = 7
CARD_WINDOW = 5

# newtenant.com onboarded INSIDE the window (whole backlog lands 09-15); established.com
# onboarded well before it (09-01).
FIRST_PULL = {"newtenant.com": D(2026, 9, 15), "established.com": D(2026, 9, 1)}


def rec(domain, first_seen, posted_at=None):
    return {"employer_domain": domain, "first_seen": first_seen, "posted_at": posted_at}


def eff(r):
    return model.effective_new_date(r, FIRST_PULL)


def badge_new(r):
    return model.is_new_within(eff(r), PULL, BADGE_WINDOW)


def card_new(r):
    return model.is_new_within(eff(r), PULL, CARD_WINDOW)


# --- Spec test 1: onboarding backfill never counts; established-tenant genuine new does ---
def test_freshly_onboarded_backfill_is_never_new():
    # Every record from newtenant.com's first pull (first_seen == onboarding date),
    # even one the employer stamped today — backfill is not news, however recent.
    assert eff(rec("newtenant.com", "2026-09-15", "2026-09-15")) is None
    assert eff(rec("newtenant.com", "2026-09-15T08:00:00+00:00", "2026-09-16")) is None
    assert not badge_new(rec("newtenant.com", "2026-09-15", "2026-09-16"))


def test_genuinely_new_from_established_tenant_counts():
    assert badge_new(rec("established.com", "2026-09-16", "2026-09-16"))
    assert badge_new(rec("established.com", "2026-09-14", "2026-09-14"))
    # newtenant's SECOND pull (day after onboarding) brings a genuinely new posting.
    assert badge_new(rec("newtenant.com", "2026-09-16", "2026-09-16"))


# --- Spec test 2: null posted_at everywhere -> first_seen fallback carries them ---
def test_null_posted_at_uses_first_seen_fallback():
    assert eff(rec("established.com", "2026-09-16", None)) == D(2026, 9, 16)
    assert badge_new(rec("established.com", "2026-09-16", None))          # recent -> new
    assert not badge_new(rec("established.com", "2026-09-01", None))      # 15d old -> not new


def test_coalesce_prefers_posted_at():
    # Ingested today but posted three weeks ago -> effective date is the OLD posted_at.
    assert eff(rec("established.com", "2026-09-16", "2026-08-26")) == D(2026, 8, 26)
    assert not badge_new(rec("established.com", "2026-09-16", "2026-08-26"))


# --- Spec test 3: badge and card are consistent — card-new (5d) is a SUBSET of badge-new (7d),
#     and nothing badged "New" fails the unified rule (backfill is never badged) ---
def test_badge_and_card_consistency():
    feed = [
        rec("established.com", "2026-09-16", "2026-09-16"),  # 0d  -> both
        rec("established.com", "2026-09-12", "2026-09-12"),  # 4d  -> both
        rec("established.com", "2026-09-10", "2026-09-10"),  # 6d  -> badge only
        rec("established.com", "2026-09-01", "2026-09-01"),  # 15d -> neither
        rec("newtenant.com", "2026-09-15", "2026-09-16"),    # backfill -> neither
    ]
    for r in feed:
        if card_new(r):
            assert badge_new(r), "a card-New record must also satisfy the badge window"
        if badge_new(r) or card_new(r):
            assert eff(r) is not None, "nothing may be 'New' with a None effective date (backfill)"
    assert sum(badge_new(r) for r in feed) == 3
    assert sum(card_new(r) for r in feed) == 2


# --- Spec test 4: clock is the pull date, not wall-clock — result depends only on (eff, pull, window) ---
def test_pull_date_is_the_clock():
    r = rec("established.com", "2026-09-14", "2026-09-14")
    # Same feed evaluated "at two different wall-clock times" = two calls with the SAME
    # pull date -> identical (the function never reads now()).
    assert model.is_new_within(eff(r), PULL, BADGE_WINDOW) == model.is_new_within(eff(r), PULL, BADGE_WINDOW)
    # A different pull date shifts the verdict — proving pull_date IS the clock.
    assert model.is_new_within(eff(r), D(2026, 9, 16), BADGE_WINDOW)       # 2d -> new
    assert not model.is_new_within(eff(r), D(2026, 9, 30), BADGE_WINDOW)   # 16d -> not new


# --- Spec test 5: re-onboarding a dropped tenant is backfill too (its first-pull date is updated) ---
def test_re_onboarding_is_backfill():
    # A tenant dropped and re-added on 09-16: its first-pull entry reflects the re-onboard,
    # so the returning backlog (first_seen 09-16) is excluded, not a wave of "new".
    re_fp = {"returned.com": D(2026, 9, 16)}
    r = {"employer_domain": "returned.com", "first_seen": "2026-09-16", "posted_at": "2026-09-16"}
    assert model.effective_new_date(r, re_fp) is None
    assert not model.is_new_within(model.effective_new_date(r, re_fp), PULL, BADGE_WINDOW)


# --- Spec test 6: determinism ---
def test_determinism():
    r = rec("established.com", "2026-09-14", "2026-09-13")
    assert eff(r) == eff(r)
    assert badge_new(r) == badge_new(r)


# --- boundaries and missing data ---
def test_window_boundary():
    assert badge_new(rec("established.com", "2026-09-09", "2026-09-09"))      # exactly 7d
    assert not badge_new(rec("established.com", "2026-09-08", "2026-09-08"))  # 8d
    assert card_new(rec("established.com", "2026-09-11", "2026-09-11"))       # exactly 5d
    assert not card_new(rec("established.com", "2026-09-10", "2026-09-10"))   # 6d


def test_no_first_seen_is_never_new():
    assert eff(rec("established.com", None, "2026-09-16")) is None
    assert eff(rec("established.com", "", None)) is None


def test_domain_absent_from_map_gets_window_only():
    assert badge_new(rec("unlisted.com", "2026-09-16", "2026-09-16"))
    assert not badge_new(rec("unlisted.com", "2026-08-01", "2026-08-01"))


def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
