# Vendored data — US Census Bureau Gazetteer Files, 2025 vintage

Provenance travels with the data (same rule as job records).

- **Publisher:** U.S. Census Bureau
- **Product:** 2025 Gazetteer Files
- **Source page:** https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
- **Retrieved:** 2026-09-02
- **Status:** Public domain (work of the U.S. federal government, 17 U.S.C. §105). No API key, no vendor, no license terms.

## Files (extracted from the published `.zip`, pipe-delimited `|`)

| file | from | columns used |
|---|---|---|
| `2025_Gaz_zcta_national.txt` | `2025_Gaz_zcta_national.zip` (952,026 bytes) | `GEOID` (ZCTA5), `INTPTLAT`, `INTPTLONG` |
| `2025_Gaz_place_national.txt` | `2025_Gaz_place_national.zip` (1,214,053 bytes) | `USPS` (state), `NAME` (place + LSAD suffix), `INTPTLAT`, `INTPTLONG` |

Download URLs (2025_Gazetteer directory):
- https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_zcta_national.zip
- https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip

## Notes carried from the Census documentation

- **ZCTAs are not USPS ZIP codes.** The Census produces ZIP Code Tabulation Areas because ZIP-code land area is hard to define; it does not distribute USPS ZIP Code products. Some ZIP codes have no ZCTA.
- **`INTPTLAT`/`INTPTLONG` are representative internal points (centroids)**, one per area. Centroid-to-centroid distance is approximate and increasingly so for large places.
- The 2025 files added a `GEOIDFQ` column vs older vintages and are pipe-delimited.
