# Places Architecture Cleanup Design

## Goal

Create a behavior-preserving cleanup branch for the Places Home Assistant integration that improves maintainability, correctness confidence, and local performance characteristics without changing the public integration contract.

The branch must preserve user-facing behavior, config semantics, event payload shape, persisted JSON compatibility, entity names, state strings, OSM request semantics, update throttling, and cache behavior. Existing tests and README-documented behavior are the contract. Where behavior is unclear and untested, add characterization tests before refactoring.

## Recommended Approach

Use a larger architectural extraction, but keep each extraction behind compatibility-preserving adapters until the old call sites can be migrated safely.

This approach accepts more structural change than a mechanical cleanup, because the current code concentrates too much behavior in long mutable pipelines. The key constraint is that structure may change, but observable behavior must not.

## Proposed Components

### PlacesAttributes

Extract the mutable sensor attribute mechanics from `Places`.

Responsibilities:

- Store the internal attribute mapping.
- Provide `get`, `set`, `clear`, blank checks, and safe string/float/list/dict conversions.
- Own cleanup of blank values while preserving the current zero-is-not-blank behavior.
- Own JSON import/export filtering and rollback snapshots.
- Read old persisted JSON dictionaries without changing the file format.

`Places` should initially keep its existing public helper methods and delegate them to `PlacesAttributes`. This keeps the first extraction low-risk and avoids a broad call-site rewrite.

### TrackerSnapshot

Extract tracked-entity reads and validation from repeated `hass.states.get(...)` calls.

Responsibilities:

- Capture tracker entity ID, state, zone, friendly zone name, coordinates, GPS accuracy, entity picture, and availability.
- Represent validation results for missing tracker, unknown/unavailable tracker, missing coordinates, invalid coordinates, and GPS accuracy skip behavior.
- Avoid repeated Home Assistant state lookups within one update attempt.

This object should not change how invalid trackers are logged or when an update proceeds.

### LocationSnapshot

Extract coordinate formatting and distance calculations.

Responsibilities:

- Represent current, previous, and home coordinates.
- Produce current, previous, and home location strings in the current format.
- Calculate distance from home, distance traveled, and direction of travel.
- Preserve identical-coordinate and less-than-10-meter skip behavior.

### PlacesUpdatePipeline

Replace most of the procedural sprawl in `PlacesUpdater` with a clearer coordinator.

The pipeline must preserve the current update order:

1. Synchronize renamed entity state back to the config entry.
2. Capture previous rendered state.
3. Capture old coordinates.
4. Validate tracker and refresh coordinates.
5. Load zone details.
6. Calculate distance and movement criteria.
7. Reset transient attributes.
8. Build map link.
9. Query OSM.
10. Parse OSM response.
11. Render display state.
12. Decide whether the sensor state should update.
13. Fire event data.
14. Persist JSON.
15. Roll back and apply skipped-update adjustments when criteria fail.

The old `do_update` method should remain as the public entry point during the transition.

### OSMClient

Extract external JSON fetching and URL construction from the updater.

Responsibilities:

- Build Nominatim reverse lookup URLs.
- Build Nominatim details lookup URLs.
- Build Wikidata entity-data URLs.
- Preserve existing query parameters, user agent, timeout, cache keys, cache lifetime, throttle interval, and list-response flattening behavior.
- Handle invalid JSON, timeout/client errors, `error_message`, and empty responses as the current code does.

This should make network behavior independently testable without changing the integration's external requests.

### Display Rendering

Keep `BasicOptionsParser` and `AdvancedOptionsParser` behavior, but separate parsing/token work from sensor attribute reads where practical.

This is one of the riskiest areas. It should be refactored late, after characterization tests cover README examples, bracket fallback behavior, include/exclude filters, nested filters, street-number joining, zone display behavior, `place`, and `formatted_place`.

The cleanup target is parser clarity, not new display features.

### Config And Options Flow Helpers

Extract duplicated config/options schema construction and selector list building.

Responsibilities:

- Preserve form fields, defaults, suggested values, selector modes, custom-value behavior, validation error keys, options update behavior, and reload behavior.
- Reduce repeated state lookup and repeated schema construction logic.
- Keep config entry data shape unchanged.

## Phasing

### Phase 1: Characterization Tests

Add or tighten tests around current behavior before moving production code.

Priority coverage:

- Attribute blank semantics, zero handling, safe conversions, cleanup, snapshot/restore, and JSON filtering.
- Tracker missing/unavailable/unknown states, invalid coordinates, GPS accuracy `0`, absent GPS accuracy, entity picture extraction, and zone-backed trackers.
- Current/previous/home coordinate strings, distance fields, travel direction, less-than-10-meter skip, and identical-coordinate stationary handling.
- OSM cache hits, throttled requests, timeout/client errors, invalid JSON, list response flattening, `error_message`, user-agent, and URL parameters.
- OSM parser name precedence, language-specific name, address hierarchy, `state_abbr`, city cleanup, highway `street_ref`, duplicate place-name suppression, and `last_place_name` preservation.
- Display rendering for README examples, `place`, `formatted_place`, bracket fallback, nested fallback, include/exclude filters, and attribute-scoped filters.
- Final update behavior: rollback, state truncation, `show_time` suffix, date rollover, event payloads, JSON persistence, and extended attributes.

### Phase 2: Attribute, Tracker, And Location Extraction

Introduce `PlacesAttributes`, `TrackerSnapshot`, and `LocationSnapshot`.

Keep existing public methods on `Places` while migrating internals behind them. End this phase with full test coverage passing before touching OSM or display parsing.

### Phase 3: Update Pipeline Extraction

Break `PlacesUpdater` into smaller collaborators while preserving `do_update` order and observable behavior.

The phase is complete only when rollback behavior, skipped update behavior, event firing, and JSON persistence match the characterization tests.

### Phase 4: OSM Client And Parser Extraction

Move URL construction, throttling, cache handling, request execution, JSON parsing, and response normalization into `OSMClient`.

Keep `OSMParser` focused on translating OSM dictionaries into Places attributes. Do not change parsed field names or precedence rules.

### Phase 5: Display Parser Cleanup

Refactor display rendering after tests pin current behavior.

Focus on making the grammar and rendering steps easier to understand. Do not add display options, change separators, change case formatting, or alter fallback semantics.

### Phase 6: Config Flow Cleanup

Extract schema builders, selector builders, and validation helpers after config-flow and options-flow tests cover current defaults and update behavior.

### Phase 7: Final Polish

Run full verification, review coverage and complexity, and update contributor documentation only if the module layout changes in a way maintainers need to know.

## Non-Goals

- No config migration.
- No new user-facing options.
- No entity ID changes.
- No event type or event payload schema changes.
- No persisted JSON format change.
- No OSM provider behavior change.
- No throttling, cache lifetime, or cache key changes.
- No display string behavior changes.
- No broad rewrite that removes compatibility adapters before tests prove equivalence.

## Review Gates

Each phase should be a reviewable commit or small commit group.

Required gates:

1. Characterization tests pass before structural extraction begins.
2. Attribute, tracker, and location extraction passes the full test suite before OSM or display parsing changes.
3. OSM client/parser extraction passes the full test suite before display rendering changes.
4. Display rendering extraction passes the full test suite before config-flow cleanup.
5. Final branch passes the full test suite and `prek`.

## Verification

Use the repository-local virtual environment for verification:

```bash
./.venv/bin/python -m pytest
./.venv/bin/python -m prek run -a
```

Targeted tests are acceptable while developing a phase. Phase completion requires the full test suite. The final branch requires both full `pytest` and full `prek`.

## Acceptance Criteria

- The integration's Home Assistant-facing behavior is unchanged.
- Persisted JSON from previous versions still imports.
- README-documented display examples still render the same.
- Current event payload keys and values are preserved.
- OSM request URLs, headers, timeout, throttling, and cache behavior are preserved.
- Core files are smaller or more focused, especially `sensor.py`, `update_sensor.py`, and parser modules.
- Tests cover the behavior that was moved before each major extraction.

## Regression note: README display contract

The README advanced `place` expression example is not equivalent to current runtime `place` output in existing behavior; this is a pre-existing mismatch already captured by characterizing tests. This branch keeps behavior unchanged and does not alter display rendering.
The preserved contract remains the README-backed `formatted_place` equivalence, which is verified by tests.
