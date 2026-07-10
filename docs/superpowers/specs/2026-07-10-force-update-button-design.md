# Force Update Button Design

## Goal

Add one `Force Update` button per Places config entry. Pressing it removes that entry's persisted Store snapshot and performs one fresh update without using cached responses or update timers.

## Design

- Add the Home Assistant button platform to the integration and create one diagnostic `Force Update` button for each config entry.
- Route button presses through a coordinator method so the Store removal and refresh use the coordinator's existing update lock.
- Pass a one-shot `force` flag through the coordinator, updater, and OSM client.
- A forced update bypasses the coordinator scan timer, update-criteria short-circuiting, and reads from the shared OSM/Wikidata response cache.
- A forced update does not clear or replace shared cache data, does not reset shared throttle timestamps, and does not disable request-rate throttling. Fresh successful responses may update the shared cache normally.
- After Store removal, the forced cycle persists its fresh snapshot through the existing persistence path.
- The flag exists only on the current call; all later updates use normal cache and timer behavior.

## Error Handling

- If Store removal fails, surface the button action failure and do not begin a refresh that could falsely appear to have cleared persistence.
- Existing coordinator update rollback and persistence error handling remain authoritative for refresh failures.

## Tests

- Verify the button removes only its entry's Store data and requests one forced update.
- Verify forced updates bypass scan/update criteria and cached-response reads.
- Verify forced requests retain shared cache contents and throttle behavior, and normal calls resume cache use afterward.
- Run the full pytest and prek gates.
