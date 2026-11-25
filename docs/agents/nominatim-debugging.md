# Debugging address fields against Nominatim

<!-- cspell:words isaddress placex Kingsbridge Tavistock Totnes Ivybridge -->

Use this when a Place's city, postal town, or neighbourhood is wrong or missing. Most of these reports trace to the Nominatim `address` Places received, not to Places' parsing. Settle which side owns the fault before changing code.

## How address keys become Places fields

`match_city_types` in `custom_components/places/parse_osm.py` picks one Nominatim `address` key each for city, postal town, and neighbourhood, from the overlapping precedence lists in `custom_components/places/const.py`. The rules and their history are in [ADR 0002: address-field precedence](../adr/0002-address-field-precedence.md).

So a field is empty when the keys that would feed it are absent from the `address`. Example: when `address` has `city` but no `town`, postal town stays empty.

## Probe first

Run the probe. It prints the reverse `address`, the key Places picks for each field, and the Nominatim address chain with `rank_address` and `isaddress`:

```sh
./.venv/bin/python -m tools.nominatim_probe --point LAT,LON --relation OSM_RELATION_ID
```

`--point` and `--relation` repeat. The probe spaces requests 1.2 s apart (Nominatim allows 1 request per second), times each out after 12 s, flushes every line, and exits `1` if any request failed.

For ad-hoc calls beyond the probe, keep the same discipline: a generic User-Agent, a request timeout, ≥1 s spacing, and unbuffered output (`python -u` or `print(..., flush=True)`). A loop without a timeout and with buffered output can hang in the background showing nothing.

## Endpoints

| Purpose | URL |
| --- | --- |
| Reverse (what Places requests) | `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=LAT&lon=LON&addressdetails=1&namedetails=1&zoom=18` |
| Search by name | `https://nominatim.openstreetmap.org/search?q=NAME&format=jsonv2&addressdetails=1&limit=5` |
| Details: `rank_address`, `rank_search`, `admin_level`, `indexed_date`, linked places, address chain | `https://nominatim.openstreetmap.org/details?osmtype=R&osmid=ID&addressdetails=1&linkedplaces=1&format=json` |
| OSM edit history of a relation | `https://api.openstreetmap.org/api/0.6/relation/ID/history.json` |
| One OSM changeset | `https://api.openstreetmap.org/api/0.6/changeset/ID.json` |
| A relation with its members | `https://api.openstreetmap.org/api/0.6/relation/ID/full.json` |

## One place per `rank_address`

Nominatim keeps at most one place per `rank_address` in an address. In the details address chain, the loser of a tie shows `isaddress: false` and never appears in the reverse `address`.

A boundary's rank must exceed the boundary that contains it (`lib-sql/functions/placex_triggers.sql` in Nominatim: "We must always increase the address level relative to the admin boundary"). In England, a civil parish (`admin_level` 10) linked to a `place=town` node normally gets `rank_address` 20 and appears as `town`. If Nominatim did not see the containing district (`admin_level` 8, rank 16) when it indexed the parish, the parish takes the town's own rank 16, ties with the district, and one of them drops out of the address.

### Diagnose a tie

1. Run the probe on the reported coordinate. A tie shows as two chain entries with the same `rank_address`, one with `isaddress` `no`.
2. Probe the dropped relation and a healthy comparator of the same kind (same `admin_level`, linked to the same `place` type). The dropped one has the lower `rank_address`, and its own chain is missing the containing district.
3. Compare the dropped relation's `indexed_date` with the containing district's OSM history (`history.json`, then the changeset). An edit to the district just before `indexed_date` explains the stale rank.

The diagnosis is done when you can name the dropped relation, its rank against the comparator's, and the edit that preceded its indexing. That is a Nominatim data or indexing fault: report it upstream (OSM or Nominatim) rather than changing `match_city_types`. A reindex, often triggered by any later edit to the relation, usually clears it.

## Worked example: #550, postal town unknown in Kingsbridge

Probe of `50.2818,-3.7770` (Kingsbridge Quay, Devon), 2026-11-25:

```text
  Places mapping:
  city           'South Hams' from address.city
  postal_town    (empty)
  neighbourhood  (empty)
  address chain (rank_address, isaddress, place_type/type, admin_level):
    27 yes "Square's Quay" residential admin_level=15 W78058089
    16 no  'Kingsbridge' administrative admin_level=10 R3544003
    16 yes 'South Hams' administrative admin_level=8 R2118151
```

- Kingsbridge parish (R3544003) has `rank_address` 16 and `rank_search` 20, `indexed_date` 2026-11-16 00:10, and its own chain lacks South Hams. The comparator Tavistock parish (R3600281, linked to `place=town`) has rank 20 under West Devon.
- South Hams district (R2118151) was edited 2026-11-16 00:08 (changeset 192008729). The parishes Kingsbridge 3544003, Totnes 3531842, Ivybridge 3561765, and Dartmouth 3534550 were reindexed at 00:10 and stuck at rank 16.
- The tie does not always drop the parish. In Dartmouth (R3534550) the district lost instead, so the reverse `address` has `town: Dartmouth` and no South Hams.
- So in Kingsbridge Nominatim returned no `town`, and postal town had nothing to take. Places parsed correctly; the fault is upstream.
