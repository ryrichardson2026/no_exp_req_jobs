"""
Pure-Python tests for adapters/adp_wfn.py. NO network - every test drives the
adapter's factored parsing functions on static fixture dicts.

Runs two ways:
  - plain:   py tests/test_adp_wfn.py     (prints PASS/FAIL, exits non-zero on failure)
  - pytest:  pytest tests/test_adp_wfn.py  (functions are discovered as test_*)

The repo has no pytest config and no prior tests, so the plain-assert + __main__
runner is the primary path; pytest discovery is a bonus.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

from adapters import adp_wfn  # noqa: E402
from normalize import model  # noqa: E402


# A stand-in tenant config carrying exactly the keys the adapter reads. Kept in
# the test (not read from tenants.json) so the test is independent of the config
# insertion - it mirrors the returned `gensco` block.
TENANT = {
    "key": "gensco",
    "label": "Gensco (ADP WFN)",
    "employer_name": "Gensco",
    "employer_domain": "gensco.com",
    "market": None,
    "state": "WA",
    "source_class": "direct-employer",
    "apply_class": "employer-direct",
    "terms_reference": None,
    "geo_scope": {
        "exempt": True,
        "reason": "small PNW-centric board",
        "still_client_filter": True,
    },
    "endpoints": {
        "list": "https://my.adp.com/x/mycareer/public/staffing/v1/job-requisitions/search-custom-filters",
        "listing_page": "https://myjobs.adp.com/genscocareers/cx/job-listing",
    },
    "list_request": {
        "params": {
            "$select": "reqId,jobTitle,publishedJobTitle,type,jobDescription,jobQualifications,workLocations,workLevelCode,clientRequisitionID,postingDate,requisitionLocations",
            "$top": 10,
            "$filter": "",
            "tz": "America/Los_Angeles",
        },
        "page_size": 10,
        "pagination": {"cursor_param": "$skip"},
    },
    "field_map": {
        "source_job_id": "reqId",
        "title": "publishedJobTitle",
        "internal_title": "jobTitle",
        "client_req_id": "clientRequisitionID",
        "description_html": "jobDescription",
        "qualifications_html": "jobQualifications",
        "employment_type": "type",
        "work_level": "workLevelCode",
        "posted_text": "postingDate",
    },
    "headers": {
        "Referer": "https://myjobs.adp.com/genscocareers/cx/job-listing",
        "note": "headers not yet captured - Referer is a scoping guess only.",
    },
}


def _load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- unwrap
def test_unwrap_known_key():
    payload = _load("adp_wfn_page_jobRequisitions.json")
    rows, key = adp_wfn.unwrap(payload)
    assert key == "jobRequisitions", key
    assert len(rows) == 3, len(rows)
    assert rows[0]["reqId"] == "REQ-1001"


def test_unwrap_novel_key_fallback():
    payload = _load("adp_wfn_page_novelkey.json")
    rows, key = adp_wfn.unwrap(payload)
    # None of LIST_KEYS present -> first list-of-objects wins.
    assert key == "myCustomRequisitionRows", key
    assert len(rows) == 1, len(rows)
    assert rows[0]["reqId"] == "REQ-2001"


def test_unwrap_root_list():
    rows, key = adp_wfn.unwrap([{"reqId": "X"}])
    assert key == "<root list>"
    assert rows[0]["reqId"] == "X"


# ---------------------------------------------------------------- loc_strings
def test_loc_bare_string():
    row = {"workLocations": "Tacoma, WA", "requisitionLocations": []}
    assert adp_wfn.loc_strings(row) == ["Tacoma, WA"]


def test_loc_list_of_strings():
    row = {"workLocations": ["Kent, WA", "Fife, WA"], "requisitionLocations": ["Kent, WA"]}
    # deduped, order preserved across both keys
    assert adp_wfn.loc_strings(row) == ["Kent, WA", "Fife, WA"]


def test_loc_nested_namecode_address():
    row = _load("adp_wfn_page_jobRequisitions.json")["jobRequisitions"][2]
    got = adp_wfn.loc_strings(row)
    assert "Portland Branch" in got, got
    assert "Portland, OR, 97201" in got, got   # codeValue wrapper flattened
    assert "Portland, OR" in got, got


# ---------------------------------------------------------------- normalize
def test_normalize_yields_valid_contract_record():
    row = _load("adp_wfn_page_jobRequisitions.json")["jobRequisitions"][0]
    rec, warnings = adp_wfn.normalize_record(
        row, TENANT, retrieved_at="2026-09-11T00:00:00",
        now="2026-09-11T00:00:00", seen_state={})
    problems = model.validate(rec)
    assert problems == [], problems
    assert rec["source_id"] == "adp_wfn"
    assert rec["source_job_id"] == "REQ-1001"
    assert rec["company_name"] == "Gensco"
    assert rec["qualifications_html"], "qualifications_html must be populated from jobQualifications"
    # jobQualifications folded into description_text as well
    assert "lift 50 lbs" in rec["description_text"]
    # clean 'City, ST' parsed
    assert rec["location_raw"] == "Tacoma, WA"
    assert rec["city"] == "Tacoma"
    assert rec["state"] == "WA"
    assert rec["apply_url"] == TENANT["endpoints"]["listing_page"]
    assert rec["source_class"] == "direct-employer"


def test_normalize_novel_key_record():
    row = _load("adp_wfn_page_novelkey.json")["myCustomRequisitionRows"][0]
    rec, _ = adp_wfn.normalize_record(
        row, TENANT, retrieved_at="2026-09-11T00:00:00",
        now="2026-09-11T00:00:00", seen_state={})
    assert model.validate(rec) == []
    assert rec["source_job_id"] == "REQ-2001"
    assert rec["qualifications_html"] == "No prior warehouse experience necessary."


def test_derived_fields_left_at_defaults():
    """normalize must NOT classify: experience/category/credentials stay default."""
    row = _load("adp_wfn_page_jobRequisitions.json")["jobRequisitions"][0]
    rec, _ = adp_wfn.normalize_record(
        row, TENANT, retrieved_at="2026-09-11T00:00:00",
        now="2026-09-11T00:00:00", seen_state={})
    assert rec["experience_condition"] is None
    assert rec["category"] == []
    assert rec["credentials"] == []
    assert rec["evidence_clauses"] == []


# ---------------------------------------------------------------- geo-scope guard
def test_pull_guard_passes_when_exempt():
    assert adp_wfn.geo_scope_ok({"geo_scope": {"exempt": True}}) is True
    assert adp_wfn.geo_scope_ok(TENANT) is True   # gensco exempt


def test_pull_guard_passes_when_verified():
    assert adp_wfn.geo_scope_ok({"geo_scope": {"verified": True}}) is True


def test_pull_guard_refuses_without_geo_scope():
    # absent geo_scope, and present-but-neither-flag, both refuse
    assert adp_wfn.geo_scope_ok({}) is False
    assert adp_wfn.geo_scope_ok({"geo_scope": {"reason": "someday"}}) is False


# ---------------------------------------------------------------- client-side WA filter
def test_wa_filter_keeps_wa_row():
    wa_row = _load("adp_wfn_page_jobRequisitions.json")["jobRequisitions"][0]  # Tacoma, WA
    assert adp_wfn.row_in_state(wa_row, "WA") is True


def test_wa_filter_drops_non_wa_row():
    or_row = _load("adp_wfn_page_jobRequisitions.json")["jobRequisitions"][2]  # Portland, OR
    assert adp_wfn.row_in_state(or_row, "WA") is False


def test_location_state_resolves_and_ignores_city_false_positive():
    assert adp_wfn.location_state("Tacoma, WA") == "WA"
    assert adp_wfn.location_state("Portland, OR, 97201") == "OR"   # state mid-string
    assert adp_wfn.location_state("Tacoma Branch") is None         # no standalone code
    assert adp_wfn.location_state("Orlando, FL") == "FL"           # 'Or' does not fire


# ---------------------------------------------------------------- runner
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
