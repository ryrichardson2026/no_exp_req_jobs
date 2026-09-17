"""Guard for the credential 'acquire-frame' waiver in analyze/report.gate_credential.

A TO_APPLY credential framed "eligibility/able/ability to acquire|obtain|get X" asserts
X is obtainable (employer-sponsored, after selection), so it must NOT gate - this is what
lets an airport Ramp Agent ("eligibility to acquire FAA/TSA clearances") reach applicable.

Fail-safe direction (mirrors the pay-disclaimer guard): the waiver is VOID when the clause
names a hard long-lead credential (CDL/RN/degree) - "able to obtain a CDL" is still a barrier.
"""
from analyze.report import gate_credential


def _rec(*clauses):
    return {"_cred_to_apply": list(clauses)}


def test_acquire_clearances_passes():
    # PrimeFlight's real ramp/fuel/baggage clause - the whole point of the fix.
    ok, why = gate_credential(_rec(
        "Eligibility to acquire needed credentials and clearances (FAA, RAIC, TSA, Port Authority, U.S. Customs)"))
    assert ok, f"acquire-framed clearances should not gate, got {why}"


def test_able_to_obtain_food_safety_passes():
    ok, _ = gate_credential(_rec("Must be able to obtain food safety and MAST certification"))
    assert ok


def test_plain_valid_drivers_license_still_passes():
    # driver's license is on the quick-list already - unaffected by the waiver.
    ok, _ = gate_credential(_rec("Must have a valid state-issued driver's license"))
    assert ok


def test_failsafe_able_to_obtain_cdl_still_blocks():
    # A CDL is long-lead; the acquire framing must NOT wave it through.
    ok, why = gate_credential(_rec("Must be able to obtain a CDL within 90 days"))
    assert not ok and why == "credential"


def test_failsafe_acquire_rn_license_still_blocks():
    ok, why = gate_credential(_rec("Eligibility to acquire an active RN license"))
    assert not ok and why == "credential"


def test_held_hard_credential_unframed_still_blocks():
    # No acquire framing at all -> existing behaviour: a held non-quick credential gates.
    ok, why = gate_credential(_rec("Active ARRT certification required"))
    assert not ok and why == "credential"


def test_no_credentials_passes():
    ok, _ = gate_credential(_rec())
    assert ok
