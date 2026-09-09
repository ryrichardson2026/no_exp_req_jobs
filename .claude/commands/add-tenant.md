---
description: Onboard a new employer/config to the job pull (runs the SOP)
argument-hint: <employer name> [ATS/platform if known]
---
We are ONBOARDING A NEW CONFIG to the recurring job pull.

Target: $ARGUMENTS

First, read and treat as authoritative the required SOP: `docs/onboarding-a-tenant.md`. Then
drive the onboarding for the target above, following it verbatim:

1. **Case A vs B.** Decide whether this employer runs an ATS we already support (Case A —
   config only) or a new read surface (Case B — new adapter + `pull.json` + reconcile branch).
   If the ATS wasn't given, identify the read surface and run `--probe` first: a differing
   fetch shape is a NEW platform with its own key.
2. **Walk the GATEs interactively.** Run `python -m adapters.<platform> --tenant <key> --probe`
   then `--inspect` (plus `--locate`/`--facets`/`--survey`/`--categories` where offered), show
   me the output, and PAUSE for my confirmation. Do not write any `config/tenants.json` entry
   until the gates are cleared.
3. **Derive `extraction.openers` from THIS employer's own captured descriptions** — never copy
   a sibling's. Show me the measured heading counts (which headings actually delimit the
   requirements section) before committing them.
4. **Make only the config edits the SOP prescribes** (`tenants.json`; plus `pull.json` and a
   `run_pull.py` reconcile branch only for Case B). Honor the invariants: config is data (no
   tenant branching), never trust a vendor total as a stop condition, wire the reconcile for a
   new detail-cache platform (the guard fails safe).
5. **Validate:** `python run_pull.py --plan`, then `python run_pull.py --tenant <key> --dry-run`,
   then a full `python run_pull.py --tenant <key>`; report applicable/density with gate
   attribution. Add the `config/baseline.json` row only after I accept the numbers.
6. **Do NOT** enable it in `--all` / publish, or run `--all`, until I explicitly sign it off.

Stop and ask me at every GATE and before any config-writing or destructive step.
