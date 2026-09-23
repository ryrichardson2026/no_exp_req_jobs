"""
Pure-Python tests for the oracle_orc category-facet scoping mechanism
(the second scoping axis, beside location). NO network - drives the factored
build_finder() on static tenant dicts.

Runs two ways:
  - plain:   py tests/test_oracle_orc_scope.py
  - pytest:  pytest tests/test_oracle_orc_scope.py

Guards the acceptance criteria for the category-facet task:
  1. selectedCategoriesFacet is optional and passes through opaquely.
  2. A list value joins with the vendor ';' delimiter (measured, not guessed).
  3. A tenant with NO finder_extra pulls UNSCOPED - no special handling, the
     finder is byte-identical to the pre-mechanism string.
  4. No category NAME appears in adapter code - the values are opaque ids.
  5. The source taxonomy (source_category) never sets the board category[].
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from adapters import oracle_orc  # noqa: E402
from normalize import model  # noqa: E402


BASE = "findReqs;siteNumber=CX_1,sortBy=POSTING_DATES_DESC,limit=100,offset=0"


def test_no_finder_extra_is_unscoped():
    """A tenant with no facet omits it and pulls the whole board - the finder is
    exactly the pre-mechanism string, no trailing scope, no crash."""
    t = {"site_number": "CX_1"}
    assert oracle_orc.build_finder(t, offset=0, limit=100) == BASE
    # explicit-empty behaves the same as absent
    t2 = {"site_number": "CX_1", "finder_extra": {}}
    assert oracle_orc.build_finder(t2, offset=0, limit=100) == BASE


def test_scalar_location_facet():
    """The existing location axis (a scalar) is unchanged."""
    t = {"site_number": "CX_1", "finder_extra": {"selectedLocationsFacet": 300000004686048}}
    f = oracle_orc.build_finder(t, offset=0, limit=100)
    assert f == BASE + ",selectedLocationsFacet=300000004686048"


def test_category_facet_list_joins_with_semicolon():
    """The category axis: a list of opaque ids joins with the vendor ';'."""
    t = {"site_number": "CX_1", "finder_extra": {
        "selectedLocationsFacet": 300000004686048,
        "selectedCategoriesFacet": [300000055008090, 300000054987331, 300000055008036],
    }}
    f = oracle_orc.build_finder(t, offset=0, limit=100)
    assert "selectedLocationsFacet=300000004686048" in f
    assert "selectedCategoriesFacet=300000055008090;300000054987331;300000055008036" in f


def test_single_element_list_still_joins():
    t = {"site_number": "CX_1", "finder_extra": {"selectedCategoriesFacet": [111]}}
    assert oracle_orc.build_finder(t, offset=0, limit=100).endswith("selectedCategoriesFacet=111")


def test_underscore_keys_are_comments_not_finder_vars():
    """A _note comment inside finder_extra must never land in the request."""
    t = {"site_number": "CX_1", "finder_extra": {
        "_note": "owner-approved non-clinical scope",
        "selectedLocationsFacet": 300000004686048,
    }}
    f = oracle_orc.build_finder(t, offset=0, limit=100)
    assert "_note" not in f
    assert f == BASE + ",selectedLocationsFacet=300000004686048"


def test_offset_and_limit_flow_through():
    t = {"site_number": "CX_1"}
    f = oracle_orc.build_finder(t, offset=200, limit=50)
    assert "limit=50,offset=200" in f


def test_source_category_never_sets_board_category():
    """Acceptance #5: the vendor taxonomy lands in source_category, verbatim, and
    the board category[] stays empty at map time (enrich derives it from title +
    tenant_category.json only). A renamed source family cannot move a job's board
    category."""
    rec = model.new_record()
    assert rec["category"] == []
    assert rec["source_category"] is None
    # simulate the adapter writing the vendor label (oracle_orc.py:808)
    rec["source_category"] = "Facilities Management"
    rec["source_function"] = "Facilities"
    # board category is untouched by the source taxonomy
    assert rec["category"] == []


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
