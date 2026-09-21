# SOP — adding a new employer / config to the pull

**This is mandatory for every new config.** The daily recurring pull (`run_pull.py --all
--publish`) automates the *recurring* pull only. It does **not** automate onboarding — the
steps marked **GATE** below are manual by design and are the quality control. Do not add an
entry to `config/tenants.json` until its GATEs are cleared.

Read this in full before editing config. It encodes rules that are easy to violate and
expensive to unwind (silent undercounts, zombie listings, deleted live jobs).

---

## Invariants (never break these)

1. **Config is data. No adapter or the runner ever branches on tenant identity.** A tenant
   is added by adding a config entry, never by an `if tenant == "..."`. The platform key
   *names the code path* (`python -m adapters.<platform>`).
2. **Extraction vocabulary forks per tenant — DERIVE it, never copy.** The `extraction.openers`
   block must be measured from *that employer's own* captured descriptions. Copying a
   sibling's openers is the #1 way to produce a wrong applicable/density number. Every
   tenant note in `tenants.json` documents its openers as "derived from this capture,
   nothing inherited." Follow that.
3. **Never trust a vendor total.** Report any vendor-declared count as a diagnostic only,
   never a stop condition or a completeness check. (Target reported 2,000 against a real
   12,233.) Completeness = paging to a genuinely empty page + a client-side location filter.
4. **Liveness = the URL is in this pull's index.** The runner's clean-capture depends on the
   index being the current board and the detail cache being reconcilable to it. A new
   detail-cache platform that isn't wired into the reconcile will accumulate zombies.

---

## Step 0 — decide which case you're in

- **Case A — the employer runs an ATS we already support** (Oracle `oracle_orc`, Workday
  `workday`, Target-style `target`, Radancy/TalentBrew `radancy_tb`, Jibe `jibe_api`, Compass
  `compass_api`). → No code. Config + opener derivation only.
- **Case B — a genuinely new ATS / read surface** (the fetch shape differs from every existing
  adapter). → New adapter + `pull.json` entry + (if it has a detail step) a reconcile branch.

Rule for the boundary: **one platform key = one fetch shape.** If the call shape differs from
an existing adapter — even another employer on the same underlying ATS (Allied and Dollar
General were both iCIMS but had unrelated read surfaces) — it is Case B and gets its own key.
`--probe` first; if the shape differs, it is a new platform.

**Read surfaces churn — re-onboarding is a real event.** An employer can migrate its careers
site off one ATS onto another; when it does, the old adapter's endpoint 404s (or returns an
empty board) and the tenant HALTS the pull until it's re-onboarded on the new surface. Dollar
General did exactly this 2026-09-21 (Jibe → Oracle `oracle_orc`): `--probe` the new host, then
treat it as a fresh Case-A onboarding (host/site + **openers derived from a real new capture**,
never ported from the dead surface). While the new surface has no jobs yet, suppress the tenant
(underscore-prefix its key to skip the pull, add its `employer_domain` to `SUPPRESSED_EMPLOYERS`
in `noprobjobs/data/published.js`) rather than leave a halting dead endpoint in the run.

---

## Case A — new employer on an existing ATS

Checklist (do in order):

- [ ] **GATE — read surface + call shape.** Confirm the endpoint/host/site and how it pages.
- [ ] **GATE — probe.** `python -m adapters.<platform> --tenant <newkey> --probe`
      (also `--locate`/`--facets`/`--survey`/`--categories` where the adapter offers them).
      Confirms the endpoint answers, pages, and the page-1 in-scope count is plausible.
- [ ] **GATE — inspect.** `python -m adapters.<platform> --tenant <newkey> --inspect`
      Confirms real field names + fill, so you pin `location_filter` to a **named field** when
      one exists (not a blob/title token — two of the first five tenants were measured wrong
      on a token). Verify the WA token/field against a real capture, not a guess.
- [ ] **GATE — derive openers.** Capture the WA set, measure which headings actually delimit
      the requirements section (colon / bare / prefix / line), and write `extraction.openers`
      from *that*. A headingless template returns NOT_STATED by construction — do not default
      it to a modality.
- [ ] **Add the tenant block to `config/tenants.json`** under the platform's section. Mirror an
      existing sibling: `label`, host/site/`careers_url`, `employer_domain`, `source_class`,
      `sector`, `location_filter`, `extraction.openers`, and a `verified` note with the date +
      what you confirmed.
- [ ] **If the platform is `workday`:** also add the new key to `pull.json`'s
      `workday` → `"tenants"` list (that section is pinned because Target borrows it). Oracle /
      Radancy / Jibe / Compass need **no** `pull.json` change — they enumerate every non-`_`
      key in their section automatically.
- [ ] **Validate** (see "Validation" below).
- [ ] **Add a `config/baseline.json` row** once you accept the first run.

---

## Case B — a new ATS / read surface

- [ ] All Case-A GATEs, plus:
- [ ] **Write `adapters/<platform>.py`** with the standard modes (`--probe --inspect --index/
      --discovery --detail --report --normalize`, plus any surface-specific mode). Write output
      to `out/<PLATFORM>/<tenant>/normalized.jsonl` and detail to `raw/<platform>/<tenant>/detail/`.
- [ ] **Paginate the index/discovery loop through `adapters.paginate.fetch_paged`** — never
      hand-roll `if r.status_code != 200: break`. That shape silently truncated Compass (a 502
      at page 16 → 150 of 316 written as complete) and had been copied into all six adapters.
      `fetch_paged` retries transient 5xx/429, and on exhaustion raises `Truncated`; wrap the
      loop in `try/except Truncated` → log + `return 1`, so a short read fails LOUD (run_pull
      marks the source FAILED) and **never writes a partial set as complete**. The output write
      must sit *after* the loop, outside the `try`, so an abort skips it.
- [ ] **Add a `config/pull.json` platform entry:** `{ "platform": "<x>", "modes": [ordered
      modes], "section": "<x>" }`. Add `"tenants": [...]` only if it shares another platform's
      `tenants.json` section (the Target/Workday case).
- [ ] **If it has a detail cache, wire the reconcile in `run_pull.py`:**
  - add a branch to `_live_detail_names()` returning `{<detail-filename> for each in-scope index
    record}, ext` using the adapter's own `load_index`/`in_scope` + id/filename scheme;
  - add its enumerate dir to `_ENUMERATE_ARTIFACT`.
  - The reconcile **guard** aborts the purge unless the reconstructed live set reproduces the
    cache (kept ≥ 80% of live), so a wrong scheme *fails safe* (zombies remain, flagged) rather
    than deleting live jobs — but you still want it wired so clean-capture actually runs.
- [ ] **Add the tenant(s) to `config/tenants.json`** under the new section.
- [ ] **Validate + baseline.**

---

## Validation (required before it rides in the daily run)

```
python run_pull.py --plan                        # the new tenant appears with the right module + modes + out path
python run_pull.py --tenant <newkey> --dry-run   # index/discovery only, no writes — confirms it fetches
python run_pull.py --tenant <newkey>             # full pull → normalize → enrich → the applicable/density number
```

- Sanity-check the number against the employer's own facet count *as a diagnostic only*. A
  number far off usually means the extractor/openers are wrong for this tenant (Finding 31:
  a low number is the extractor's fault, not the employer's), not that the employer has no
  frontline jobs.
- **Add the `config/baseline.json` row** (`records` / `applicable` / `density`). Until you do,
  that tenant skips the <50%-records and ±15-pt-density halt checks (only zero-records still
  halts it) — so it has no smoke alarm. `run_pull.py --update-baseline` fills it from the last
  report after you've accepted it.

---

## Guardrails / gotchas

- **`config/baseline.json` is updated only on an ACCEPTED run, never automatically.** Inspect
  the movement file and the numbers first, then `--update-baseline`.
- **`first_seen` is preserved across pulls** via `out/<platform>/<tenant>/seen_state.json`
  (not in `raw/`), so clean-capture wiping `raw/` never resets it.
- **The movement gate halts on verdict/category CHANGES, not board turnover.** New tenants add
  a burst of "entered" jobs on their first live run — that's turnover, not a change, and does
  not halt.
- **A second tenant per sector is the real baseline.** One tenant in a new sector is n=1 and
  provisional — there's no smoke alarm until a second employer in that sector exists.
- **Licensed-occupation / credential gates** may make a clinical or security employer return
  near-zero applicable for a *config* reason (a missing credential on the allowlist), not a
  finding about the employer. Check the gate-attribution before concluding the employer is dry.
- **Validate a source's date field before mapping it to `posted_at`.** `posted_at` is a
  timestamptz column; a non-date value (a vendor's own requisition id, a marketing label) makes
  Postgres 22007-reject the ENTIRE upsert row in `analyze.supabase_sink`, silently dropping the
  job — the tenant's applicable count at report far exceeds its published/DB row count. The
  Paradox `postedAt` field carried exactly this (`JR13558-1` on Shake Shack) and dropped 100% of
  the tenant for its whole life until fixed. Adapters must emit a real ISO date or `None`, never
  a raw passthrough. **Where it surfaces:** `out/quarantine.jsonl` — "NOT published" rows are a
  real drop (investigate); "pay suppressed; job PUBLISHED" rows are benign.

---

## Sign-off

A new config is "done" when: its GATEs are cleared and dated in the `verified` note; `--plan`
shows it wired correctly; a full `--tenant` run produces a plausible, gate-attributed number;
its `baseline.json` row exists; and (Case B) its reconcile branch is wired and the guard
passes on a real run (`reconcile <tenant>: … kept …` with no SKIP). Only then does it belong
in `--all`.
