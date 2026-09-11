"""
Tests for adapters/successfactors_rmk.py (Cintas).

Pure-Python, NO network: every assertion drives a parsing function on a static
HTML fixture. Runs either under pytest OR as a plain script:

  python -m pytest tests/test_successfactors_rmk.py
  python tests/test_successfactors_rmk.py     # repo has no pytest installed
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

from adapters import successfactors_rmk as sf  # noqa: E402
from normalize import model  # noqa: E402

HOST = "https://careers.cintas.com"

# Self-contained tenant, mirroring the config block that goes into tenants.json.
# The test does not depend on tenants.json (the cintas entry may not be inserted
# yet), only on the adapter's parsing/mapping contract.
TENANT = {
    "key": "cintas",
    "label": "Cintas",
    "host": HOST,
    "endpoints": {
        "search": f"{HOST}/search/",
        "job_base": f"{HOST}/job/",
        "apply_pattern": f"{HOST}/talentcommunity/apply/{{posting_id}}/?locale=en_US",
    },
    "page_size": 25,
    "search_params": {
        "q": "",
        "locationsearch": "WA",
        "searchby": "location",
        "d": "50",
        "sortColumn": "referencedate",
        "sortDirection": "desc",
    },
    "employer_name": "Cintas",
    "company_name": "Cintas",
    "employer_domain": "cintas.com",
    "market": None,
    "state": "WA",
    "geo_scope": {
        "verified": "2026-09-11",
        "method": "search params locationsearch=WA&searchby=location (state match)",
        "national": "full board",
        "in_market": 60,
    },
    "source_class": "direct-employer",
    "apply_class": "employer-direct",
    "terms_reference": None,
    "labeled_fields": {
        "requisition_number": "Requisition Number",
        "job_category": "Job Category",
        "organization": "Organization",
        "employee_status": "Employee Status",
        "schedule": "Schedule",
        "shift": "Shift",
        "nearest_major_market": "Nearest Major Market",
        "nearest_secondary_market": "Nearest Secondary Market",
        "job_segment": "Job Segment",
    },
    "section_headings": {
        "job_description": "Job Description",
        "skills_qualifications": "Skills/Qualifications",
        "compensation": "Compensation",
        "benefits": "Benefits",
    },
}


def _load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as fh:
        return fh.read()


def test_find_links_returns_postings_and_excludes_go():
    raw = _load("cintas_search.html")
    links = sf.find_links(raw, HOST)
    ids = [l["posting_id"] for l in links]
    assert ids == ["1421663700", "1421663800"], ids
    # /go/ category feeds must never appear
    assert all("/go/" not in l["url"] for l in links)
    assert links[0]["url"] == f"{HOST}/job/Cincinnati-Warehouse-Associate-OH-45262/1421663700/"


def test_parse_labels_catches_shift_schedule_reqnum():
    raw = _load("cintas_job.html")
    text = sf.visible_text(raw)
    labels = sf.parse_labels(text, TENANT["labeled_fields"])
    assert labels.get("shift") == "2nd Shift", labels.get("shift")
    assert labels.get("schedule") == "Full Time", labels.get("schedule")
    assert labels.get("requisition_number") == "233578", labels.get("requisition_number")
    assert labels.get("job_category") == "Production", labels.get("job_category")


def test_parse_section_catches_skills_qualifications():
    raw = _load("cintas_job.html")
    text = sf.visible_text(raw)
    heads = list(TENANT["section_headings"].values())
    body = sf.parse_section(text, "Skills/Qualifications",
                            [h for h in heads if h != "Skills/Qualifications"])
    assert body, "Skills/Qualifications section not caught"
    assert "lift up to 50 lbs" in body
    # section must STOP at the next heading (Compensation), not run into it
    assert "Competitive hourly wage" not in body


def test_parse_jsonld_present():
    raw = _load("cintas_job.html")
    ld = sf.parse_jsonld(raw)
    assert ld is not None and ld.get("@type") == "JobPosting"


def _build_raw():
    """Simulate what --pull writes: parse_job output + the link-carried fields."""
    page = _load("cintas_job.html")
    rec = sf.parse_job(TENANT, page)
    posting_id = "1421663700"
    rec.update({
        "tenant_key": "cintas",
        "platform": sf.PLATFORM,
        "posting_id": posting_id,
        "slug": "Cincinnati-Warehouse-Associate-OH-45262",
        "source_url": f"{HOST}/job/Cincinnati-Warehouse-Associate-OH-45262/{posting_id}/",
        "apply_url": TENANT["endpoints"]["apply_pattern"].format(posting_id=posting_id),
        "retrieved_at": "2026-09-11T00:00:00Z",
    })
    return rec


def test_normalize_produces_valid_contract_record():
    raw = _build_raw()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec, warnings = sf.map_record(raw, TENANT, now)

    problems = model.validate(rec)
    assert problems == [], problems

    # source_job_id keys on the POSTING id, not the requisition number
    assert rec["source_job_id"] == "1421663700"
    assert rec["source_job_id"] != "233578"

    # STRUCTURED shift comes from the label, verbatim
    assert rec["shift_raw"] == "2nd Shift"
    assert rec["employment_type"] == "Full Time"

    # contract wiring
    assert rec["source_id"] == "successfactors_rmk"
    assert rec["company_name"] == "Cintas"
    assert rec["source_category"] == "Production"
    assert rec["city"] == "Cincinnati"
    assert rec["state"] == "OH"
    assert rec["apply_url"] == f"{HOST}/talentcommunity/apply/1421663700/?locale=en_US"
    assert rec["description_text"] and "lift up to 50 lbs" in rec["description_text"]
    # the requisition number is NOT smuggled in as an unknown field
    assert "requisition_number" not in rec


def test_find_links_tolerates_percent_encoded_slug():
    raw = _load("cintas_search_wa.html")
    links = sf.find_links(raw, HOST)
    ids = [l["posting_id"] for l in links]
    # all three /job/ rows found (percent-encoded row included); /go/ excluded
    assert ids == ["1421664000", "1421664100", "1421664200"], ids
    assert all("/go/" not in l["url"] for l in links)
    pct = links[0]
    assert "%284-Day-Workweek%29" in pct["url"]
    # and its state still resolves through the percent-encoding
    assert sf.state_from_slug(pct["slug"]) == "WA"


def test_client_side_wa_filter_drops_out_of_state():
    raw = _load("cintas_search_wa.html")
    links = sf.find_links(raw, HOST)
    kept, dropped = sf.filter_in_market(links, "WA")
    kept_ids = [l["posting_id"] for l in kept]
    assert dropped == 1, dropped
    assert "1421664200" not in kept_ids   # Portland, OR dropped
    assert kept_ids == ["1421664000", "1421664100"], kept_ids


def test_geo_scope_guard_refuses_without_scope():
    # The guard logic that --pull calls BEFORE any fetch. Verified scope passes;
    # missing/unverified fails. No network, no disk.
    assert sf.geo_scope_ok(TENANT) is True                              # verified: 2026-09-11
    assert sf.geo_scope_ok({}) is False                                 # no geo_scope at all
    assert sf.geo_scope_ok({"geo_scope": {}}) is False                  # empty block
    assert sf.geo_scope_ok({"geo_scope": {"national": "full board"}}) is False  # unverified
    assert sf.geo_scope_ok({"geo_scope": {"exempt": True}}) is True     # explicitly exempt


def _run_all():
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
    sys.exit(_run_all())
