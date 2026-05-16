# Places Architecture Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Places integration into clearer internal components while preserving all Home Assistant-facing behavior.

**Architecture:** Keep `Places` and `PlacesUpdater` as compatibility entry points while extracting attribute storage, tracker snapshots, location calculations, OSM I/O, display rendering seams, and config-flow helpers behind them. Each phase starts with characterization tests and ends with full repo verification so behavior drift is caught before the next extraction.

**Tech Stack:** Home Assistant custom integration, Python 3.14, pytest, pytest-homeassistant-custom-component, aiohttp, cachetools, prek, ruff, mypy.

---

## File Structure

Create these production files:

- `custom_components/places/attributes.py`: `PlacesAttributes`, the internal attribute-map wrapper used by `Places`.
- `custom_components/places/tracker.py`: `TrackerSnapshot`, `TrackerStatus`, and helper functions for reading tracked Home Assistant state.
- `custom_components/places/location.py`: coordinate snapshots, location strings, distance calculation, and travel-direction classification.
- `custom_components/places/osm_client.py`: OSM/Wikidata URL builders, cache/throttle-aware JSON fetch, and response normalization.
- `custom_components/places/pipeline.py`: the extracted update coordinator used by `PlacesUpdater`.
- `custom_components/places/config_schema.py`: selector-list and schema-builder helpers for config and options flows.

Modify these production files:

- `custom_components/places/sensor.py`: delegate attribute mechanics to `PlacesAttributes`, keep public helper methods, and eventually use the extracted pipeline.
- `custom_components/places/update_sensor.py`: keep `PlacesUpdater` as the compatibility facade while moving responsibilities into `pipeline.py`, `tracker.py`, `location.py`, and `osm_client.py`.
- `custom_components/places/parse_osm.py`: keep OSM dictionary parsing behavior but reduce coupling to updater network code.
- `custom_components/places/basic_options.py`: preserve display behavior while tightening renderer inputs.
- `custom_components/places/advanced_options.py`: preserve advanced grammar behavior while isolating token parsing where practical.
- `custom_components/places/config_flow.py`: delegate schema and selector construction to `config_schema.py`.

Create or expand these test files:

- `tests/test_attributes.py`: tests for `PlacesAttributes`.
- `tests/test_tracker.py`: tests for tracker snapshot creation and validation.
- `tests/test_location.py`: tests for coordinate strings, distance, and travel direction.
- `tests/test_osm_client.py`: tests for URL builders, cache/throttle behavior, network response handling.
- `tests/test_pipeline.py`: tests for phase ordering and compatibility facade behavior.
- Existing files: add shared fixtures to `tests/conftest.py` and characterization cases to `tests/test_sensor.py`, `tests/test_update_sensor.py`, `tests/test_parse_osm.py`, `tests/test_basic_options.py`, `tests/test_advanced_options.py`, `tests/test_config_flow.py`, and `tests/test_display_options_integration.py`.

Use these commands throughout:

```bash
./.venv/bin/python -m pytest
./.venv/bin/python -m prek run -a
```

If `.venv` does not exist, create it and install the repo's dev dependencies:

```bash
./.venv/bin/python --version || python3.14 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ".[dev]"
```

## Task 1: Attribute Characterization Tests

**Files:**
- Create: `tests/test_attributes.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_attributes.py`

- [ ] **Step 1: Add shared real `Places` and config-entry fixtures**

Append these fixtures to `tests/conftest.py` so new test modules can instantiate the real entity and updater without depending on fixtures local to `tests/test_sensor.py` or `tests/test_update_sensor.py`:

```python
@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Provide a default Places config entry for unit tests."""
    return MockConfigEntry(domain="places", data={"name": "Test Place"})


@pytest.fixture
def places_instance(
    mock_hass: MagicMock,
    patch_entity_registry: object,
    mock_config_entry: MockConfigEntry,
) -> Places:
    """Provide a real Places sensor instance with minimal configuration."""
    from custom_components.places.sensor import Places

    _ = patch_entity_registry
    config = {"devicetracker_id": "device_tracker.test"}
    return Places(
        mock_hass,
        config,
        mock_config_entry,
        "TestSensor",
        "unique123",
        {},
    )
```

Add this import near the other imports in `tests/conftest.py`:

```python
from custom_components.places.sensor import Places
```

- [ ] **Step 2: Write characterization tests for current attribute semantics**

Create `tests/test_attributes.py` with tests that initially target the current `Places` helper methods. These tests become the contract for `PlacesAttributes`.

```python
"""Tests for Places attribute storage compatibility."""

from collections.abc import MutableMapping

from homeassistant.const import CONF_NAME

from custom_components.places.const import (
    ATTR_INITIAL_UPDATE,
    ATTR_NATIVE_VALUE,
    ATTR_PLACE_NAME,
)


def test_places_attribute_blank_semantics(places_instance) -> None:
    """Blank checks preserve the current falsey-value behavior."""
    places_instance.clear_attr("missing")
    places_instance.set_attr("empty_string", "")
    places_instance.set_attr("none_value", None)
    places_instance.set_attr("zero_value", 0)
    places_instance.set_attr("false_value", False)
    places_instance.set_attr("text_value", "home")

    assert places_instance.is_attr_blank("missing") is True
    assert places_instance.is_attr_blank("empty_string") is True
    assert places_instance.is_attr_blank("none_value") is True
    assert places_instance.is_attr_blank("zero_value") is False
    assert places_instance.is_attr_blank("false_value") is True
    assert places_instance.is_attr_blank("text_value") is False


def test_places_attribute_safe_conversions(places_instance) -> None:
    """Safe conversion helpers keep current fallback behavior."""
    places_instance.set_attr("int_text", "12")
    places_instance.set_attr("bad_float", object())
    places_instance.set_attr("items", ["a", "b"])
    places_instance.set_attr("not_items", "a,b")
    places_instance.set_attr("mapping", {"a": 1})
    places_instance.set_attr("not_mapping", ["a"])

    assert places_instance.get_attr_safe_str("int_text") == "12"
    assert places_instance.get_attr_safe_float("int_text") == 12.0
    assert places_instance.get_attr_safe_float("bad_float") == 0.0
    assert places_instance.get_attr_safe_list("items") == ["a", "b"]
    assert places_instance.get_attr_safe_list("not_items") == []
    assert places_instance.get_attr_safe_dict("mapping") == {"a": 1}
    assert places_instance.get_attr_safe_dict("not_mapping") == {}


def test_places_attribute_cleanup_and_restore(places_instance) -> None:
    """Cleanup removes blank values and restore replaces the whole mapping."""
    places_instance.set_attr("keep_zero", 0)
    places_instance.set_attr("remove_empty", "")
    places_instance.set_attr("remove_none", None)
    places_instance.set_attr(ATTR_PLACE_NAME, "Library")

    places_instance.cleanup_attributes()

    attrs = places_instance.get_internal_attr()
    assert attrs[CONF_NAME] == "TestSensor"
    assert attrs["keep_zero"] == 0
    assert attrs[ATTR_INITIAL_UPDATE] is False
    assert attrs[ATTR_PLACE_NAME] == "Library"
    assert "remove_empty" not in attrs
    assert "remove_none" not in attrs


async def test_places_attribute_restore_previous_attr(places_instance) -> None:
    """Rollback restores the exact previous mapping object content."""
    previous: MutableMapping[str, object] = {
        CONF_NAME: "Restored",
        ATTR_NATIVE_VALUE: "Old State",
    }

    await places_instance.restore_previous_attr(previous)

    assert places_instance.get_internal_attr() == previous
```

- [ ] **Step 3: Run the characterization tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_attributes.py -v
```

Expected: tests pass against the existing `Places` implementation.

- [ ] **Step 4: Commit the characterization tests**

```bash
git add tests/conftest.py tests/test_attributes.py
git commit -m "test: characterize places attribute semantics"
```

## Task 2: Extract PlacesAttributes Behind Places

**Files:**
- Create: `custom_components/places/attributes.py`
- Modify: `custom_components/places/sensor.py`
- Test: `tests/test_attributes.py`, `tests/test_sensor.py`

- [ ] **Step 1: Add `PlacesAttributes`**

Create `custom_components/places/attributes.py`:

```python
"""Attribute storage helpers for Places sensors."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, SupportsFloat, SupportsIndex, TypeVar

from .const import (
    CONFIG_ATTRIBUTES_LIST,
    JSON_ATTRIBUTE_LIST,
    JSON_IGNORE_ATTRIBUTE_LIST,
)

_AttrT = TypeVar("_AttrT", default=Any)


class PlacesAttributes:
    """Manage mutable Places sensor attributes and compatibility helpers."""

    def __init__(self) -> None:
        """Initialize an empty attribute store."""
        self._attrs: MutableMapping[str, Any] = {}

    @property
    def data(self) -> MutableMapping[str, Any]:
        """Return the mutable backing attribute mapping."""
        return self._attrs

    @data.setter
    def data(self, value: MutableMapping[str, Any]) -> None:
        """Replace the backing attribute mapping for rollback compatibility."""
        self._attrs = value

    def set(self, attr: str, value: object | None = None) -> None:
        """Store an attribute value."""
        if attr:
            self._attrs[attr] = value

    def clear(self, attr: str) -> None:
        """Remove an attribute if present."""
        self._attrs.pop(attr, None)

    def is_blank(self, attr: str) -> bool:
        """Return whether an attribute is blank using existing Places semantics."""
        if self._attrs.get(attr) or self._attrs.get(attr) == 0:
            return False
        return True

    def get(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Return an attribute value with existing blank/default behavior."""
        if attr is None or (default is None and self.is_blank(attr)):
            return None
        return self._attrs.get(attr, default)

    def safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Return an attribute as a string, or an empty string on conversion failure."""
        value = self.get(attr) if default is None else self.get(attr, default)
        if value is None:
            return ""
        try:
            return str(value)
        except (ValueError, TypeError):
            return ""

    def safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Return an attribute as a float, or ``0.0`` when conversion fails."""
        value: object | None = self.get(attr) if default is None else self.get(attr, default)
        if value is None:
            return 0.0
        if not isinstance(value, str | bytes | bytearray | SupportsFloat | SupportsIndex):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def safe_list(self, attr: str | None, default: object | None = None) -> list:
        """Return an attribute as a list, or an empty list for non-list values."""
        value: object | None = self.get(attr) if default is None else self.get(attr, default)
        if not isinstance(value, list):
            return []
        return value

    def safe_dict(
        self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
    ) -> MutableMapping[str, _AttrT]:
        """Return an attribute as a mutable mapping, or an empty mapping."""
        value = self.get(attr) if default is None else self.get(attr, default)
        if not isinstance(value, MutableMapping):
            return {}
        return value

    def cleanup(self) -> None:
        """Remove blank attributes from the backing mapping."""
        for attr in list(self._attrs):
            if self.is_blank(attr):
                self.clear(attr)

    def import_json_attributes(self, json_attr: MutableMapping[str, Any]) -> None:
        """Import persisted JSON attributes using the existing allow/ignore lists."""
        for attr in JSON_ATTRIBUTE_LIST:
            if attr in json_attr:
                self.set(attr, json_attr.pop(attr, None))

        for attr in CONFIG_ATTRIBUTES_LIST + JSON_IGNORE_ATTRIBUTE_LIST:
            json_attr.pop(attr, None)
```

- [ ] **Step 2: Delegate `Places` attribute helpers to `PlacesAttributes`**

Modify `custom_components/places/sensor.py` imports:

```python
from .attributes import PlacesAttributes
```

In `Places.__init__`, replace:

```python
self._internal_attr: MutableMapping[str, Any] = {}
```

with:

```python
self._attributes = PlacesAttributes()
self._internal_attr = self._attributes.data
```

Replace the helper method bodies with delegations:

```python
def get_internal_attr(self) -> MutableMapping[str, Any]:
    """Return the mutable attribute store used for state and persistence."""
    return self._attributes.data

def cleanup_attributes(self) -> None:
    """Remove blank attributes from the internal attribute mapping."""
    self._attributes.cleanup()

def is_attr_blank(self, attr: str) -> bool:
    """Return whether an internal attribute is absent or falsey except zero."""
    return self._attributes.is_blank(attr)

def get_attr(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
    """Read an internal attribute with optional default handling."""
    return self._attributes.get(attr, default)

def get_attr_safe_str(self, attr: str | None, default: object | None = None) -> str:
    """Read an internal attribute as text without propagating conversion errors."""
    return self._attributes.safe_str(attr, default)

def get_attr_safe_float(self, attr: str | None, default: object | None = None) -> float:
    """Read an internal attribute as a float."""
    return self._attributes.safe_float(attr, default)

def get_attr_safe_list(self, attr: str | None, default: object | None = None) -> list:
    """Read an internal attribute as a list."""
    return self._attributes.safe_list(attr, default)

def get_attr_safe_dict(
    self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
) -> MutableMapping[str, _AttrT]:
    """Read an internal attribute as a mutable mapping."""
    return self._attributes.safe_dict(attr, default)

def set_attr(self, attr: str, value: object | None = None) -> None:
    """Store a value in the internal attribute mapping."""
    self._attributes.set(attr, value)

def clear_attr(self, attr: str) -> None:
    """Remove an internal attribute if present."""
    self._attributes.clear(attr)

async def restore_previous_attr(self, previous_attr: MutableMapping[str, Any]) -> None:
    """Replace current attributes with a previous snapshot after rollback."""
    self._attributes.data = previous_attr
    self._internal_attr = self._attributes.data
```

In `import_attributes_from_json`, replace the import loops with:

```python
self.set_attr(ATTR_INITIAL_UPDATE, False)
self._attributes.import_json_attributes(json_attr)
if not self.is_attr_blank(ATTR_NATIVE_VALUE):
    self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)
if json_attr is not None and json_attr:
    _LOGGER.debug(
        "(%s) [import_attributes] Attributes not imported: %s",
        self.get_attr(CONF_NAME),
        json_attr,
    )
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_attributes.py tests/test_sensor.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run full tests**

Run:

```bash
./.venv/bin/python -m pytest
```

Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/attributes.py custom_components/places/sensor.py tests/test_attributes.py
git commit -m "refactor: extract places attribute store"
```

## Task 3: Characterize Tracker And Location Behavior

**Files:**
- Create: `tests/test_tracker.py`
- Create: `tests/test_location.py`
- Modify: `tests/test_update_sensor.py`
- Test: `tests/test_tracker.py`, `tests/test_location.py`, `tests/test_update_sensor.py`

- [ ] **Step 1: Add tracker behavior tests against current updater methods**

Create `tests/test_tracker.py`:

```python
"""Characterization tests for tracked entity handling."""

from unittest.mock import MagicMock

from homeassistant.const import ATTR_GPS_ACCURACY, CONF_LATITUDE, CONF_LONGITUDE

from custom_components.places.const import (
    ATTR_GPS_ACCURACY as PLACES_GPS_ACCURACY,
    CONF_DEVICETRACKER_ID,
    CONF_USE_GPS,
    UpdateStatus,
)
from custom_components.places.update_sensor import PlacesUpdater


async def test_tracker_missing_skips_update(mock_hass: MagicMock, mock_config_entry, sensor) -> None:
    """Missing tracked entities skip update without coordinates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.missing"
    mock_hass.states.get.return_value = None
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.is_devicetracker_set()

    assert result is UpdateStatus.SKIP


async def test_tracker_invalid_coordinates_skip_update(
    mock_hass: MagicMock, mock_config_entry, sensor
) -> None:
    """Non-numeric coordinates skip updates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: "north", CONF_LONGITUDE: "-70.0"}
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.has_valid_coordinates()

    assert result is False


async def test_tracker_zero_gps_accuracy_skips_when_enabled(
    mock_hass: MagicMock, mock_config_entry, sensor
) -> None:
    """GPS accuracy zero preserves the existing skip behavior."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    sensor.attrs[CONF_USE_GPS] = True
    tracker = MagicMock()
    tracker.attributes = {ATTR_GPS_ACCURACY: 0}
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.get_gps_accuracy()

    assert result is UpdateStatus.SKIP
    assert sensor.attrs[PLACES_GPS_ACCURACY] == 0.0
```

- [ ] **Step 2: Add location behavior tests against current updater methods**

Create `tests/test_location.py`:

```python
"""Characterization tests for Places location calculations."""

from custom_components.places.const import (
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LOCATION_CURRENT,
    ATTR_LOCATION_PREVIOUS,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
)
from custom_components.places.update_sensor import PlacesUpdater


async def test_location_strings_are_current_format(mock_hass, mock_config_entry, sensor) -> None:
    """Location string formatting stays compatible."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.1,
            ATTR_LONGITUDE: -70.2,
            ATTR_LATITUDE_OLD: 40.0,
            ATTR_LONGITUDE_OLD: -70.0,
            ATTR_HOME_LATITUDE: 39.9,
            ATTR_HOME_LONGITUDE: -69.9,
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.update_location_attributes()

    assert sensor.attrs[ATTR_LOCATION_CURRENT] == "40.1,-70.2"
    assert sensor.attrs[ATTR_LOCATION_PREVIOUS] == "40.0,-70.0"
    assert sensor.attrs[ATTR_HOME_LOCATION] == "39.9,-69.9"


async def test_distance_fields_are_populated(mock_hass, mock_config_entry, sensor) -> None:
    """Distance calculations populate meters, kilometers, and miles."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.1,
            ATTR_LONGITUDE: -70.2,
            ATTR_HOME_LATITUDE: 40.0,
            ATTR_HOME_LONGITUDE: -70.0,
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.calculate_distances()

    assert sensor.attrs[ATTR_DISTANCE_FROM_HOME_M] > 0
    assert sensor.attrs[ATTR_DISTANCE_FROM_HOME_KM] > 0
    assert sensor.attrs[ATTR_DISTANCE_FROM_HOME_MI] > 0


async def test_direction_of_travel_stationary_when_distance_unchanged(
    mock_hass, mock_config_entry, sensor
) -> None:
    """Direction remains stationary when distance from home is unchanged."""
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = 1.0
    sensor.attrs[ATTR_DISTANCE_FROM_HOME_M] = 100.0
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.determine_direction_of_travel(last_distance_traveled_m=100.0)

    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"
```

- [ ] **Step 3: Run new characterization tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_tracker.py tests/test_location.py -v
```

Expected: all tests pass against current code.

- [ ] **Step 4: Commit**

```bash
git add tests/test_tracker.py tests/test_location.py tests/test_update_sensor.py
git commit -m "test: characterize tracker and location behavior"
```

## Task 4: Extract TrackerSnapshot And LocationSnapshot

**Files:**
- Create: `custom_components/places/tracker.py`
- Create: `custom_components/places/location.py`
- Modify: `custom_components/places/update_sensor.py`
- Test: `tests/test_tracker.py`, `tests/test_location.py`, `tests/test_update_sensor.py`

- [ ] **Step 1: Add tracker snapshot types**

Create `custom_components/places/tracker.py`:

```python
"""Tracked entity snapshots for Places updates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State

from .helpers import is_float


class TrackerStatus(Enum):
    """Validation status for a tracked entity snapshot."""

    OK = auto()
    MISSING_ENTITY_ID = auto()
    NOT_FOUND = auto()
    UNAVAILABLE = auto()
    MISSING_COORDINATES = auto()
    INVALID_COORDINATES = auto()


@dataclass(slots=True)
class TrackerSnapshot:
    """Snapshot of a tracked Home Assistant entity for one Places update."""

    entity_id: str | None
    state: State | None
    status: TrackerStatus
    latitude: float | None
    longitude: float | None
    gps_accuracy: float | None
    zone: str | None
    zone_name: str | None
    entity_picture: str | None

    @classmethod
    def from_hass(cls, hass: HomeAssistant, entity_id: str | None) -> TrackerSnapshot:
        """Build a tracker snapshot from Home Assistant state."""
        if not entity_id:
            return cls(entity_id, None, TrackerStatus.MISSING_ENTITY_ID, None, None, None, None, None, None)

        state = hass.states.get(entity_id)
        if state is None:
            return cls(entity_id, None, TrackerStatus.NOT_FOUND, None, None, None, None, None, None)

        if isinstance(state.state, str) and state.state.lower() in {
            "none",
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }:
            return cls(entity_id, state, TrackerStatus.UNAVAILABLE, None, None, None, None, None, None)

        attrs: dict[str, Any] = dict(state.attributes)
        lat = attrs.get(CONF_LATITUDE)
        lon = attrs.get(CONF_LONGITUDE)
        if lat is None or lon is None:
            status = TrackerStatus.MISSING_COORDINATES
            latitude = None
            longitude = None
        elif not is_float(lat) or not is_float(lon):
            status = TrackerStatus.INVALID_COORDINATES
            latitude = None
            longitude = None
        else:
            status = TrackerStatus.OK
            latitude = float(lat)
            longitude = float(lon)

        gps_accuracy = attrs.get(ATTR_GPS_ACCURACY)
        return cls(
            entity_id=entity_id,
            state=state,
            status=status,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy=float(gps_accuracy) if is_float(gps_accuracy) else None,
            zone=state.state,
            zone_name=attrs.get(CONF_ZONE) or attrs.get(ATTR_FRIENDLY_NAME),
            entity_picture=attrs.get("entity_picture"),
        )

    @property
    def has_valid_coordinates(self) -> bool:
        """Return whether the snapshot has usable coordinates."""
        return self.status is TrackerStatus.OK
```

- [ ] **Step 2: Add location helpers**

Create `custom_components/places/location.py`:

```python
"""Location calculations for Places updates."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.util.location import distance

from .const import METERS_PER_MILE


@dataclass(slots=True)
class CoordinatePair:
    """Latitude and longitude pair."""

    latitude: float
    longitude: float

    def as_location(self) -> str:
        """Return the current Places ``lat,lon`` string format."""
        return f"{self.latitude},{self.longitude}"


@dataclass(slots=True)
class LocationSnapshot:
    """Current, previous, and home coordinates with derived distances."""

    current: CoordinatePair | None
    previous: CoordinatePair | None
    home: CoordinatePair | None
    distance_from_home_m: float | None = None
    distance_traveled_m: float | None = None

    def calculate(self) -> None:
        """Populate distance fields from available coordinates."""
        if self.current is not None and self.home is not None:
            self.distance_from_home_m = distance(
                self.current.latitude,
                self.current.longitude,
                self.home.latitude,
                self.home.longitude,
            )
        if self.current is not None and self.previous is not None:
            self.distance_traveled_m = distance(
                self.current.latitude,
                self.current.longitude,
                self.previous.latitude,
                self.previous.longitude,
            )
        elif self.previous is None:
            self.distance_traveled_m = 0

    @property
    def distance_from_home_km(self) -> float | None:
        """Return distance from home in kilometers."""
        if self.distance_from_home_m is None:
            return None
        return round(self.distance_from_home_m / 1000, 3)

    @property
    def distance_from_home_mi(self) -> float | None:
        """Return distance from home in miles."""
        if self.distance_from_home_m is None:
            return None
        return round(self.distance_from_home_m / METERS_PER_MILE, 3)

    @property
    def distance_traveled_mi(self) -> float | None:
        """Return distance traveled in miles."""
        if self.distance_traveled_m is None:
            return None
        return round(self.distance_traveled_m / METERS_PER_MILE, 3)


def direction_of_travel(previous_distance_from_home_m: float, distance_from_home_m: float) -> str:
    """Classify travel direction using the existing string values."""
    if previous_distance_from_home_m > distance_from_home_m:
        return "towards home"
    if previous_distance_from_home_m < distance_from_home_m:
        return "away from home"
    return "stationary"
```

- [ ] **Step 3: Integrate snapshots into `PlacesUpdater` without changing public methods**

In `custom_components/places/update_sensor.py`, import:

```python
from .location import CoordinatePair, LocationSnapshot, direction_of_travel
from .tracker import TrackerSnapshot, TrackerStatus
```

Update `has_valid_coordinates` to use `TrackerSnapshot`:

```python
async def has_valid_coordinates(self) -> bool:
    """Return whether the tracked entity exposes numeric coordinates."""
    snapshot = TrackerSnapshot.from_hass(
        self._hass, self.sensor.get_attr(CONF_DEVICETRACKER_ID)
    )
    if snapshot.status in {TrackerStatus.MISSING_COORDINATES, TrackerStatus.INVALID_COORDINATES}:
        await self.log_coordinate_issue()
        return False
    return snapshot.status is TrackerStatus.OK
```

Update `update_coordinates` to use the same snapshot:

```python
async def update_coordinates(self) -> None:
    """Copy latitude and longitude from the tracked entity state."""
    tracker = TrackerSnapshot.from_hass(
        self._hass, self.sensor.get_attr(CONF_DEVICETRACKER_ID)
    )
    if tracker.status is TrackerStatus.NOT_FOUND:
        _LOGGER.warning(
            "(%s) Device tracker entity not found: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(CONF_DEVICETRACKER_ID),
        )
        return
    if tracker.latitude is not None:
        self.sensor.set_attr(ATTR_LATITUDE, tracker.latitude)
    if tracker.longitude is not None:
        self.sensor.set_attr(ATTR_LONGITUDE, tracker.longitude)
```

Replace `update_location_attributes` with a version that writes the same string values through `CoordinatePair`:

```python
async def update_location_attributes(self) -> None:
    """Store current, previous, and home coordinates as ``lat,lon`` strings."""
    current = None
    previous = None
    home = None
    if not self.sensor.is_attr_blank(ATTR_LATITUDE) and not self.sensor.is_attr_blank(ATTR_LONGITUDE):
        current = CoordinatePair(
            self.sensor.get_attr_safe_float(ATTR_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
        )
        self.sensor.set_attr(ATTR_LOCATION_CURRENT, current.as_location())
    if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(ATTR_LONGITUDE_OLD):
        previous = CoordinatePair(
            self.sensor.get_attr_safe_float(ATTR_LATITUDE_OLD),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE_OLD),
        )
        self.sensor.set_attr(ATTR_LOCATION_PREVIOUS, previous.as_location())
    if not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE) and not self.sensor.is_attr_blank(ATTR_HOME_LONGITUDE):
        home = CoordinatePair(
            self.sensor.get_attr_safe_float(ATTR_HOME_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_HOME_LONGITUDE),
        )
        self.sensor.set_attr(ATTR_HOME_LOCATION, home.as_location())
```

Replace `calculate_distances` with:

```python
async def calculate_distances(self) -> None:
    """Calculate distance from home in meters, kilometers, and miles."""
    if (
        self.sensor.is_attr_blank(ATTR_LATITUDE)
        or self.sensor.is_attr_blank(ATTR_LONGITUDE)
        or self.sensor.is_attr_blank(ATTR_HOME_LATITUDE)
        or self.sensor.is_attr_blank(ATTR_HOME_LONGITUDE)
    ):
        return
    snapshot = LocationSnapshot(
        current=CoordinatePair(
            self.sensor.get_attr_safe_float(ATTR_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
        ),
        previous=None,
        home=CoordinatePair(
            self.sensor.get_attr_safe_float(ATTR_HOME_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_HOME_LONGITUDE),
        ),
    )
    snapshot.calculate()
    if snapshot.distance_from_home_m is not None:
        self.sensor.set_attr(ATTR_DISTANCE_FROM_HOME_M, snapshot.distance_from_home_m)
        self.sensor.set_attr(ATTR_DISTANCE_FROM_HOME_KM, snapshot.distance_from_home_km)
        self.sensor.set_attr(ATTR_DISTANCE_FROM_HOME_MI, snapshot.distance_from_home_mi)
```

Replace `calculate_travel_distance` with:

```python
async def calculate_travel_distance(self) -> None:
    """Calculate distance traveled since the previous coordinates."""
    if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(ATTR_LONGITUDE_OLD):
        snapshot = LocationSnapshot(
            current=CoordinatePair(
                self.sensor.get_attr_safe_float(ATTR_LATITUDE),
                self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
            ),
            previous=CoordinatePair(
                self.sensor.get_attr_safe_float(ATTR_LATITUDE_OLD),
                self.sensor.get_attr_safe_float(ATTR_LONGITUDE_OLD),
            ),
            home=None,
        )
        snapshot.calculate()
        if snapshot.distance_traveled_m is not None:
            self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_M, snapshot.distance_traveled_m)
            self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_MI, snapshot.distance_traveled_mi)
    else:
        self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
        self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)
```

Replace `determine_direction_of_travel` with:

```python
async def determine_direction_of_travel(self, last_distance_traveled_m: float) -> None:
    """Classify movement relative to home as towards, away, or stationary."""
    if not self.sensor.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
        self.sensor.set_attr(
            ATTR_DIRECTION_OF_TRAVEL,
            direction_of_travel(
                previous_distance_from_home_m=last_distance_traveled_m,
                distance_from_home_m=self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M),
            ),
        )
    else:
        self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_tracker.py tests/test_location.py tests/test_update_sensor.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full tests and commit**

```bash
./.venv/bin/python -m pytest
git add custom_components/places/tracker.py custom_components/places/location.py custom_components/places/update_sensor.py tests/conftest.py tests/test_tracker.py tests/test_location.py
git commit -m "refactor: extract tracker and location snapshots"
```

## Task 5: Characterize OSM Client Behavior

**Files:**
- Create: `tests/test_osm_client.py`
- Modify: none
- Test: `tests/test_osm_client.py`, `tests/test_update_sensor.py`

- [ ] **Step 1: Add URL and response behavior tests against current updater**

Create `tests/test_osm_client.py`:

```python
"""Characterization tests for OSM request behavior."""

from urllib.parse import parse_qs, urlparse

from custom_components.places.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_API_KEY,
    CONF_LANGUAGE,
)
from custom_components.places.update_sensor import PlacesUpdater


async def test_reverse_osm_url_parameters(mock_hass, mock_config_entry, sensor) -> None:
    """Reverse lookup URL parameters remain stable."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.123,
            ATTR_LONGITUDE: -70.456,
            CONF_LANGUAGE: "en,fr",
            CONF_API_KEY: "person@example.com",
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    url = await updater.build_osm_url()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "nominatim.openstreetmap.org"
    assert query["format"] == ["json"]
    assert query["lat"] == ["40.123"]
    assert query["lon"] == ["-70.456"]
    assert query["accept-language"] == ["en,fr"]
    assert query["addressdetails"] == ["1"]
    assert query["namedetails"] == ["1"]
    assert query["zoom"] == ["18"]
    assert query["limit"] == ["1"]
    assert query["email"] == ["person@example.com"]
```

- [ ] **Step 2: Add cache and list-response tests if not already covered**

If `tests/test_update_sensor.py` already covers list-response flattening and throttle behavior, add only this cache-hit assertion to `tests/test_osm_client.py`:

```python
from custom_components.places.const import ATTR_OSM_DICT, DOMAIN, OSM_CACHE, OSM_THROTTLE


async def test_get_dict_from_url_uses_existing_cache(mock_hass, mock_config_entry, sensor) -> None:
    """Cached OSM responses are used without network calls."""
    url = "https://example.test/osm"
    cached = {"place_id": 123}
    mock_hass.data = {
        DOMAIN: {
            OSM_CACHE: {url: cached},
            OSM_THROTTLE: {"lock": None, "last_query": 0.0},
        }
    }
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.get_dict_from_url(url=url, name="OpenStreetMaps", dict_name=ATTR_OSM_DICT)

    assert sensor.attrs[ATTR_OSM_DICT] == cached
```

- [ ] **Step 3: Run OSM characterization tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_osm_client.py tests/test_update_sensor.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_osm_client.py tests/test_update_sensor.py
git commit -m "test: characterize osm client behavior"
```

## Task 6: Extract OSMClient

**Files:**
- Create: `custom_components/places/osm_client.py`
- Modify: `custom_components/places/update_sensor.py`
- Test: `tests/test_osm_client.py`, `tests/test_update_sensor.py`

- [ ] **Step 1: Add `OSMClient`**

Create `custom_components/places/osm_client.py`:

```python
"""OSM and Wikidata HTTP client helpers for Places."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
import json
import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp
from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    OSM_CACHE,
    OSM_THROTTLE,
    OSM_THROTTLE_INTERVAL_SECONDS,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)


class OSMClient:
    """Fetch and cache OSM/Wikidata JSON using Places throttling rules."""

    def __init__(self, hass: HomeAssistant, sensor_name: str) -> None:
        """Initialize the client for a Home Assistant instance."""
        self._hass = hass
        self._sensor_name = sensor_name

    @staticmethod
    def reverse_url(
        *,
        latitude: float,
        longitude: float,
        language: str,
        email: str,
    ) -> str:
        """Build the existing Nominatim reverse lookup URL."""
        base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
        params = {
            "lat": latitude,
            "lon": longitude,
            "accept-language": language,
            "addressdetails": "1",
            "namedetails": "1",
            "zoom": "18",
            "limit": "1",
            "email": email,
        }
        return f"{base_url}&{urlencode(params)}"

    @staticmethod
    def details_url(
        *,
        osm_type_abbr: str,
        osm_id: object,
        language: str,
        email: str,
    ) -> str:
        """Build the existing Nominatim details lookup URL."""
        params = {
            "osm_ids": f"{osm_type_abbr}{osm_id}",
            "format": "json",
            "addressdetails": "1",
            "extratags": "1",
            "namedetails": "1",
            "email": email,
            "accept-language": language,
        }
        return f"https://nominatim.openstreetmap.org/lookup?{urlencode(params)}"

    @staticmethod
    def wikidata_url(wikidata_id: object) -> str:
        """Build the existing Wikidata entity-data URL."""
        return f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"

    async def get_json(self, url: str, name: str) -> MutableMapping[str, Any] | None:
        """Fetch a JSON mapping with existing cache, throttle, and error behavior."""
        osm_cache = self._hass.data[DOMAIN][OSM_CACHE]
        if url in osm_cache:
            _LOGGER.debug("(%s) %s data loaded from cache (Cache size: %s)", self._sensor_name, name, len(osm_cache))
            return osm_cache[url]

        throttle = self._hass.data[DOMAIN][OSM_THROTTLE]
        async with throttle["lock"]:
            now = asyncio.get_running_loop().time()
            wait_time = max(0, OSM_THROTTLE_INTERVAL_SECONDS - (now - throttle["last_query"]))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            throttle["last_query"] = asyncio.get_running_loop().time()

            headers = {
                "user-agent": (
                    f"Mozilla/5.0 (Home Assistant/{ha_version}) "
                    f"{DOMAIN}/{VERSION} (+https://github.com/custom-components/places)"
                )
            }
            try:
                session = async_get_clientsession(self._hass)
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    payload = await response.text()
                    try:
                        decoded = json.loads(payload)
                    except json.decoder.JSONDecodeError as err:
                        _LOGGER.warning(
                            "(%s) JSON Decode Error with %s info [%s: %s]: %s",
                            self._sensor_name,
                            name,
                            type(err).__name__,
                            err,
                            payload,
                        )
                        return None
            except (TimeoutError, aiohttp.ClientError, aiohttp.ContentTypeError, OSError, RuntimeError) as err:
                _LOGGER.warning(
                    "(%s) Error connecting to %s [%s: %s]: %s",
                    self._sensor_name,
                    name,
                    type(err).__name__,
                    err,
                    url,
                )
                return None

        if isinstance(decoded, MutableMapping) and "error_message" in decoded:
            _LOGGER.warning(
                "(%s) An error occurred contacting the web service for %s: %s",
                self._sensor_name,
                name,
                decoded.get("error_message"),
            )
            return None

        if isinstance(decoded, list) and len(decoded) == 1 and isinstance(decoded[0], MutableMapping):
            osm_cache[url] = decoded[0]
            return decoded[0]

        if isinstance(decoded, MutableMapping):
            osm_cache[url] = decoded
            return decoded

        return None
```

- [ ] **Step 2: Delegate updater URL and fetch methods to `OSMClient`**

In `custom_components/places/update_sensor.py`, import:

```python
from .osm_client import OSMClient
```

In `PlacesUpdater.__init__`, add:

```python
self._osm_client = OSMClient(hass=hass, sensor_name=str(sensor.get_attr(CONF_NAME)))
```

Replace `build_osm_url` body:

```python
return OSMClient.reverse_url(
    latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE),
    longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
    language=self.sensor.get_attr_safe_str(CONF_LANGUAGE),
    email=self.sensor.get_attr_safe_str(CONF_API_KEY),
)
```

Replace `get_dict_from_url` body:

```python
result = await self._osm_client.get_json(url=url, name=name)
self.sensor.set_attr(dict_name, result or {})
```

When replacing details and Wikidata URL construction in `get_extended_attr`, call:

```python
osm_details_url = OSMClient.details_url(
    osm_type_abbr=osm_type_abbr,
    osm_id=self.sensor.get_attr(ATTR_OSM_ID),
    language=self.sensor.get_attr_safe_str(CONF_LANGUAGE),
    email=self.sensor.get_attr_safe_str(CONF_API_KEY),
)
wikidata_url = OSMClient.wikidata_url(self.sensor.get_attr(ATTR_WIKIDATA_ID))
```

- [ ] **Step 3: Remove unused imports from `update_sensor.py`**

After delegation, remove imports that are no longer used in `update_sensor.py`:

```python
import asyncio
import json
from urllib.parse import urlencode
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.const import __version__ as ha_version
```

Keep imports that are still used by map-link generation or other methods.

- [ ] **Step 4: Run focused and full tests**

```bash
./.venv/bin/python -m pytest tests/test_osm_client.py tests/test_update_sensor.py -v
./.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/osm_client.py custom_components/places/update_sensor.py tests/test_osm_client.py tests/test_update_sensor.py
git commit -m "refactor: extract osm client"
```

## Task 7: Tighten OSM Parser Internals

**Files:**
- Modify: `custom_components/places/parse_osm.py`
- Modify: `tests/test_parse_osm.py`
- Test: `tests/test_parse_osm.py`, `tests/test_update_sensor.py`

- [ ] **Step 1: Add parser regression tests for address lookup compatibility**

Add this test to `tests/test_parse_osm.py`:

```python
async def test_parse_miscellaneous_osm_id_and_postcode_use_current_osm_dict(sensor) -> None:
    """Parser keeps using the current OSM dictionary for derived fields."""
    from custom_components.places.const import (
        ATTR_OSM_DICT,
        ATTR_OSM_ID,
        ATTR_POSTAL_CODE,
    )
    from custom_components.places.parse_osm import OSMParser

    sensor.attrs[ATTR_OSM_DICT] = {
        "osm_id": 12345,
        "osm_type": "way",
        "address": {"postcode": "07024"},
    }
    parser = OSMParser(sensor)

    await parser.set_region_details(sensor.attrs[ATTR_OSM_DICT]["address"])
    await parser.parse_miscellaneous(sensor.attrs[ATTR_OSM_DICT])

    assert sensor.attrs[ATTR_OSM_ID] == "12345"
    assert sensor.attrs[ATTR_POSTAL_CODE] == "07024"
```

- [ ] **Step 2: Add private OSM dictionary helper methods**

In `custom_components/places/parse_osm.py`, add these methods to `OSMParser` after `__init__`:

```python
def current_osm_dict(self) -> MutableMapping[str, Any]:
    """Return the current OSM response mapping from sensor attributes."""
    return self.sensor.get_attr_safe_dict(ATTR_OSM_DICT)

def current_address(self) -> MutableMapping[str, Any]:
    """Return the current OSM address mapping from sensor attributes."""
    address = self.current_osm_dict().get("address", {})
    if isinstance(address, MutableMapping):
        return address
    return {}
```

- [ ] **Step 3: Replace repeated OSM dictionary reads**

In `set_address_details`, replace:

```python
self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("retail")
```

with:

```python
self.current_address().get("retail")
```

In `set_region_details`, replace:

```python
self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("postcode")
```

with:

```python
self.current_address().get("postcode")
```

In `parse_miscellaneous`, replace:

```python
str(self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("osm_id", ""))
```

with:

```python
str(self.current_osm_dict().get("osm_id", ""))
```

- [ ] **Step 4: Run parser tests and full tests**

```bash
./.venv/bin/python -m pytest tests/test_parse_osm.py tests/test_update_sensor.py -v
./.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/parse_osm.py tests/test_parse_osm.py
git commit -m "refactor: tighten osm parser internals"
```

## Task 8: Extract Update Pipeline Facade

**Files:**
- Create: `custom_components/places/pipeline.py`
- Modify: `custom_components/places/update_sensor.py`
- Create: `tests/test_pipeline.py`
- Test: `tests/test_pipeline.py`, `tests/test_update_sensor.py`, `tests/test_sensor.py`

- [ ] **Step 1: Add pipeline class with existing update order**

Create `custom_components/places/pipeline.py`:

```python
"""Update pipeline coordinator for Places sensors."""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .const import ATTR_LAST_PLACE_NAME, UpdateStatus

if TYPE_CHECKING:
    from .update_sensor import PlacesUpdater


class PlacesUpdatePipeline:
    """Coordinate one Places update using the existing updater operations."""

    def __init__(self, updater: PlacesUpdater) -> None:
        """Initialize the pipeline with a compatibility updater facade."""
        self.updater = updater

    async def run(self, reason: str, previous_attr: MutableMapping[str, Any]) -> None:
        """Run the existing update phases in their current order."""
        sensor = self.updater.sensor
        self.updater.log_update_start(reason)

        now: datetime = await self.updater.get_current_time()
        await self.updater.update_entity_name_and_cleanup()
        await self.updater.update_previous_state()
        await self.updater.update_old_coordinates()
        prev_last_place_name = sensor.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        proceed = await self.updater.check_device_tracker_and_update_coords()
        if proceed == UpdateStatus.PROCEED:
            proceed = await self.updater.determine_update_criteria()

        if proceed == UpdateStatus.PROCEED:
            await self.updater.process_osm_update(now=now)
            if await self.updater.should_update_state(now=now):
                await self.updater.handle_state_update(
                    now=now,
                    prev_last_place_name=prev_last_place_name,
                )
            else:
                await self.updater.rollback_update(previous_attr, now, proceed)
        else:
            await self.updater.rollback_update(previous_attr, now, proceed)

        await self.updater.finish_update(now)
```

- [ ] **Step 2: Add compatibility methods on `PlacesUpdater`**

In `custom_components/places/update_sensor.py`, import:

```python
from .pipeline import PlacesUpdatePipeline
```

Add methods:

```python
def log_update_start(self, reason: str) -> None:
    """Log the start of an update."""
    _LOGGER.info(
        "(%s) Starting %s Update (Tracked Entity: %s)",
        self.sensor.get_attr(CONF_NAME),
        reason,
        self.sensor.get_attr(CONF_DEVICETRACKER_ID),
    )

async def finish_update(self, now: datetime) -> None:
    """Store update completion time and log completion."""
    self.sensor.set_attr(ATTR_LAST_UPDATED, now.isoformat(sep=" ", timespec="seconds"))
    _LOGGER.info("(%s) End of Update", self.sensor.get_attr(CONF_NAME))
```

Replace `do_update` body with:

```python
pipeline = PlacesUpdatePipeline(self)
await pipeline.run(reason=reason, previous_attr=previous_attr)
```

- [ ] **Step 3: Add pipeline order test**

Create `tests/test_pipeline.py`:

```python
"""Tests for the extracted Places update pipeline."""

from collections.abc import MutableMapping
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from custom_components.places.const import UpdateStatus
from custom_components.places.pipeline import PlacesUpdatePipeline


async def test_pipeline_runs_existing_order(sensor) -> None:
    """Pipeline preserves the existing update phase order."""
    calls: list[str] = []
    updater = MagicMock()
    updater.sensor = sensor
    sensor.attrs["last_place_name"] = "Previous"

    async def record_async(name: str, result: object = None) -> object:
        calls.append(name)
        return result

    updater.log_update_start.side_effect = lambda reason: calls.append("log_update_start")
    updater.get_current_time = AsyncMock(side_effect=lambda: record_async("get_current_time", datetime(2026, 5, 16, tzinfo=UTC)))
    updater.update_entity_name_and_cleanup = AsyncMock(side_effect=lambda: record_async("update_entity_name_and_cleanup"))
    updater.update_previous_state = AsyncMock(side_effect=lambda: record_async("update_previous_state"))
    updater.update_old_coordinates = AsyncMock(side_effect=lambda: record_async("update_old_coordinates"))
    updater.check_device_tracker_and_update_coords = AsyncMock(side_effect=lambda: record_async("check_device_tracker_and_update_coords", UpdateStatus.PROCEED))
    updater.determine_update_criteria = AsyncMock(side_effect=lambda: record_async("determine_update_criteria", UpdateStatus.PROCEED))
    updater.process_osm_update = AsyncMock(side_effect=lambda now: record_async("process_osm_update"))
    updater.should_update_state = AsyncMock(side_effect=lambda now: record_async("should_update_state", True))
    updater.handle_state_update = AsyncMock(side_effect=lambda now, prev_last_place_name: record_async("handle_state_update"))
    updater.rollback_update = AsyncMock(side_effect=lambda previous_attr, now, proceed_with_update: record_async("rollback_update"))
    updater.finish_update = AsyncMock(side_effect=lambda now: record_async("finish_update"))

    pipeline = PlacesUpdatePipeline(updater)
    previous_attr: MutableMapping[str, object] = {}

    await pipeline.run("test", previous_attr)

    assert calls == [
        "log_update_start",
        "get_current_time",
        "update_entity_name_and_cleanup",
        "update_previous_state",
        "update_old_coordinates",
        "check_device_tracker_and_update_coords",
        "determine_update_criteria",
        "process_osm_update",
        "should_update_state",
        "handle_state_update",
        "finish_update",
    ]
    updater.rollback_update.assert_not_awaited()
```

- [ ] **Step 4: Run focused and full tests**

```bash
./.venv/bin/python -m pytest tests/test_pipeline.py tests/test_update_sensor.py tests/test_sensor.py -v
./.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/pipeline.py custom_components/places/update_sensor.py tests/test_pipeline.py tests/test_update_sensor.py tests/test_sensor.py
git commit -m "refactor: extract update pipeline coordinator"
```

## Task 9: Characterize README Display Examples

**Files:**
- Modify: `tests/test_display_options_integration.py`
- Test: `tests/test_display_options_integration.py`, `tests/test_basic_options.py`, `tests/test_advanced_options.py`

- [ ] **Step 1: Add README advanced display examples as fixtures**

In `tests/test_display_options_integration.py`, add constants:

```python
README_PLACE_ADVANCED = (
    "name_no_dupe, category(-, place), type(-, yes), neighborhood, house_number, street"
)

README_FORMATTED_PLACE_ADVANCED = (
    "zone_name[driving, name_no_dupe[type(-, unclassified, category(-, highway))"
    "[category(-, highway)], house_number, route_number(type(+, motorway, trunk))"
    "[street[route_number]], neighborhood(type(house))], city_clean[county], state_abbr]"
)
```

- [ ] **Step 2: Add rendering tests that pin current output**

Add tests:

```python
from unittest.mock import AsyncMock

from homeassistant.const import CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
)
from custom_components.places.sensor import Places


async def render_display_option(mock_hass, monkeypatch, display_option: str) -> str | None:
    """Render one display option using the integration test attribute snapshot."""
    config_entry = MockConfigEntry(domain="places", data={CONF_NAME: "Test Place"})
    config = {CONF_DEVICETRACKER_ID: "device_tracker.test_iphone"}
    sensor = Places(mock_hass, config, config_entry, "Test Place", "unique-id-123", {})
    sensor._internal_attr = copy.deepcopy(BASE_INTERNAL_ATTR)
    sensor.clear_attr(ATTR_NATIVE_VALUE)
    sensor._attr_native_value = None
    sensor.set_attr(CONF_DISPLAY_OPTIONS, display_option)
    sensor.set_attr(ATTR_DISPLAY_OPTIONS, display_option)
    sensor.set_attr(ATTR_DISPLAY_OPTIONS_LIST, [])
    monkeypatch.setattr(sensor, "in_zone", AsyncMock(return_value=False), raising=False)
    monkeypatch.setattr(sensor, "get_driving_status", AsyncMock(return_value=None), raising=False)

    await sensor.process_display_options()

    return sensor.get_attr(ATTR_NATIVE_VALUE)


async def test_readme_place_advanced_example_matches_basic_place(
    mock_hass,
    monkeypatch,
) -> None:
    """README advanced `place` example renders the same value as basic `place`."""
    basic_state = await render_display_option(mock_hass, monkeypatch, "place")
    advanced_state = await render_display_option(mock_hass, monkeypatch, README_PLACE_ADVANCED)

    assert advanced_state == basic_state


async def test_readme_formatted_place_advanced_example_matches_formatted_place(
    mock_hass,
    monkeypatch,
) -> None:
    """README advanced formatted_place example renders the same value."""
    formatted_state = await render_display_option(mock_hass, monkeypatch, "formatted_place")
    advanced_state = await render_display_option(
        mock_hass,
        monkeypatch,
        README_FORMATTED_PLACE_ADVANCED,
    )

    assert advanced_state == formatted_state
```

- [ ] **Step 3: Run display characterization tests**

```bash
./.venv/bin/python -m pytest tests/test_display_options_integration.py tests/test_basic_options.py tests/test_advanced_options.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_display_options_integration.py
git commit -m "test: characterize readme display examples"
```

## Task 10: Cleanup Display Rendering Internals

**Files:**
- Modify: `custom_components/places/basic_options.py`
- Modify: `custom_components/places/advanced_options.py`
- Test: `tests/test_basic_options.py`, `tests/test_advanced_options.py`, `tests/test_display_options_integration.py`

- [ ] **Step 1: Extract basic display append helper to a method**

In `custom_components/places/basic_options.py`, move the nested `add_to_display` function out of `build_display`:

```python
def add_to_display(
    self,
    user_display: list[str],
    attr_key: str,
    option_key: str | None = None,
    condition: bool = True,
    require_in_display_options: bool = True,
) -> None:
    """Append an attribute value when the display rules allow it."""
    if (
        (not require_in_display_options or option_key in self.display_options)
        and not self.sensor.is_attr_blank(attr_key)
        and condition
    ):
        user_display.append(self.sensor.get_attr_safe_str(attr_key))
```

Replace nested calls like:

```python
add_to_display(option_key="driving", attr_key="driving")
```

with:

```python
self.add_to_display(user_display, option_key="driving", attr_key="driving")
```

- [ ] **Step 2: Add an advanced parser helper for next-expression recursion**

In `custom_components/places/advanced_options.py`, add:

```python
async def build_next_option(self, next_opt: str | None) -> None:
    """Continue parsing after a comma-prefixed next expression."""
    if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
        next_opt = next_opt[1:]
    if next_opt:
        await self.build_from_advanced_options(next_opt.strip())
```

Replace repeated blocks:

```python
if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
    next_opt = next_opt[1:]
    if next_opt:
        await self.build_from_advanced_options(next_opt.strip())
```

with:

```python
await self.build_next_option(next_opt)
```

- [ ] **Step 3: Run display tests**

```bash
./.venv/bin/python -m pytest tests/test_basic_options.py tests/test_advanced_options.py tests/test_display_options_integration.py -v
./.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add custom_components/places/basic_options.py custom_components/places/advanced_options.py tests/test_basic_options.py tests/test_advanced_options.py tests/test_display_options_integration.py
git commit -m "refactor: simplify display rendering internals"
```

## Task 11: Extract Config Schema Helpers

**Files:**
- Create: `custom_components/places/config_schema.py`
- Modify: `custom_components/places/config_flow.py`
- Test: `tests/test_config_flow.py`

- [ ] **Step 1: Add config schema helper module**

Create `custom_components/places/config_schema.py`:

```python
"""Config and options schema builders for Places."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
)

MAP_PROVIDER_OPTIONS: list[str] = ["apple", "google", "osm"]
STATE_OPTIONS: list[str] = ["zone, place", "formatted_place", "zone_name, place"]
DATE_FORMAT_OPTIONS: list[str] = ["mm/dd", "dd/mm"]
MAP_ZOOM_MIN: int = 1
MAP_ZOOM_MAX: int = 20


def select_schema(options: list[selector.SelectOptionDict] | list[str], *, custom_value: bool) -> selector.SelectSelector:
    """Build the dropdown selector used by Places forms."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=False,
            custom_value=custom_value,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def user_schema(
    devicetracker_options: list[selector.SelectOptionDict],
    zone_options: list[selector.SelectOptionDict],
) -> vol.Schema:
    """Build the new-entry config-flow schema."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_DEVICETRACKER_ID): select_schema(devicetracker_options, custom_value=False),
            vol.Optional(CONF_API_KEY): str,
            vol.Optional(CONF_DISPLAY_OPTIONS, default=DEFAULT_DISPLAY_OPTIONS): select_schema(STATE_OPTIONS, custom_value=True),
            vol.Optional(CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE): select_schema(zone_options, custom_value=False),
            vol.Optional(CONF_MAP_PROVIDER, default=DEFAULT_MAP_PROVIDER): select_schema(MAP_PROVIDER_OPTIONS, custom_value=False),
            vol.Optional(CONF_MAP_ZOOM, default=int(DEFAULT_MAP_ZOOM)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=MAP_ZOOM_MIN, max=MAP_ZOOM_MAX, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_LANGUAGE): str,
            vol.Optional(CONF_USE_GPS, default=DEFAULT_USE_GPS): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(CONF_SHOW_TIME, default=DEFAULT_SHOW_TIME): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): select_schema(DATE_FORMAT_OPTIONS, custom_value=False),
        }
    )


def suggested_value(data: Mapping[str, Any], key: str, default: object | None = None) -> dict[str, object | None]:
    """Return Home Assistant selector suggested-value metadata."""
    return {"suggested_value": data.get(key, default)}
```

- [ ] **Step 2: Replace duplicated schema code in `config_flow.py`**

In `custom_components/places/config_flow.py`, import:

```python
from .config_schema import user_schema
```

Replace the inline `data_schema` construction block in `async_step_user` with:

```python
data_schema = user_schema(devicetracker_id_list, zone_list)
```

Leave options-flow schema inline for this task unless tests remain straightforward. This keeps the first config extraction bounded.

- [ ] **Step 3: Run config-flow tests**

```bash
./.venv/bin/python -m pytest tests/test_config_flow.py -v
./.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add custom_components/places/config_schema.py custom_components/places/config_flow.py tests/test_config_flow.py
git commit -m "refactor: extract config flow schema builder"
```

## Task 12: Final Verification And Documentation Review

**Files:**
- Modify: `README.md` only if contributor-facing module layout documentation is needed.
- Modify: `docs/superpowers/specs/2026-05-16-places-architecture-cleanup-design.md` only if implementation intentionally diverged from the approved design.
- Test: full suite and full prek.

- [ ] **Step 1: Run full pytest**

```bash
./.venv/bin/python -m pytest
```

Expected: full test suite passes with coverage output.

- [ ] **Step 2: Run full prek**

```bash
./.venv/bin/python -m prek run -a
```

Expected: all hooks pass. If ruff formats files, rerun:

```bash
./.venv/bin/python -m prek run -a
./.venv/bin/python -m pytest
```

- [ ] **Step 3: Inspect final diff**

```bash
git diff --stat main HEAD
git diff --name-only main HEAD
```

Expected: new helper modules and focused test files are present; no translation, manifest, HACS, or README change exists unless deliberately required.

- [ ] **Step 4: Commit final polish if needed**

If verification changed files, commit them:

```bash
git add custom_components/places tests README.md docs/superpowers
git commit -m "chore: finalize architecture cleanup"
```

If no files changed, do not create an empty commit.

## Final Acceptance Checklist

- [ ] Existing Home Assistant entity behavior is unchanged.
- [ ] `Places` still exposes the same helper methods used by existing tests and code.
- [ ] `PlacesUpdater.do_update` remains the compatibility entry point.
- [ ] Persisted JSON import/export shape is unchanged.
- [ ] Event type and payload keys are unchanged.
- [ ] OSM URL parameters, user-agent, timeout, cache, and throttle behavior are unchanged.
- [ ] README display examples render the same.
- [ ] Full `./.venv/bin/python -m pytest` passes.
- [ ] Full `./.venv/bin/python -m prek run -a` passes.
