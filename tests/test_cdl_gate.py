"""
Guards the CDL exclusion (analyze/report.py). A commercial driver's license is an
occupational license, not entry level, so it must be excluded — two ways:
  gate 1  a CDL-titled role is excluded on the title ("title IS the credential").
  gate 3  a "Commercial Driver License" clause must NOT be allowlisted by the
          driver's-license quick-list entry (the string contains "Driver License").
A regular (non-commercial) driver's license stays quick-obtainable and passes.

  python tests/test_cdl_gate.py   (repo has no pytest)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analyze import report  # noqa: E402


# ---- gate 1: title ----------------------------------------------------------
CDL_TITLES = [
    "CDL A Local Delivery Truck Driver",
    "CDL B Local Delivery Truck Driver - Up to $1500 Sign-On Bonus",
    "Delivery Driver - CDL/Hazmat",
    "CDL Production Shuttle Driver (4-Day Workweek)",
]
NON_CDL_DRIVER_TITLES = ["Delivery Driver", "Delivery Driver Associate", "Route Service Representative"]


def test_cdl_titles_excluded_at_gate1():
    for t in CDL_TITLES:
        passed, reason = report.gate_exclusion({"title": t, "education_flag": ""})
        assert reason == "occupation-licensed", f"{t!r} must be title-excluded (got {reason})"


def test_regular_driver_titles_not_excluded():
    for t in NON_CDL_DRIVER_TITLES:
        passed, reason = report.gate_exclusion({"title": t, "education_flag": ""})
        assert passed, f"{t!r} is a regular driver, should not be title-excluded (got {reason})"


# ---- gate 3: credential allowlist override ---------------------------------
def test_cdl_credential_clause_fails_even_though_it_says_driver_license():
    r = {"_cred_to_apply": [
        "License to drive - valid Class A Commercial Driver License (CDL) with a clean record"]}
    passed, reason = report.gate_credential(r)
    assert reason == "credential", f"a CDL clause must fail the credential gate (got {reason})"


def test_plain_drivers_license_still_passes():
    r = {"_cred_to_apply": ["Must have a valid driver's license"]}
    passed, reason = report.gate_credential(r)
    assert passed, f"a plain driver's license is quick-obtainable, should pass (got {reason})"


def test_cdl_rx_matches_cdl_and_commercial_not_plain():
    assert report.CDL_RX.search("CDL A Truck Driver")
    assert report.CDL_RX.search("Commercial Driver License")
    assert not report.CDL_RX.search("valid driver's license")


def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
