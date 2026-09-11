"""
Tests for the Sysco (Path B) tenant on adapters/radancy_tb.py.

Sysco is built by ADDITIVE config-driven parameterisation of the LIVE radancy_tb
adapter (one code path, Allied byte-identical). These assertions drive the
adapter's parsing/mapping against the REAL captured detail page and the SHIPPED
config block - no network, no disk beyond the fixture.

  python -m pytest tests/test_sysco.py
  python tests/test_sysco.py     # repo has no pytest installed
"""

import datetime
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

from adapters import radancy_tb as rt  # noqa: E402
from normalize import model  # noqa: E402
from normalize import experience as X  # noqa: E402

FIXTURE = "sysco_warehousejob.txt"

# wd5 Workday apply URL as it appears in the <meta search-job-apply-url> tag.
APPLY_URL = ("https://wd5.myworkdaysite.com/recruiting/sysco/syscocareers/job/"
             "Sysco-Seattle---Kent/Warehouse-Order-Selector_R264570/apply")


def _load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _tenant():
    """The SHIPPED config block. Loading it (not a hand-rolled copy) makes these
    tests also assert the config wiring - source_job_id_from, body_fields,
    page_url_sep are all read from config, not the test."""
    return rt.load_tenant("sysco")


def _record():
    html = _load(FIXTURE)
    ld = rt.extract_jobposting(html)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec, warnings = rt.map_record(ld, _tenant(), "2026-09-11T00:00:00", html)
    return rec, ld, html


# ---------------------------------------------------------------------------
# JSON-LD core + config-driven source_job_id
# ---------------------------------------------------------------------------

def test_title():
    rec, _, _ = _record()
    assert rec["title"] == "Warehouse Order Selector", rec["title"]


def test_source_job_id_is_url_tail_not_identifier():
    rec, ld, _ = _record()
    # source_job_id_from='url_tail' -> the TalentBrew job id (url tail),
    # NOT ld['identifier'] (the Workday req id).
    assert rec["source_job_id"] == "99722303904", rec["source_job_id"]
    assert rec["source_job_id"] != "R264570"


def test_req_id_extractable_but_off_contract():
    rec, ld, _ = _record()
    # The Workday req id is extractable from the JSON-LD identifier ...
    assert ld.get("identifier") == "R264570"
    # ... but has NO contract slot, so it is NOT smuggled into the record
    # (the Cintas precedent). It survives only in raw.
    assert "R264570" not in (rec.get("source_job_id") or "")
    assert "req_id" not in rec and "identifier" not in rec


def test_posted_at_parses_to_2026_08_25():
    rec, _, _ = _record()
    d = datetime.datetime.strptime(rec["posted_at"], "%Y-%m-%d").date()
    assert d == datetime.date(2026, 8, 25), rec["posted_at"]


def test_company_name():
    rec, _, _ = _record()
    assert rec["company_name"] == "US0055 Sysco Seattle, Inc.", rec["company_name"]


def test_city_and_state():
    rec, _, _ = _record()
    assert rec["city"] == "Kent", rec["city"]
    assert rec["state"] == "WA", rec["state"]


# ---------------------------------------------------------------------------
# body_fields parse (server-rendered labeled fields, not in the JSON-LD)
# ---------------------------------------------------------------------------

def test_employment_type_from_body_field():
    rec, _, _ = _record()
    assert rec["employment_type"] == "Full time", rec["employment_type"]


def test_compensation_parses_to_hourly_range():
    rec, _, _ = _record()
    assert rec["salary_min"] == 31.53, rec["salary_min"]
    assert rec["salary_max"] == 35.47, rec["salary_max"]
    assert rec["salary_is_stated"] is True
    assert rec["pay_period"] == "HOURLY", rec["pay_period"]


def test_apply_url_is_the_wd5_workday_url():
    rec, _, _ = _record()
    assert rec["apply_url"] == APPLY_URL, rec["apply_url"]
    assert "wd5.myworkdaysite.com" in rec["apply_url"]
    assert rec["apply_url"].endswith("/apply")
    # source_url stays the careers.sysco.com job page, distinct from apply_url
    assert rec["source_url"].startswith("https://careers.sysco.com/")


# ---------------------------------------------------------------------------
# description: the JSON-LD body, with the Min/Preferred split and NO boilerplate
# ---------------------------------------------------------------------------

def test_description_carries_the_min_preferred_split():
    rec, _, _ = _record()
    body = rec["description_html"]
    assert "JOB SUMMARY" in body
    assert "Minimum Requirements" in body
    assert "Preferred Requirements" in body


def test_description_drops_the_visible_body_boilerplate():
    rec, _, _ = _record()
    body = rec["description_html"]
    # These labels live only in the visible HTML job-info fields, never in the
    # JSON-LD description that feeds the extractor.
    for boiler in ("Compensation Range", "Job Profile Summary",
                   "AFFIRMATIVE ACTION STATEMENT"):
        assert boiler not in body, boiler


def test_record_is_a_valid_contract_record():
    rec, _, _ = _record()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec["first_seen"] = rec["last_seen"] = now  # set by mode_normalize at runtime
    problems = model.validate(rec)
    assert problems == [], problems


# ---------------------------------------------------------------------------
# link collector: locale-prefixed /en/job/ hrefs match; search-jobs / content reject
# ---------------------------------------------------------------------------

_LISTING_HTML = """
<a href="/en/job/kent/warehouse-order-selector/1105/99722303904">Warehouse Order Selector</a>
<a href="/en/job/auburn/warehouse-associate-day-shift-wa/1105/98910846608">Warehouse Associate</a>
<a href="/en/job/olympia/sales-consultant-olympia/1105/99821988400">Sales Consultant</a>
<a href="/en/job/everett/cdl-b-local-delivery-truck-driver-up-to-1500-sign-on-bonus/1105/97762984592">CDL B Driver</a>
<a href="/en/search-jobs/Washington%2C%20US/1105/3/6252001-5815135/47x50012/-120x50147/50">Search WA jobs</a>
<a href="/en/job_location/kent/warehouse-order-selector/1105/99722303904/955649">Explore the Area</a>
<a href="/benefits">Benefits</a>
"""

_EXPECTED_HREFS = [
    "/en/job/kent/warehouse-order-selector/1105/99722303904",
    "/en/job/auburn/warehouse-associate-day-shift-wa/1105/98910846608",
    "/en/job/olympia/sales-consultant-olympia/1105/99821988400",
    "/en/job/everett/cdl-b-local-delivery-truck-driver-up-to-1500-sign-on-bonus/1105/97762984592",
]


def test_link_collector_pulls_four_and_rejects_search_and_content():
    rows = rt.extract_rows(_LISTING_HTML)
    hrefs = [r["href"] for r in rows]
    assert hrefs == _EXPECTED_HREFS, hrefs
    # search-jobs and content links (job_location, /benefits) never appear
    assert not any("/search-jobs/" in h for h in hrefs)
    assert not any("job_location" in h for h in hrefs)
    assert not any(h == "/benefits" for h in hrefs)
    # the org/id groups are still captured off the locale-prefixed href
    kent = rows[0]
    assert kent["org_id"] == "1105" and kent["internal_id"] == "99722303904"


def test_allied_style_href_still_matches_identically():
    # Byte-identity guard for change 1: a bare /job/city/title/12345/67890 href
    # (Allied's shape, no locale prefix) must still match with unchanged groups.
    m = rt._JOB_HREF.search('href="/job/seattle/security-officer/12345/67890"')
    assert m is not None
    assert m.group(1) == "/job/seattle/security-officer/12345/67890"
    assert m.group(2) == "12345"
    assert m.group(3) == "67890"


def test_enrich_section_and_zero_inclusive_open():
    """With the SHIPPED Sysco openers (BARE, colon-less) + the opted-in zero-inclusive
    lever, the fixture's Minimum Requirements section is found and the '0 - 1 Year'
    experience does NOT bar - the record resolves to an applicable condition."""
    ld = rt.extract_jobposting(_load(FIXTURE))
    op = X.load_openers("sysco")
    assert op.get("zero_range_open") is True, "sysco must opt into the zero-inclusive lever"
    r = X.extract(ld["description"], openers=op)
    assert r["section_found"], "bare openers must find the colon-less Minimum Requirements heading"
    assert r["experience_condition"] in ("PREFERRED", "NONE_NEEDED", "WAIVED"), \
        f"zero-inclusive minimum must read as applicable, got {r['experience_condition']}"


def test_zero_inclusive_lever_is_config_scoped():
    """Blast-radius guard: the lever is OFF by default, so a 0-month experience clause
    still bars unless the tenant opted in. It can never silently change another build."""
    reqs = [{"clause": "0 - 1 Year relevant work experience", "types": ["experience"],
             "modality": X.TO_APPLY, "months": 0.0, "trade_ticket": False}]
    assert X.derive_condition(reqs, True)[0] == "REQUIRED", \
        "default (flag off) must still bar a 0-month clause"
    assert X.derive_condition(reqs, True, zero_range_open=True)[0] == "NONE_NEEDED", \
        "opted-in must open the zero-inclusive range"


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
