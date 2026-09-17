"""
Tenant-discovery agent — finds and qualifies employer domains, then hands an
approved candidate record to /add-tenant.

Design contract (see the build spec):
  - Discovery FINDS and QUALIFIES. /add-tenant ONBOARDS. The candidate record is
    the seam; discovery emits exactly the facts /add-tenant consumes.
  - Every sourcing rule lives in config/sourcing_rules.json. ZERO rules in code.
    Change a rule there, re-run, and a disposition changes with no code edit.
  - Three stages: Stage 1 classify (NO network), Stage 2 browser pass + probe
    (tier 1 only, human-approved), Stage 3 = /add-tenant (unchanged, external).
  - Facts are cached per candidate; dispositions are re-evaluated against current
    rules WITHOUT re-fetching. Resumable, idempotent, queryable.

Modules:
  rules     load + validate config/sourcing_rules.json
  record    the candidate record (field names match /add-tenant's inputs)
  classify  Stage 1 — pure, no network
  evaluate  the role-level requirement gate (density never rejects)
  store     per-candidate persistence, idempotency, re-eval-on-rule-change
  report    queryable dispositions + the approval report + unknown-platform tally
"""
