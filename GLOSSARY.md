# Places

Turns the coordinates of a tracked entity into a human-readable description of where it is, using reverse geocoding.

## Language

**Place**:
The real-world location a tracked entity is at, as resolved by reverse geocoding: its address, point of interest, and zone.
_Avoid_: location, spot

**Places entry**:
One configured instance of the integration, which follows a single tracked entity and exposes its Place through a main sensor and child sensors.
_Avoid_: places sensor, instance, tracker

**POI name**:
The OpenStreetMap name of the point of interest at a Place, such as a shop or park.
_Avoid_: place name, name

## Sensors

**Main sensor**:
The primary sensor of a Places entry, whose state is the Place text built from its Display options.
_Avoid_: places sensor, parent sensor

**Child sensor**:
A sensor of a Places entry that reports one resolved detail of the Place, such as the city or a map link. Some are disabled by default.
_Avoid_: attribute sensor, sub-sensor

**Extended data**:
The opt-in raw OpenStreetMap and Wikidata details for a Place, kept for diagnostics and advanced use.
_Avoid_: extended attributes, raw data

## Updating

**Update**:
Re-resolving a Place from the tracked entity's current coordinates. A Places entry shows when it last did this.
_Avoid_: refresh, lookup, geocode

**Force update**:
An Update that bypasses the cache and does not clear the data already stored for the Places entry.
_Avoid_: forced refresh, reset

## Display

**Display options**:
The plain comma-separated list of fields that makes up the text a Places entry shows for its Place.
_Avoid_: display settings, format

**Formatted place**:
The built-in Display option that produces a full address-style description of a Place. It cannot be combined with other fields.
_Avoid_: full address

**Advanced display options**:
A way of writing the Place text with brackets and parentheses, to fall back between fields and to include a field only under conditions, instead of using a plain list.
_Avoid_: custom format, template

## Tracking

**Tracked entity**:
The Home Assistant entity with coordinates that a Places entry follows. It can be a device tracker, person, sensor, variable, or zone.
_Avoid_: device tracker, device

**Current zone**:
The Home Assistant zone the tracked entity is in right now.
_Avoid_: zone (unqualified), device tracker zone

**Home zone**:
The reference zone that distance and direction of travel are measured against.
_Avoid_: home, home location
