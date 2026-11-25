---
status: accepted
---

# How Nominatim `address` keys become Place address fields

Nominatim's reverse `address` object can hold several place-like keys at once (`city`, `town`, `village`, `suburb`, and so on), and different regions tag the same kind of place differently. Places maps those keys onto its address fields with fixed precedence lists rather than taking one key per field. The city, postal town and neighbourhood lists overlap on purpose, so a key can feed a lower field when a higher-ranked key has already filled a higher field. Each Update reads Nominatim's `address` as returned, and a field whose keys are all missing stays blank.

**Source of truth:** `CITY_LIST`, `POSTAL_TOWN_LIST` and `NEIGHBOURHOOD_LIST` in `custom_components/places/const.py`, together with the address parsing in `custom_components/places/parse_osm.py` (`OSMParser`). Read the lists and the parser there. This ADR doesn't copy them. An open PR (Snuffy2/places#299) moves the city, postal town and neighbourhood matching into a standalone `match_city_types(address)` entry point with unchanged behavior. The rules below describe behavior, so they hold whichever layout is current.

## Decisions

### 1. City, postal town and neighbourhood use overlapping, ordered lists

- **City** takes the first `CITY_LIST` key present in `address`.
- **Postal town** takes the first `POSTAL_TOWN_LIST` key present that is not at or above the matched city key in `CITY_LIST` order. If no city key matched, nothing is excluded.
- **Neighbourhood** takes the first `NEIGHBOURHOOD_LIST` key present that is not excluded by either earlier group. Both the keys at or above the city match and the keys at or above the postal town match (within the postal town candidates) are excluded.
- **City (clean)** is derived from City by dropping ` Township` and rewriting `City of X` as `X City`.

Examples:

- `{city: "Sydney", town: "Parramatta"}` gives City *Sydney* and Postal town *Parramatta*. This is the case from custom-components/places#282.
- `{town: "A", suburb: "B", neighbourhood: "C"}` gives City *A*, Postal town *B* and Neighbourhood *C*.
- `{city: "X", village: "V", suburb: "S"}` gives City *X*, Postal town *V* and Neighbourhood *S*. Lower-ranked city-like keys stay available to the later groups.

Why: custom-components/places#282 reported that postal town was often empty even though Nominatim's `display_name` showed one. The cause was a Parramatta address tagged `city=Sydney` plus `town=Parramatta`, while the old logic filled postal town only from `suburb` or `city_district`. The maintainer said in that issue that they wanted to fix it without breaking other locations and without city and postal town showing the same value "unless appropriate". The fix in PR custom-components/places#285 (commit `cc28017`) introduced the three lists. Its description says the lists follow the OpenStreetMap `place` key hierarchy (<https://wiki.openstreetmap.org/wiki/Key:place>). Each group searches "below" the key used by the group before it. Fixes #282.

History that kept the behavior:

- PR custom-components/places#341 (`48ab3f7`) moved the lists into `const.py` and added the "intentional overlaps" comment above them.
- PR custom-components/places#420 (`360a08c`, commit bullet "fix: preserve OSM address precedence") replaced in-place list removal with explicit "at or above the match" exclusion. The same PR added `test_set_city_details_preserves_overlapping_type_precedence` and `test_set_city_details_preserves_lower_priority_postal_town` in `tests/test_parse_osm.py`, which pin the precedence. The algorithm from #285 and the one after #420 give the same results. The only difference is that #285 also dropped every `CITY_LIST` key when no city matched, and in that case none of those keys are present anyway.

Inferred, not stated in a source: `city_district` and `municipality` sit at the end of `CITY_LIST`, and are absent from the other lists, so that they fill City only when no settlement-level key exists.

### 2. The other address fields each read one fixed key

These fields have no precedence list. Each reads a single key and is left unset when that key is absent.

| Field group | Nominatim key | Example |
| --- | --- | --- |
| Street, street number | `road`, `house_number` | `{road: "Main St", house_number: "12"}` gives Street *Main St* and Street number *12*. |
| Place name fallback | `retail` | Used only when no place name was found, or when the place name just repeats the street on a `highway` result. |
| Region | `state` | `{state: "California"}` gives Region *California*. `province` and `region` are not read from `address`. They exist only as Display option aliases for the region field. |
| State abbreviation | `ISO3166-2-lvl4` | `"US-CA"` gives *CA* (the part after the first `-`, upper-cased). |
| County, country, country code | `county`, `country`, `country_code` | `{country_code: "us"}` gives *US* (upper-cased). |
| Postal code | `postcode` | `{postcode: "90210"}` gives *90210*. |

Outside `address`, the parser fills further fields from the top-level response:

- **Formatted address:** `display_name`.
- **OSM ID and OSM type:** `osm_id` and `osm_type`.
- **Route number:** only for results whose category is `highway`. It is the first segment of `namedetails.ref`, split on `; \ / , . :`, that contains a digit. For example, `"I 5;CA 1"` gives *I 5*.

Evidence: the state abbreviation came from `ad9f4ca` ("Add State Abbreviation Attribute"). The `retail` fallback came from `9af440f` ("Set place_name to address, retail if exists"). `road`, `house_number` and `postcode` date from the first import, `33810e0`. None of these commits records an alternative that was considered.

## Consequences

- Moving a key earlier or later in one list changes the other fields as well, because of the exclusion rule. Change the lists only together with the precedence tests named above.
- Results depend on how places near the tracked entity are tagged in OpenStreetMap. The same real-world area may fill City in one country and Postal town in another.

## Open questions

- **Nominatim omits a key.** Nominatim keeps one place per `rank_address`. When two places tie at the same rank, for example a parish tied with its district so that no `town` comes back, postal town is empty. Should Places keep following `address` as returned, or patch around such gaps in the parser? No settled decision exists in the code, commits or issues. The parser follows `address` as returned today, but that is the current behavior, not a recorded choice. The nearest precedent cuts both ways. In #282 the maintainer suggested correcting the OpenStreetMap tagging upstream, but #285 also changed the parser to handle the case. Snuffy2/places#299 (unmerged) documents how to diagnose these rank ties without deciding the policy.
