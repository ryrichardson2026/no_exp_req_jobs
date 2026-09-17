"""
Acceptance tests for the discovery agent (discovery/*).

Maps to the build spec's acceptance list. The repo has no pytest — run directly:

    python tests/test_discovery.py

Covered here (the code-testable criteria):
  #1  all sourcing rules read from config; zero rules in code
  #2  changing one rule in config changes a disposition with no code edit
  #3  Stage 1 makes no network calls
  #5  density never rejects at Stage 2; industry label never rejects
  #8  candidate record field names match /add-tenant's inputs exactly
  #10 resumable, idempotent, re-evaluable on rule change without re-fetching
  #11 the three manually-probed airport employers reproduce (at the logic level,
      given their captured facts; the live browser reproduction is /discover's job)

Criteria #4/#6/#7/#9 are runtime browser/orchestration guarantees enforced by the
/discover command and asserted there, not unit-testable without a network.
"""
import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from discovery import rules as R          # noqa: E402
from discovery import classify as C       # noqa: E402
from discovery import evaluate as E       # noqa: E402
from discovery import store as S          # noqa: E402
from discovery import report as RP        # noqa: E402
from discovery.record import (            # noqa: E402
    Candidate, ADD_TENANT_INPUTS,
    DISPOSITION_EXCLUDED, DISPOSITION_CANDIDATE, DISPOSITION_QUALIFIED,
    DISPOSITION_NEEDS_REVIEW, DISPOSITION_RULED_OUT, PERMANENT_DISPOSITIONS,
)


def _rules():
    return R.load_rules()


# --- #1 rules come from config -------------------------------------------------

def test_rules_load_from_config_file():
    rules = _rules()
    # The exclusions the spec pins must be present in the FILE, not in code.
    names = {e.get("name") for e in rules["exclusions"]}
    classes = {e.get("class") for e in rules["exclusions"]}
    assert "Amazon" in names, "Amazon exclusion must live in config/sourcing_rules.json"
    assert {"staffing_agency", "aggregator", "grocery"} <= classes


def test_no_rule_literals_hardcoded_in_classify():
    # classify.py must not embed the exclusion vocabulary; it reads it from rules.
    src = open(os.path.join(ROOT, "discovery", "classify.py"), encoding="utf-8").read()
    for banned in ("Amazon", "staffing_agency", "survey_gig", "merchandising_firm"):
        assert banned not in src, f"{banned!r} is hardcoded in classify.py — must come from rules"


# --- #2 change a rule -> disposition changes, no code edit ---------------------

def test_rule_change_flips_disposition():
    rules = _rules()
    amazon = Candidate(company="Amazon", domain="amazon.com",
                       segment="logistics_warehouse", footprint="national", size_band="enterprise")
    C.classify(amazon, rules)
    assert amazon.disposition == DISPOSITION_EXCLUDED, "Amazon excluded under shipped rules"

    # Simulate an edit to config: drop the Amazon exclusion. NO code change.
    edited = copy.deepcopy(rules)
    edited["exclusions"] = [e for e in edited["exclusions"] if e.get("name") != "Amazon"]
    amazon2 = Candidate(company="Amazon", domain="amazon.com",
                        segment="logistics_warehouse", footprint="national", size_band="enterprise")
    C.classify(amazon2, edited)
    assert amazon2.disposition == DISPOSITION_CANDIDATE, \
        "with the exclusion removed, Amazon should classify as a candidate"


def test_grocery_class_exclusion_reads_config():
    rules = _rules()
    g = Candidate(company="Some New Grocer", domain="newgrocer.com",
                  segment="grocery", footprint="national", size_band="large")
    C.classify(g, rules)
    assert g.disposition == DISPOSITION_EXCLUDED
    assert "grocery" in g.rationale.lower()


# --- #3 Stage 1 makes no network calls -----------------------------------------

def test_stage1_makes_no_network_calls():
    import socket
    real = socket.socket

    def _boom(*a, **k):
        raise AssertionError("Stage 1 opened a socket — it must make NO network calls")

    socket.socket = _boom
    try:
        rules = _rules()
        cands = [
            Candidate(company="Unifi Aviation", domain="unifiservice.com",
                      segment="aviation_ground_services", footprint="national", size_band="large"),
            Candidate(company="Amazon", domain="amazon.com", segment="logistics_warehouse"),
            Candidate(company="Random Tech", domain="rt.com", segment="software_tech"),
        ]
        C.classify_batch(cands, rules)
        assert cands[0].disposition == DISPOSITION_CANDIDATE
    finally:
        socket.socket = real


# --- #5 density never rejects; industry label never rejects --------------------

def test_density_invariant_is_hardwired_false():
    assert E.density_rejects(0, 100) is False
    assert E.label_rejects("construction", "manufacturing") is False


def test_low_density_is_needs_review_never_a_reject():
    rules = _rules()
    cand = Candidate(
        company="Cintas-like", domain="cintas-like.com",
        segment="facilities_janitorial", footprint="national", size_band="large",
        scope_verified=True, row_locations_verified=True,
        in_market_volume=120, in_market_volume_basis="measured",
        sampled_applicable={"n": 0, "m": 12, "rejects": []},  # 0 applicable, like Cintas pre-fork
    )
    disp, why = E.stage2_disposition(cand, rules)
    assert disp == DISPOSITION_NEEDS_REVIEW, "0 density must be needs_review, not a reject"
    assert disp not in PERMANENT_DISPOSITIONS
    assert "density never rejects" in why.lower()


def test_wrong_industry_label_does_not_reject():
    # A candidate mislabeled 'construction' (deprioritized) that is really frontline
    # manufacturing must not be permanently killed by the label — the operator
    # re-labels and re-runs. Here we prove the label alone never forces a reject.
    rules = _rules()
    assert E.label_rejects("construction", "manufacturing_production") is False
    reseg = Candidate(company="Cornerstone-like", domain="cs.com",
                      segment="manufacturing_production", footprint="national", size_band="mid")
    C.classify(reseg, rules)
    assert reseg.disposition == DISPOSITION_CANDIDATE


# --- #8 record fields match /add-tenant inputs ---------------------------------

def test_candidate_record_carries_all_add_tenant_inputs():
    fields = set(Candidate().to_dict().keys())
    missing = [f for f in ADD_TENANT_INPUTS if f not in fields]
    assert not missing, f"candidate record is missing /add-tenant inputs: {missing}"


def test_handoff_record_is_exactly_the_add_tenant_inputs():
    c = Candidate(company="X", careers_url="https://x/careers", employer_domain="x.com",
                  source_class="direct-employer", sector="aviation", platform="avature",
                  tenant_identifiers={"host": "h"}, rendering_mode="server",
                  market="WA", scope_params={"state": "Washington"},
                  # decision-only noise that must be dropped at the seam:
                  tier=1, disposition="qualified", sampled_applicable={"n": 5, "m": 6})
    rec = RP.handoff_record(c)
    assert set(rec.keys()) == set(ADD_TENANT_INPUTS), "handoff must emit exactly the /add-tenant inputs"
    assert "tier" not in rec and "disposition" not in rec and "sampled_applicable" not in rec


def test_add_tenant_input_names_exist_in_real_tenants_json():
    # The common coordinates the record promises must be real tenants.json keys.
    tj = json.load(open(os.path.join(ROOT, "config", "tenants.json"), encoding="utf-8"))
    seen = set()
    for plat, ents in tj.items():
        if plat.startswith("_"):
            continue
        for k, v in ents.items():
            if isinstance(v, dict):
                seen |= set(v.keys())
    for f in ("careers_url", "employer_domain", "source_class"):
        assert f in seen, f"{f!r} should be a real tenants.json field the record mirrors"


# --- #10 resumable / idempotent / re-eval without refetch ----------------------

def _temp_store():
    d = tempfile.mkdtemp(prefix="disc_store_")
    os.environ["DISCOVERY_STATE_DIR"] = d
    return d


def test_store_roundtrip_and_idempotent_upsert():
    _temp_store()
    rules = _rules()
    cand = Candidate(company="Unifi Aviation", domain="unifiservice.com",
                     segment="aviation_ground_services", footprint="national", size_band="large")
    a = S.upsert_classified(cand, rules)
    assert a.disposition == DISPOSITION_CANDIDATE and a.tier == 1
    # Re-running the SAME candidate returns the stored disposition, no reclassify churn.
    again = S.upsert_classified(
        Candidate(company="Unifi Aviation", domain="unifiservice.com", segment="aviation_ground_services",
                  footprint="national", size_band="large"),
        rules)
    assert again.disposition == a.disposition
    loaded = S.load("unifiservice.com")
    assert loaded is not None and loaded.company == "Unifi Aviation"


def test_reeval_on_rule_change_without_refetch():
    d = _temp_store()
    rules = _rules()
    # A frontline candidate WITH captured Stage-2 facts (as if browser-probed).
    cand = Candidate(company="Unifi Aviation", domain="unifiservice.com",
                     segment="aviation_ground_services", footprint="national", size_band="large",
                     platform="avature", adapter_exists=False, rendering_mode="server",
                     tenant_identifiers={"careers_url": "https://careers.unifiservice.com/careers"},
                     scope_verified=True, row_locations_verified=True,
                     in_market_volume=691, in_market_volume_basis="measured",
                     sampled_applicable={"n": 6, "m": 8})
    S.upsert_classified(cand, rules)
    probed = S.apply_probe("unifiservice.com", {"stage": "probed"}, rules)
    assert probed.disposition == DISPOSITION_QUALIFIED

    facts_before = {k: probed.to_dict()[k] for k in
                    ("segment", "footprint", "platform", "tenant_identifiers", "in_market_volume")}
    mtime_before = os.path.getmtime(os.path.join(d, "unifiservice_com.json"))

    # Edit the rules on disk: aviation_ground_services is now deprioritized/hold.
    edited = copy.deepcopy(rules)
    edited["deprioritized"].append(
        {"segment": "aviation_ground_services", "status": "hold", "note": "test hold"})
    edited["segments"]["frontline"] = [s for s in edited["segments"]["frontline"]
                                       if s != "aviation_ground_services"]
    tmp_rules = os.path.join(tempfile.gettempdir(), "sourcing_rules_edited.json")
    json.dump(edited, open(tmp_rules, "w", encoding="utf-8"))
    edited_loaded = R.load_rules(tmp_rules)

    changes = S.reevaluate_all(edited_loaded, only_stale=False)
    assert any(ch["key"] == "unifiservice.com" for ch in changes), "re-eval should flip Unifi"
    after = S.load("unifiservice.com")
    assert after.disposition == "deprioritized", "rule edit re-disposed without any re-fetch"
    # Facts are untouched — re-eval never re-fetches.
    facts_after = {k: after.to_dict()[k] for k in
                   ("segment", "footprint", "platform", "tenant_identifiers", "in_market_volume")}
    assert facts_after == facts_before, "captured facts must survive a rule re-eval unchanged"
    assert after.in_market_volume == 691


def test_query_by_fixable_vs_permanent():
    _temp_store()
    rules = _rules()
    for c in [
        Candidate(company="Amazon", domain="amazon.com", segment="logistics_warehouse"),
        Candidate(company="TechCo", domain="techco.com", segment="software_tech"),
        Candidate(company="ThinCo", domain="thinco.com", segment="retail",
                  footprint="national", size_band="large"),
    ]:
        S.upsert_classified(c, rules)
    # A thin measured volume -> needs_review (fixable), queryable by "volume".
    S.apply_probe("thinco.com", {"scope_verified": True, "row_locations_verified": True,
                                 "in_market_volume": 4, "in_market_volume_basis": "measured"}, rules)
    all_c = S.load_all()
    permanent = RP.query(all_c, revisitable=False)
    fixable = RP.query(all_c, revisitable=True)
    assert {c.company for c in permanent} >= {"Amazon", "TechCo"}
    assert any("volume" in c.rationale.lower() for c in RP.query(all_c, failed_on="volume"))
    assert all(c.disposition not in PERMANENT_DISPOSITIONS for c in fixable)


# --- #11 airport employers reproduce, given captured facts ---------------------

def test_excluded_candidate_does_not_drive_adapter_build():
    # An owner-vetoed employer on a new platform must NOT show up as an
    # adapter-build candidate (it was rejected — we won't build for it).
    _temp_store()
    rules = _rules()
    cand = Candidate(company="Vetoed Co", domain="vetoed.com", segment="retail",
                     footprint="national", size_band="large",
                     platform="some_new_ats", adapter_exists=False)
    S.upsert_classified(cand, rules)
    S.apply_probe("vetoed.com", {"platform": "some_new_ats", "adapter_exists": False}, rules)
    # Before exclusion: it IS a build candidate.
    assert any(u["platform"] == "some_new_ats" for u in RP.unknown_platforms(S.load_all()))
    # Exclude by name via a rule edit, re-dispose, and it must drop off the tally.
    edited = copy.deepcopy(rules)
    edited["exclusions"].append({"name": "Vetoed Co", "reason": "test veto"})
    S.reevaluate_all(edited, only_stale=False)
    assert S.load("vetoed.com").disposition == DISPOSITION_EXCLUDED
    assert not any(u["platform"] == "some_new_ats" for u in RP.unknown_platforms(S.load_all())), \
        "an excluded employer must not recommend an adapter build"


def test_multi_market_qualifies_when_any_market_clears():
    # A thin WA must not sink a strong TX (the WFS case: WA 15, TX 68).
    rules = _rules()
    cand = Candidate(company="WFS-like", domain="wfslike.com", segment="logistics_warehouse",
                     footprint="national", size_band="large", target_markets=["WA", "TX"],
                     market_scope={
                         "WA": {"in_market_volume": 15, "basis": "measured",
                                "scope_verified": True, "row_locations_verified": True},
                         "TX": {"in_market_volume": 68, "basis": "measured",
                                "scope_verified": True, "row_locations_verified": True},
                     })
    disp, why = E.stage2_disposition(cand, rules)
    assert disp == DISPOSITION_QUALIFIED, "one clearing market (TX 68) should qualify"
    assert "TX" in why and "WA" in why, "note should name the cleared TX and the held thin WA"

    # If BOTH markets are thin, it stays needs_review (fixable, never a reject).
    cand.market_scope["TX"]["in_market_volume"] = 4
    disp2, _ = E.stage2_disposition(cand, rules)
    assert disp2 == DISPOSITION_NEEDS_REVIEW
    assert disp2 not in PERMANENT_DISPOSITIONS


def test_airport_probed_three_reproduce():
    _temp_store()
    rules = _rules()
    # Seed the nine-employer cluster at Stage 1 (segments/footprints as in Pass A).
    cluster = [
        Candidate(company="Unifi Aviation", domain="unifiservice.com",
                  segment="aviation_ground_services", footprint="national", size_band="large"),
        Candidate(company="PrimeFlight Aviation Services", domain="primeflight.com",
                  segment="aviation_ground_services", footprint="national", size_band="large"),
        Candidate(company="Menzies Aviation", domain="jmenzies.com",
                  segment="aviation_ground_services", footprint="national", size_band="large"),
    ]
    for c in cluster:
        S.upsert_classified(c, rules)

    # Unifi: server-rendered, state filter present, SEA inventory, five categories -> QUALIFIED.
    unifi = S.apply_probe("unifiservice.com", {
        "platform": "avature", "adapter_exists": False, "rendering_mode": "server",
        "careers_url": "https://careers.unifiservice.com/careers",
        "tenant_identifiers": {"careers_url": "https://careers.unifiservice.com/careers"},
        "market": "WA", "scope_params": {"state": "Washington"},
        "scope_verified": True, "row_locations_verified": True,
        "in_market_volume": 691, "in_market_volume_basis": "measured",
        "sampled_applicable": {"n": 7, "m": 8},
    }, rules)
    assert unifi.platform == "avature" and unifi.adapter_exists is False
    assert unifi.disposition == DISPOSITION_QUALIFIED, "Unifi is the strongest of the three"

    # PrimeFlight: UltiPro over a Drupal marketing site — vendor != ATS captured.
    pf = S.apply_probe("primeflight.com", {
        "platform": "ultipro", "adapter_exists": False, "rendering_mode": "client",
        "front_end_vendor": "Drupal",
        "tenant_identifiers": {"company_code": "PRI1027PFAS",
                               "job_board_guid": "77b3fc1f-af0c-4943-b588-446adc55a407"},
        "scope_verified": False, "row_locations_verified": False,
        "in_market_volume": 500, "in_market_volume_basis": "screening",
        "notes": "UltiPro public endpoint unverified against this tenant; 4 other GUIDs must not be pulled",
    }, rules)
    assert pf.front_end_vendor == "Drupal" and pf.platform == "ultipro"
    # scope not yet verified -> needs_review, exactly the manual 'probe further' state.
    assert pf.disposition == DISPOSITION_NEEDS_REVIEW

    # Menzies: portal looked UK-only, SEA roles not visible -> inconclusive -> needs_review.
    mz = S.apply_probe("jmenzies.com", {
        "platform": "earcu", "adapter_exists": False, "rendering_mode": "server",
        "scope_verified": False, "row_locations_verified": False,
        "notes": "portal looked international/UK-only; US SEA roles not visible on this surface",
    }, rules)
    assert mz.disposition == DISPOSITION_NEEDS_REVIEW, "Menzies is inconclusive, not a reject"

    # And none of the three was permanently rejected on density or label.
    for c in (unifi, pf, mz):
        assert c.disposition not in (DISPOSITION_RULED_OUT, DISPOSITION_EXCLUDED)


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
