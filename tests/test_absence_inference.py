"""Guard for the absence-inference NONE_NEEDED in normalize/experience.derive_condition.

When a requirements section IS present but no line classifies as a barrier (a soft-skills-only
section), the employer stated requirements and none bars a no-experience applicant -> NONE_NEEDED,
NOT NOT_STATED. GUARDED: only when the section names no experience/education/credential language
at all (else a parser miss could hide a real requirement -> stays NOT_STATED). AGE is stripped
first and is never a factor (age-never-a-screener).
"""
import normalize.experience as X

OPENERS = X.compile_openers([{"text": "qualifications", "role": "REQUIRED", "match": "bare"}])


def cond(html):
    return X.extract(html, "", "", OPENERS)["experience_condition"]


def test_soft_skills_only_section_is_none_needed():
    h = ("<b>Qualifications</b><ul><li>Ability to learn quickly in a fast-paced environment</li>"
         "<li>Adaptability to various roles</li><li>Flexible schedule availability</li></ul>")
    assert cond(h) == X.NONE_NEEDED


def test_age_only_plus_soft_skills_is_none_needed():
    # "16 years or older" is AGE - stripped before the barrier test, never a factor either way.
    h = "<b>Qualifications</b><ul><li>Ability to learn quickly</li><li>16 years or older</li></ul>"
    assert cond(h) == X.NONE_NEEDED


def test_real_experience_clause_still_required():
    h = "<b>Qualifications</b><ul><li>Minimum 2 years of experience in food service required</li></ul>"
    assert cond(h) == X.REQUIRED


def test_no_requirements_section_is_not_stated():
    h = "<p>Join our team! It's a great place to work and grow.</p>"
    assert cond(h) == X.NOT_STATED


# --- the guard itself (the parser-miss safety net) --------------------------
# _clean_section_no_barrier drives the absence-inference: it may only infer NONE_NEEDED when the
# section names NO experience/education/credential language. Barrier phrasings that classify_line
# catches never reach this path; this guards the ones it might MISS.

def test_guard_soft_skills_no_barrier():
    assert X._clean_section_no_barrier("Ability to learn quickly and flexible schedule") is True


def test_guard_age_only_is_not_a_barrier():
    # age is stripped first - never a factor (age-never-a-screener)
    assert X._clean_section_no_barrier("Ability to learn; 16 years or older; must be at least 18") is True


def test_guard_experience_language_blocks_inference():
    assert X._clean_section_no_barrier("2 years of experience preferred") is False


def test_guard_degree_language_blocks_inference():
    assert X._clean_section_no_barrier("Bachelor degree in a relevant field") is False


def test_guard_credential_language_blocks_inference():
    assert X._clean_section_no_barrier("Must hold a valid RN license and certification") is False


def test_guard_empty_section_is_not_clean():
    assert X._clean_section_no_barrier("") is False
