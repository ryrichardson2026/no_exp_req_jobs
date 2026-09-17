---
description: Discover and qualify new tenant candidates that feed /add-tenant
argument-hint: <a domain list, an NLx capture, a cluster, or one URL>
---
We are running TENANT DISCOVERY. Discovery FINDS and QUALIFIES employers; it produces
the candidate records that `/add-tenant` consumes. It does **not** onboard, write config,
commit, or run a pull. It ends at a report a human approves.

Target input: $ARGUMENTS  (any list — a domain list, the NLx capture, a cluster, one URL)

The engine is the `discovery` package + `config/sourcing_rules.json`. **Every sourcing
rule lives in that config; none is in your head or in code.** Read it once at the start of
the run so your judgement matches the file: `python -m discovery report` shows current
state; `config/sourcing_rules.json` holds the rules.

Run the three stages in order. STOP for approval where marked.

## Stage 1 — CLASSIFY (no network)
1. Turn the input into candidate rows: `{company, domain, careers_url?, segment, size_band,
   footprint, input_class?}`. Segment/footprint/size are your read of public knowledge —
   **do not fetch**. Unknown fields stay blank (a blank drops a tier; never estimate).
   Segment must be one of `config/sourcing_rules.json` → `segments`; if a real employer
   needs a segment that isn't there, add it to the config first, don't force-fit.
2. Write the rows to a JSON file and classify:
   `python -m discovery classify <rows.json>`. This reads the rules, dispositions every row
   (excluded / deprioritized / ruled_out / needs_review / candidate+tier), and persists them.
3. Show me the report (`python -m discovery report`). **PAUSE.** I approve the tier order
   before any browser opens. No candidate reaches a browser without an approved tier.

## Markets: WA and TX (where applicable)
The default target markets are **WA and TX**. A national employer's adapter serves every
market from one build, so capture BOTH markets' scope for national candidates
(`target_markets = ["WA","TX"]`); TX airports are DFW/IAH/AUS/SAT. TX is "not applicable"
for a regional/local employer that doesn't operate there — set `["WA"]` and say why.
Record per-market scope under `market_scope` (keyed by market code). The handoff `market`
stays a SINGLE value (the primary, WA) because /add-tenant consumes one market today; whether
TX becomes a second scoped config or a runtime market parameter is an onboarding-time decision
to FLAG, not to bake into the record.

## Stage 2 — BROWSER PASS + PROBE (tier 1 first, one visit per employer)
Only `candidate`-disposition rows, best tier first. For each approved employer, ONE browser
pass captures, PER TARGET MARKET (WA, and TX where applicable): careers resolution, market
filter, volume read, role mix, sampled density — plus once per employer: ATS identification,
rendering mode. Batch rules: **one request/sec per domain; never run
domains concurrently against a shared platform host** (`wd5.myworkdaysite.com` serves many
tenants); **respect robots — a disallow is a stop**; **no unscoped pull, ever**.

Four rules that are non-negotiable:
- **Density never rejects.** A low applicable estimate is `needs_review`, never a reject
  (Cintas read 0 until per-tenant openers were forked, then 57). The engine enforces this;
  don't override it.
- **Industry label never rejects.** A wrong segment guess gets re-labelled and re-run, never
  rejected (Cornerstone read construction, was manufacturing; Sysco read warehouse, was sales+CDL).
- **Verify returned row LOCATIONS, not just the count.** U-Haul's own site resolves the bare
  state name to Washington DC. Set `row_locations_verified` only after you've eyeballed rows.
- **Identify the ATS by FOLLOWING THE APPLY LINK**, never by the careers hostname. Confirmed
  vendor-over-ATS cases: US Foods = Phenom over Workday; Sysco = Radancy over Workday;
  Marriott = Paradox over Oracle ORC; Cornerstone = SmartRecruiters Attrax; PrimeFlight =
  Drupal over UltiPro. Record `front_end_vendor` when it differs from `platform`.
- **Record `rendering_mode`** (server = HTML is the payload, no XHR to find; client = GET
  returns an empty shell, browser capture required) — it decides the capture method.

Write each employer's findings as a probe patch (a partial candidate dict keyed by `domain`)
and ingest it: `python -m discovery ingest <probe.json>`. The engine merges the facts, re-runs
Stage 1 (in case the probe corrected the label), and lets Stage 2 decide qualified vs
needs_review. `tenant_identifiers` and `scope_params` are platform-specific objects whose KEYS
are the real `tenants.json` field names for that platform (host/site_number, tenant/site,
org_id, careers_host/api_url, widgets_url, company_code/guid, …) so `/add-tenant` lifts them
across with no renaming. Show me each result. **PAUSE per candidate** before it's treated as
qualified.

## Stage 3 — HAND OFF (existing command, unchanged)
For each candidate I approve as `qualified`, print its handoff record
(`python -m discovery handoff --key <domain>`) — that dict is exactly `/add-tenant`'s inputs.
Then, and only then, I run `/add-tenant`. Discovery does not run it for me.

## Always
- **Never** write to `config/tenants.json`, `config/pull.json`, or any config; **never** commit;
  **never** run `run_pull.py`/`--pull`. The only file discovery writes is its own state under
  `out/discovery/`.
- **Re-runs are cheap and safe.** A completed candidate returns its disposition without
  re-fetching. When a rule changes, `python -m discovery reeval` re-disposes the affected
  candidates from cached facts — no re-fetch. Dispositions are queryable
  (`python -m discovery query --failed-on volume`, `--revisitable`, `--permanent`).
- **Unknown platforms accumulate.** After a batch, `python -m discovery report` tallies
  platforms with no adapter; a platform seen ≥3× is flagged BUILD NEXT — state that
  recommendation to me, don't leave it in a column. A platform serving one employer is a
  worse adapter investment than one serving three.
