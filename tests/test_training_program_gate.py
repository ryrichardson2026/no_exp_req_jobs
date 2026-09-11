"""
Guards the management-gate carve-out for entry PROGRAMS (report.py).

"Management Trainee" is already applicable (head-noun protect), but a
"Management & Sales Training Program" has head noun 'Program' / a '(City)' tail,
so the head-noun protect misses it. TRAINING_PROGRAM_RX defers such titles from
title-exclusion to the REQUIREMENTS gate - it must rescue genuine training
programs WITHOUT leaking real Manager/Director roles or internships.

  python tests/test_training_program_gate.py   (repo has no pytest)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analyze import report  # noqa: E402


def _rec(title, exp="PREFERRED"):
    # Minimal record: no degree flag so gate_exclusion reaches the title logic.
    return {"title": title, "education_flag": "", "experience_condition": exp}


def gate(title):
    """(passed, reason) from the exclusion gate for a bare title."""
    return report.gate_exclusion(_rec(title))


# --- rescued: management-titled PROGRAMS defer to the requirements gate ---
RESCUED = [
    "2027 Management & Sales Training Program (Seattle)",
    "2027 Management & Sales Training Program (Spokane)",
    "2027 Management & Sales Training Program (Tri-Cities)",
    "Leadership Development Program",
]

# --- still excluded on the management title (must NOT leak) ---
STILL_MGMT = [
    "Store Manager",
    "Sales Manager - Territory 5",
    "General Manager",
    "Manager, Training & Development",   # a real training-manager JOB, not a program
    "District Director",
]


def test_training_programs_are_not_management_excluded():
    for t in RESCUED:
        passed, reason = gate(t)
        assert reason != "occupation-management", f"{t!r} should NOT be mgmt-excluded (got {reason})"


def test_training_programs_reach_applicable_when_no_experience():
    # Deferred to requirements: PREFERRED experience -> clears the exclusion gate.
    for t in RESCUED:
        passed, reason = gate(t)
        assert passed, f"{t!r} should clear the exclusion gate, got reason={reason}"


def test_real_management_titles_still_excluded():
    for t in STILL_MGMT:
        passed, reason = gate(t)
        assert reason == "occupation-management", f"{t!r} must stay mgmt-excluded (got {reason})"


def test_internships_not_rescued_by_the_program_carveout():
    # An internship is excluded independently; the training-program phrase must not
    # match it (it is not a '... training program').
    assert not report.TRAINING_PROGRAM_RX.search(
        "Management and Sales Summer Internship 2027 (Seattle)")


def test_carveout_does_not_touch_frontline_titles():
    # Non-management titles are unaffected either way.
    passed, reason = gate("Warehouse Team Member")
    assert passed and reason is None


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
