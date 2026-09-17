# Discovery agent

Finds and qualifies employer domains, then hands an approved **candidate record** to
`/add-tenant`. Reusable pipeline, not a one-off pass. See the build spec for the design
rationale; this file is the maintainer's map.

## The seam
```
DISCOVERY  ──▶  candidate record  ──▶  /add-tenant (unchanged)
finds/qualifies      the contract         onboards
```
`/add-tenant` does not change. Discovery emits exactly the facts it consumes. The record
field names ARE the contract (`discovery/record.py` → `ADD_TENANT_INPUTS`); there is no
translation layer. `tenant_identifiers` and `scope_params` are platform-specific objects
whose keys are the real `tenants.json` coordinate fields for that platform.

## Rules live in one place
`config/sourcing_rules.json` is the single source of truth: exclusions, deprioritized,
segments, footprint/size weights, thresholds, gates, carve-outs. **Zero rules in code.**
`discovery/rules.py` is the only reader. Change a rule → `python -m discovery reeval`
re-disposes cached candidates with no code edit and no re-fetch.

## Markets
Default targets are **WA and TX**. National employers serve every market from one adapter, so
the depth pass captures both; TX is skipped where an employer doesn't operate there ("if
applicable"). Each candidate carries `target_markets` (e.g. `["WA","TX"]`) and per-market scope
in `market_scope`. The handoff `market` stays single (primary = WA) — `/add-tenant` consumes one
market today; multi-market onboarding (second scoped config vs. runtime param) is a flagged
onboarding-time decision, not baked into the record.

## Stages
| Stage | What | Code |
|------|------|------|
| 1 CLASSIFY | no network, whole list, tier it | `discovery/classify.py` |
| 2 BROWSER PASS + PROBE | tier 1 first, ATS id + geo scope + density | `/discover` drives Chrome; `discovery/evaluate.py` scores; `store.apply_probe` ingests |
| 3 /add-tenant | existing command | external |

Approval sits between 1→2 and before every 3.

## CLI
```
python -m discovery classify <rows.json>      Stage 1 -> store
python -m discovery report                     approval report + unknown-platform tally
python -m discovery query --failed-on volume   queryable dispositions
python -m discovery query --revisitable        fixable only (--permanent for the reverse)
python -m discovery reeval [--all]             re-dispose vs current rules, no re-fetch
python -m discovery ingest <probe.json>        merge Stage-2 browser findings
python -m discovery handoff --key <domain>     the /add-tenant record
```
State: `out/discovery/candidates/*.json` (override `$DISCOVERY_STATE_DIR`).

## Acceptance → where satisfied
1. Rules from config, zero in code — `rules.py`; `tests/test_discovery.py::test_no_rule_literals_hardcoded_in_classify`
2. Rule change flips a disposition, no code edit — `test_rule_change_flips_disposition`
3. Stage 1 makes no network calls — `test_stage1_makes_no_network_calls`
4. No candidate reaches a browser without an approved tier — `/discover` Stage 1 PAUSE; only `candidate`-disposition rows are browser-worthy (`classify.priority_order`)
5. Density never rejects; label never rejects — `evaluate.density_rejects`/`label_rejects` (hardwired False); `test_low_density_is_needs_review_never_a_reject`, `test_wrong_industry_label_does_not_reject`
6. ATS by following the apply link — `/discover` Stage 2 rule (vendor-over-ATS cases listed)
7. Row locations verified, not counts — `row_locations_verified` gate in `evaluate.stage2_disposition`
8. Record fields match `/add-tenant` inputs exactly — `record.ADD_TENANT_INPUTS`; `test_handoff_record_is_exactly_the_add_tenant_inputs`
9. Writes no config, no commit, no pull — `/discover` "Always" block; the package only writes `out/discovery/`
10. Resumable, idempotent, re-evaluable without re-fetch — `store.py`; `test_reeval_on_rule_change_without_refetch`
11. The three probed airport employers reproduce — `test_airport_probed_three_reproduce` (logic level); live reproduction is `/discover` Stage 2

Run the tests: `python tests/test_discovery.py` (repo has no pytest).
