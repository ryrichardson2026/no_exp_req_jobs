"""
Guards the pay-disclaimer fix in normalize/experience.py (COMP_DISCLAIMER_RX +
EXP_REQ_SIGNAL in classify_line).

The fix stops pay-transparency boilerplate ("compensation may vary based on ...
experience") from being read as an experience REQUIREMENT - it names 'experience'
but states no barrier, and untreated it falsely marks the whole posting REQUIRED
(the requirements-span leak class), suppressing real applicable jobs.

The DANGER the fix must not create: a real requirement and the disclaimer sharing
ONE clause ("2 yrs experience required and pay commensurate with experience"). If
the guard stripped that clause, a genuinely experience-required posting could read
applicable - a FALSE POSITIVE, the worst failure mode, and invisible (looks like a
pass). So the guard strips ONLY a pure pay statement (no stated duration, no
requirement signal); anything ambiguous fails SAFE and stays REQUIRED.

  python tests/test_pay_disclaimer_guard.py   (repo has no pytest)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from normalize import experience as E  # noqa: E402

_OPENERS = E.compile_openers([{"text": "qualifications", "role": "REQUIRED", "match": "bare"}])
_Q = "<p><b>Qualifications</b></p>"


def _cond(inner_html):
    html = _Q + "<ul>" + inner_html + "</ul>"
    return E.extract(html, text_fallback="", qualifications_html="", openers=_OPENERS)["experience_condition"]


# --- the recovery the fix exists for: a PURE disclaimer must not bar the posting ---

def test_pure_disclaimer_does_not_bar():
    # A physical line (applicable) + a pay disclaimer that merely names experience.
    cond = _cond("<li>Ability to lift 50 lbs.</li>"
                 "<li>Compensation may vary based on qualifications, education, and experience.</li>")
    assert cond in (E.NONE_NEEDED, E.WAIVED, E.PREFERRED), \
        f"a pure pay disclaimer must not mark REQUIRED, got {cond}"


# --- the danger the fix must not create: a real requirement sharing the disclaimer's span ---

def test_requirement_and_disclaimer_same_block_stays_required():
    # The reviewer's fixture: both sentences in one requirements block.
    cond = _cond("<li>Minimum 2 years experience required. "
                 "Compensation commensurate with experience.</li>")
    assert cond == E.REQUIRED, f"a stated requirement must survive a co-located disclaimer, got {cond}"


def test_requirement_and_disclaimer_one_sentence_stays_required():
    # Comma-joined into ONE clause (no sentence split to save it) - the hard case.
    for inner in (
        "<li>2 years experience required, and compensation is commensurate with experience.</li>",
        "<li>Prior experience required and salary commensurate with experience.</li>",
        "<li>Compensation varies with experience and a minimum of 3 years experience is required.</li>",
    ):
        assert _cond(inner) == E.REQUIRED, f"fail-safe expected REQUIRED for: {inner}"


def test_false_positive_worst_case_stays_required():
    # Requirement+disclaimer share a clause AND a benign physical line sits elsewhere -
    # the exact shape that would flip a required posting to applicable if the guard were blunt.
    cond = _cond("<li>Prior warehouse experience required and pay is commensurate with experience.</li>"
                 "<li>Ability to lift 50 lbs.</li>")
    assert cond == E.REQUIRED, f"must NOT read applicable when experience is genuinely required, got {cond}"


# --- clause-level unit checks on classify_line directly ---

def test_classify_line_strips_pure_disclaimer_only():
    pure = E.classify_line(
        "compensation may vary based on qualifications, education, and experience", E.TO_APPLY)
    assert pure is None or E.EXPERIENCE not in pure["types"], \
        "pure disclaimer clause must not carry an experience type"

    real = E.classify_line(
        "minimum 2 years experience required, pay commensurate with experience", E.TO_APPLY)
    assert real is not None and E.EXPERIENCE in real["types"], \
        "a clause with a real requirement keeps its experience type even alongside pay wording"


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
