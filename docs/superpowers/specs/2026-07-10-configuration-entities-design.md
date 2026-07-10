# Configuration Entities Design

## Goal

Add disabled-by-default Home Assistant configuration entities for Display Options, Map Provider, and Show Last Updated. Changes persist in the existing config entry and immediately update affected sensor state without reloading the entry or querying OSM.

## Entities

- A `TextEntity` edits `CONF_DISPLAY_OPTIONS`. It uses the existing display-option validator and rejects invalid input without changing saved or runtime state.
- A `SelectEntity` edits `CONF_MAP_PROVIDER` and offers the existing `apple`, `google`, and `osm` choices.
- A `SwitchEntity` edits `CONF_SHOW_TIME`.

All three entities use `EntityCategory.CONFIG`, share the Places device, and set `entity_registry_enabled_default` to `False`.

## Update Flow

The coordinator owns one settings-update method so persistence and sensor notification are not duplicated across entity platforms. A successful change:

1. Copies `ConfigEntry.data` and replaces the selected setting.
2. Calls Home Assistant's `hass.config_entries.async_update_entry(entry, data=...)`. This is the supported API that persists config-entry data across Home Assistant restarts; integration code must not edit `.storage` directly.
3. Updates the coordinator's runtime configuration and matching attributes.
4. Recalculates only affected state from existing coordinator data.
5. Publishes one coordinator snapshot and persists the runtime snapshot.

Display Options reuses `process_display_options()`. Map Provider reuses the existing map-link builder and does not make a network request. Show Last Updated removes an existing `since` suffix when disabled and applies the current local time using existing formatting behavior when enabled.

## Structure

- Add the three native Home Assistant platforms to `PLATFORMS`.
- Keep platform classes thin: expose the current value and delegate writes to the coordinator.
- Move or expose only the minimum existing map-link and last-updated rendering behavior needed by the coordinator; do not duplicate URL or suffix formatting.
- Add English entity translations for stable names.

## Error Handling

Invalid Display Options raise a Home Assistant validation error and leave both `ConfigEntry.data` and coordinator state unchanged. Select choices are constrained by the entity platform. Persistence or recalculation failures propagate rather than reporting a successful change.

## Tests

Use test-first coverage for:

- platform setup, disabled/config metadata, current values, and write delegation;
- successful config-entry persistence for each setting;
- invalid Display Options leaving state unchanged;
- local display-state, map-link, and last-updated recalculation;
- a single coordinator notification and no refresh/network request.

Run the full pytest suite and all `prek` hooks after targeted tests pass.
