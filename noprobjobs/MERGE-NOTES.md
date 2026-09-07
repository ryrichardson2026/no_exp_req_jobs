# Merge notes — 4 September 2026

Reconciled from two Claude Design workspaces into one set.

## Which copy won, per file

| File | Source | Reason |
|---|---|---|
| Job Board.dc.html | board workspace | Only copy with the circular palette, Archivo, two-tier sort, and Get job alerts |
| Job Card.dc.html | board workspace | Styled; save control already removed in both |
| Job Page.dc.html | board workspace | Styled |
| Filter Panel.dc.html | board workspace | Styled — radii 8px to 3px, selected state accent to ink, surface to surface-raised |
| Landing Page.dc.html | landing workspace | Only copy that exists |
| Landing Screen.dc.html | landing workspace | Only copy that exists |
| support.js | either | Byte-identical, 69150 bytes |
| data/* | landing workspace | Only copy with PULLED_AT, resolve.js and record.js |
| data/target-longest.json | board workspace | Board-only fixture |

## Edits made during the merge

1. **Landing header replaced with the board treatment.** Was navy bar, marigold wordmark text, tagline stacked, newsprint button. Now newsprint ground with a 2px navy bottom rule, wordmark as navy on a marigold block, tagline inline in muted navy, button filled accent red. Tagline hides below the wide breakpoint so the wordmark and button always fit at 390px.
2. **font-stretch aligned to 112% everywhere.** Landing was on 125%, the top of Archivo's width axis, which read over-stretched. 11 occurrences changed.
3. **Stale palette blocks deleted.** `[data-palette="moss"]` and `[data-palette="plum"]` still held oklch blues and greens under a hex circular base — switching to either produced a broken palette. The now-dead `palette` prop was removed from the Landing Page props schema at the same time.

## Verified after merge

- One token block, 32 tokens, in Job Board.dc.html. Landing Page.dc.html is byte-identical on every token. All other files carry no :root and inherit.
- No `toggleSave` in any file.
- `Get job alerts` present on both surfaces, no sign-in path anywhere.
- Every `import("./data/*.js")` resolves to a file present in data/.
- Both surfaces read `m.RECORDS` from the same jobs.js. Landing additionally reads `PULLED_AT`; board additionally reads `CITY_GEO`. No conflict.
- 123 records, identical internal_id set across both original copies.
- font-stretch is 112% in all 6 files.

## Known follow-ups — not fixed here

**1. Duplicate location resolver.** `data/resolve.js` exports RADII, cityKey, cityName, haversine, resolveLocation, unmatchedLine and UNMATCHED. Only Landing Screen imports it. Job Board carries its own inline copy of resolveLocation, cityKey, cityName and haversine — currently byte-identical to the module, but missing `unmatchedLine`. This is a regression: the module was extracted specifically so both surfaces shared one implementation, and the board's styling pass reintroduced an inline copy. Not fixed during the merge because rewiring the board's script to import the module is a behavioural change, not a reconciliation. Fix before the repo import.

**2. Landing to board filter handoff.** Not verifiable from static files. Confirm the landing search — selected Type of Work chips plus the location field — maps to applied filters on the board, and that the board opens in that state rather than unfiltered.

**3. Card ranking parity.** Confirm both surfaces order records identically. The two-tier freshness key (posted_at tier 0, first_seen tier 1, first_seen never displayed) is wired in Job Board only; Landing Screen has no equivalent logic and may be ordering differently.

**4. Company logos.** Currently a favicon service plus manual loads. Will not survive a static export. Decide capture-at-ingest before the repo import.

**5. Prerender for indexability.** Everything renders client-side, so a crawler sees an empty document. JobPosting markup must sit on prerendered single-job pages, never on a list page. Expired jobs need 410, which a static file set cannot produce without a Vercel rule.
