# Places Entity Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current large Places attribute surface with one main display sensor, one HA Device per Places entry, curated child sensors, and one optional extended-data payload sensor.

**Architecture:** Convert each Places config entry to a coordinator-driven model. A per-entry `PlacesUpdateCoordinator` owns tracker subscriptions, geocoding, parsing, persistence, rollback, and the parsed runtime data. Every entity inherits from a shared `PlacesEntity` base, sensor entities inherit from `PlacesSensorEntity`, and `_handle_coordinator_update` copies coordinator data into `_attr_*` sensor fields before writing to HA.

**Tech Stack:** Home Assistant custom integration, `DataUpdateCoordinator`, `CoordinatorEntity`, `SensorEntity`, `SensorEntityDescription`, `DeviceInfo`, entity registry cleanup, pytest, pytest-homeassistant-custom-component, `prek`, `ruff`, `mypy`.

---

## File Structure

- Create `custom_components/places/entity.py`: shared `PlacesEntity` and `PlacesSensorEntity` bases plus declarative sensor descriptions, default-enabled policy, native units, and the extended-data key.
- Create `custom_components/places/coordinator.py`: per-entry `PlacesUpdateCoordinator`, immutable `PlacesData` snapshots, attribute helper methods, tracker subscription setup, persistence, and update notification.
- Modify `custom_components/places/sensor.py`: define only concrete sensor classes and platform setup; concrete sensors inherit from `PlacesSensorEntity`, cache state in `_attr_native_value` and `_attr_extra_state_attributes`, and keep main attributes narrow.
- Modify `custom_components/places/update_sensor.py`: operate on the coordinator instead of a sensor entity, gate extended lookups on the config option, and stop putting raw extended payloads into bus events.
- Modify `custom_components/places/pipeline.py`, `parse_osm.py`, `basic_options.py`, and `advanced_options.py`: accept the coordinator attribute helper protocol instead of depending on the main sensor class.
- Modify `custom_components/places/__init__.py`: create/store/unload the coordinator and remove the extended-data entity registry entry when the option is turned off or an entry is removed.
- Modify `custom_components/places/const.py`: add constants for new entity suffixes and the narrowed main attribute list.
- Modify `custom_components/places/config_flow.py`, `custom_components/places/config_schema.py`, and `translations/*.json`: keep the existing Extended Attributes option but update its meaning.
- Modify `README.md`: document the breaking migration from `state_attr(...)` to child sensors.
- Modify `tests/test_sensor.py`, `tests/test_update_sensor.py`, `tests/test_integration.py`, and `tests/test_config_flow.py`: cover entity creation, defaults, registry cleanup, extended lookup gating, recorder exclusion, and docs-facing option behavior.

## Task 1: Define Shared Entity Bases and Sensor Descriptions

**Files:**
- Create: `custom_components/places/entity.py`
- Modify: `custom_components/places/const.py`
- Test: `tests/test_sensor.py`

- [ ] **Step 1: Write failing tests for the description tables**

Add these tests to `tests/test_sensor.py`:

```python
from custom_components.places.entity import (
    DEFAULT_ATTRIBUTE_SENSOR_KEYS,
    DISABLED_ATTRIBUTE_SENSOR_KEYS,
    EXTENDED_DATA_KEY,
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesEntity,
    PlacesSensorEntity,
)


def test_attribute_sensor_descriptions_have_expected_default_policy() -> None:
    """The default child sensor set should stay curated and omit formatted address."""
    assert DEFAULT_ATTRIBUTE_SENSOR_KEYS == {
        "place_name",
        "devicetracker_zone_name",
        "city",
        "state_province",
        "direction_of_travel",
        "map_link",
        "distance_from_home",
        "distance_traveled",
    }
    assert "formatted_address" not in DEFAULT_ATTRIBUTE_SENSOR_KEYS
    assert "country" in DISABLED_ATTRIBUTE_SENSOR_KEYS


def test_attribute_sensor_description_keys_are_unique() -> None:
    """Each child sensor description should produce one stable unique-id suffix."""
    keys = [description.key for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS]

    assert len(keys) == len(set(keys))
    assert EXTENDED_DATA_KEY not in keys


def test_shared_places_entity_bases_live_in_entity_module() -> None:
    """Shared Places entity bases should live with descriptions, not in sensor.py."""
    assert PlacesSensorEntity.__mro__[1] is PlacesEntity
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_attribute_sensor_descriptions_have_expected_default_policy tests/test_sensor.py::test_attribute_sensor_description_keys_are_unique -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.places.entity'`.

- [ ] **Step 3: Add constants**

Add to `custom_components/places/const.py` near the attribute lists:

```python
ATTR_EXTENDED_DATA = "extended_data"
ATTR_DISTANCE_FROM_HOME = "distance_from_home"
ATTR_DISTANCE_TRAVELED = "distance_traveled"

MAIN_STATE_ATTRIBUTE_LIST: list[str] = [
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_GPS_ACCURACY,
    ATTR_PICTURE,
    ATTR_ATTRIBUTION,
]
```

- [ ] **Step 4: Create entity descriptions**

Create `custom_components/places/entity.py`:

```python
"""Shared Places entity bases and descriptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CITY,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_TRAVELED,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_EXTENDED_DATA,
    ATTR_LAST_CHANGED,
    ATTR_LAST_PLACE_NAME,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE_OLD,
    ATTR_LONGITUDE_OLD,
    ATTR_MAP_LINK,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_REGION,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
)

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

type PlacesValueFn = Callable[["PlacesUpdateCoordinator"], StateType]

EXTENDED_DATA_KEY = ATTR_EXTENDED_DATA


class PlacesEntity(CoordinatorEntity[PlacesUpdateCoordinator]):
    """Base class for all Places entities backed by one coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: PlacesUpdateCoordinator, unique_suffix: str | None) -> None:
        """Initialize a Places coordinator entity.

        Args:
            coordinator: Places coordinator that owns runtime data.
            unique_suffix: Optional unique-id suffix for child entities.
        """
        super().__init__(coordinator)
        self._attr_unique_id = (
            coordinator.config_entry.entry_id
            if unique_suffix is None
            else f"{coordinator.config_entry.entry_id}_{unique_suffix}"
        )
        self._attr_device_info = coordinator.device_info


class PlacesSensorEntity(PlacesEntity, SensorEntity):
    """Base class for Places sensors that cache state from coordinator data."""

    def __init__(self, coordinator: PlacesUpdateCoordinator, unique_suffix: str | None) -> None:
        """Initialize a Places sensor entity."""
        super().__init__(coordinator, unique_suffix)
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh cached entity attributes from coordinator data and write state."""
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        """Copy coordinator data into this entity's cached attributes."""
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class PlacesAttributeSensorEntityDescription(SensorEntityDescription):
    """Description for a Places child sensor backed by the parent attribute store."""

    attr_key: str
    value_fn: PlacesValueFn | None = None


def _meters_attr(attr_key: str) -> PlacesValueFn:
    """Return a value function that reads a meter-valued parent attribute."""

    def _value(coordinator: PlacesUpdateCoordinator) -> StateType:
        value = coordinator.get_attr(attr_key)
        return coordinator.get_attr_safe_float(attr_key) if value is not None else None

    return _value


PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS: tuple[PlacesAttributeSensorEntityDescription, ...] = (
    PlacesAttributeSensorEntityDescription(key=ATTR_PLACE_NAME, attr_key=ATTR_PLACE_NAME),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE_NAME,
        attr_key=ATTR_DEVICETRACKER_ZONE_NAME,
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_CITY, attr_key=ATTR_CITY),
    PlacesAttributeSensorEntityDescription(key=ATTR_REGION, attr_key=ATTR_REGION),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DIRECTION_OF_TRAVEL,
        attr_key=ATTR_DIRECTION_OF_TRAVEL,
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_MAP_LINK, attr_key=ATTR_MAP_LINK),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_FROM_HOME,
        attr_key=ATTR_DISTANCE_FROM_HOME_M,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=_meters_attr(ATTR_DISTANCE_FROM_HOME_M),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_TRAVELED,
        attr_key=ATTR_DISTANCE_TRAVELED_M,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=_meters_attr(ATTR_DISTANCE_TRAVELED_M),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY,
        attr_key=ATTR_COUNTRY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY_CODE,
        attr_key=ATTR_COUNTRY_CODE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_NUMBER,
        attr_key=ATTR_STREET_NUMBER,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET,
        attr_key=ATTR_STREET,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_REF,
        attr_key=ATTR_STREET_REF,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_NEIGHBOURHOOD,
        attr_key=ATTR_PLACE_NEIGHBOURHOOD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_TOWN,
        attr_key=ATTR_POSTAL_TOWN,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_CODE,
        attr_key=ATTR_POSTAL_CODE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTY,
        attr_key=ATTR_COUNTY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STATE_ABBR,
        attr_key=ATTR_STATE_ABBR,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_TYPE,
        attr_key=ATTR_PLACE_TYPE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_CATEGORY,
        attr_key=ATTR_PLACE_CATEGORY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_NAME_NO_DUPE,
        attr_key=ATTR_PLACE_NAME_NO_DUPE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE,
        attr_key=ATTR_DEVICETRACKER_ZONE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LATITUDE_OLD,
        attr_key=ATTR_LATITUDE_OLD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LONGITUDE_OLD,
        attr_key=ATTR_LONGITUDE_OLD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_PLACE_NAME,
        attr_key=ATTR_LAST_PLACE_NAME,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_CHANGED,
        attr_key=ATTR_LAST_CHANGED,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_UPDATED,
        attr_key=ATTR_LAST_UPDATED,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_OSM_ID,
        attr_key=ATTR_OSM_ID,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_OSM_TYPE,
        attr_key=ATTR_OSM_TYPE,
        entity_registry_enabled_default=False,
    ),
)

DEFAULT_ATTRIBUTE_SENSOR_KEYS = {
    description.key
    for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
    if description.entity_registry_enabled_default
}
DISABLED_ATTRIBUTE_SENSOR_KEYS = {
    description.key
    for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
    if not description.entity_registry_enabled_default
}
```

- [ ] **Step 5: Run the tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_attribute_sensor_descriptions_have_expected_default_policy tests/test_sensor.py::test_attribute_sensor_description_keys_are_unique -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/places/const.py custom_components/places/entity.py tests/test_sensor.py
git commit -m "feat: define places child sensor descriptions"
```

## Task 2: Add the Places Update Coordinator

**Files:**
- Create: `custom_components/places/coordinator.py`
- Modify: `custom_components/places/__init__.py`
- Modify: `custom_components/places/pipeline.py`
- Modify: `custom_components/places/update_sensor.py`
- Test: `tests/test_sensor.py`

- [ ] **Step 1: Write failing tests for coordinator state and device info**

Add to `tests/test_sensor.py`:

```python
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.coordinator import PlacesData, PlacesUpdateCoordinator
from custom_components.places.const import (
    ATTR_ATTRIBUTION,
    ATTR_CITY,
    ATTR_GPS_ACCURACY,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_PICTURE,
)


def test_places_data_copies_attributes() -> None:
    """Coordinator data snapshots should not expose mutable internal state."""
    source = {ATTR_LATITUDE: 1.25}
    data = PlacesData(native_value="Library", attributes=source)
    source[ATTR_LATITUDE] = 9.5

    assert data.attributes == {ATTR_LATITUDE: 1.25}


def test_coordinator_device_info_uses_config_entry(mock_hass: MagicMock) -> None:
    """All Places entities for one entry should group under one HA Device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(
        hass=mock_hass,
        config_entry=entry,
        imported_attributes={},
        persistence=MagicMock(),
    )

    assert coordinator.device_info == {
        "identifiers": {("places", "entry123")},
        "name": "TestSensor",
        "manufacturer": "Places",
        "model": "OpenStreetMap reverse geocode",
    }


def test_coordinator_main_attributes_are_location_context_only(
    mock_hass: MagicMock,
) -> None:
    """The display sensor should expose only location-context attributes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(
        hass=mock_hass,
        config_entry=entry,
        imported_attributes={},
        persistence=MagicMock(),
    )
    coordinator.set_attr(ATTR_LATITUDE, 1.25)
    coordinator.set_attr(ATTR_LONGITUDE, -2.5)
    coordinator.set_attr(ATTR_GPS_ACCURACY, 8.0)
    coordinator.set_attr(ATTR_PICTURE, "/local/person.png")
    coordinator.set_attr(ATTR_ATTRIBUTION, "OpenStreetMap")
    coordinator.set_attr(ATTR_CITY, "Richmond")

    assert coordinator.main_state_attributes == {
        ATTR_LATITUDE: 1.25,
        ATTR_LONGITUDE: -2.5,
        ATTR_GPS_ACCURACY: 8.0,
        ATTR_PICTURE: "/local/person.png",
        ATTR_ATTRIBUTION: "OpenStreetMap",
    }
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_places_data_copies_attributes tests/test_sensor.py::test_coordinator_device_info_uses_config_entry tests/test_sensor.py::test_coordinator_main_attributes_are_location_context_only -v
```

Expected: FAIL because `custom_components.places.coordinator` does not exist.

- [ ] **Step 3: Create the coordinator data model and attribute helpers**

Create `custom_components/places/coordinator.py`:

```python
"""Coordinator for Places config entries."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import timedelta
import copy
import logging
from typing import Any, TypeVar

import cachetools
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_ICON, CONF_NAME, CONF_UNIQUE_ID, EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import Throttle

from .attributes import PlacesAttributes
from .const import (
    ATTR_DEVICETRACKER_ID,
    ATTR_INITIAL_UPDATE,
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_ICON,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    DOMAIN,
    MAIN_STATE_ATTRIBUTE_LIST,
    OSM_CACHE,
    OSM_CACHE_MAX_AGE_HOURS,
    OSM_CACHE_MAX_SIZE,
    OSM_THROTTLE,
)
from .persistence import PlacesStorage

_LOGGER = logging.getLogger(__name__)
_AttrT = TypeVar("_AttrT", default=Any)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)


@dataclass(frozen=True, kw_only=True)
class PlacesData:
    """Snapshot of Places state exposed through the coordinator."""

    native_value: str | None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy attributes so later internal mutations do not rewrite this snapshot."""
        object.__setattr__(self, "attributes", dict(self.attributes))


class PlacesUpdateCoordinator(DataUpdateCoordinator[PlacesData]):
    """Per-entry coordinator that owns Places updates and parsed state."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        imported_attributes: MutableMapping[str, Any],
        persistence: PlacesStorage,
    ) -> None:
        """Initialize the Places coordinator.

        Args:
            hass: Home Assistant instance.
            config_entry: Places config entry.
            imported_attributes: Previously persisted attribute snapshot.
            persistence: Store-backed persistence helper for this entry.
        """
        self.config_entry = config_entry
        self.config: MutableMapping[str, Any] = dict(config_entry.data)
        self.name = str(self.config[CONF_NAME])
        self._attributes = PlacesAttributes()
        self._persistence = persistence
        self._unsub_tracker: callback | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"Places {self.name}",
            config_entry=config_entry,
            always_update=False,
        )
        self._initialize_config_attributes()
        self.import_persisted_attributes(imported_attributes)
        self.async_set_updated_data(self.snapshot())

    @property
    def device_info(self) -> DeviceInfo:
        """Return the single HA Device for this Places entry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.name,
            manufacturer="Places",
            model="OpenStreetMap reverse geocode",
        )

    @property
    def main_state_attributes(self) -> dict[str, Any]:
        """Return the small location-context attribute set for the display sensor."""
        return {
            attr: self.get_attr(attr)
            for attr in MAIN_STATE_ATTRIBUTE_LIST
            if not self.is_attr_blank(attr)
        }

    def _initialize_config_attributes(self) -> None:
        """Load static config-entry values into the runtime attribute store."""
        self.set_attr(ATTR_INITIAL_UPDATE, True)
        self.set_attr(CONF_NAME, self.name)
        self.set_attr(CONF_UNIQUE_ID, self.config_entry.entry_id)
        self.set_attr(CONF_ICON, DEFAULT_ICON)
        self.set_attr(CONF_API_KEY, self.config.get(CONF_API_KEY))
        self.set_attr(CONF_DEVICETRACKER_ID, self.config[CONF_DEVICETRACKER_ID].lower())
        self.set_attr(ATTR_DEVICETRACKER_ID, self.config[CONF_DEVICETRACKER_ID].lower())
        self.set_attr(CONF_HOME_ZONE, self.config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower())
        self.set_attr(CONF_MAP_PROVIDER, self.config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER).lower())
        self.set_attr(CONF_MAP_ZOOM, int(self.config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)))
        self.set_attr(CONF_LANGUAGE, self.config.get(CONF_LANGUAGE))
        self.set_attr(CONF_EXTENDED_ATTR, self.config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR))
        self.set_attr(CONF_SHOW_TIME, self.config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME))
        self.set_attr(CONF_USE_GPS, self.config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))

    def snapshot(self) -> PlacesData:
        """Return the current coordinator data snapshot."""
        return PlacesData(
            native_value=self.get_attr(ATTR_NATIVE_VALUE),
            attributes=dict(self._attributes.data),
        )

    def publish_update(self) -> None:
        """Publish current runtime state to all CoordinatorEntity subscribers."""
        self.async_set_updated_data(self.snapshot())

    def get_internal_attr(self) -> MutableMapping[str, Any]:
        """Return the mutable internal attribute mapping."""
        return self._attributes.data

    def is_attr_blank(self, attr: str) -> bool:
        """Return whether an internal attribute is absent or falsey except zero."""
        return self._attributes.is_blank(attr)

    def get_attr(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Read an internal attribute with optional default handling."""
        return self._attributes.get(attr, default)

    def get_attr_safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Read an internal attribute as text."""
        return self._attributes.safe_str(attr, default)

    def get_attr_safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Read an internal attribute as a float."""
        return self._attributes.safe_float(attr, default)

    def get_attr_safe_list(self, attr: str | None, default: object | None = None) -> list:
        """Read an internal attribute as a list."""
        return self._attributes.safe_list(attr, default)

    def get_attr_safe_dict(self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None) -> MutableMapping[str, _AttrT]:
        """Read an internal attribute as a mutable mapping."""
        return self._attributes.safe_dict(attr, default)

    def set_attr(self, attr: str, value: object | None = None) -> None:
        """Store a value in the internal attribute mapping."""
        self._attributes.set(attr, value)

    def clear_attr(self, attr: str) -> None:
        """Remove an internal attribute if present."""
        self._attributes.clear(attr)

    def set_native_value(self, value: Any) -> None:
        """Update the rendered display state."""
        if value is not None:
            self.set_attr(ATTR_NATIVE_VALUE, value)
        else:
            self.clear_attr(ATTR_NATIVE_VALUE)

    def import_persisted_attributes(self, persisted_attr: MutableMapping[str, Any]) -> None:
        """Restore persisted runtime attributes from Store."""
        self.set_attr(ATTR_INITIAL_UPDATE, False)
        self._attributes.import_persisted_attributes(persisted_attr)

    async def async_persist_attributes(self) -> None:
        """Persist current runtime attributes to Store."""
        await self._persistence.async_save(self.get_internal_attr())

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracked-entity state changes."""
        self._unsub_tracker = async_track_state_change_event(
            self.hass,
            [str(self.get_attr(CONF_DEVICETRACKER_ID))],
            self.tsc_update,
        )

    async def async_shutdown(self) -> None:
        """Unsubscribe coordinator listeners before unload."""
        if self._unsub_tracker is not None:
            self._unsub_tracker()
            self._unsub_tracker = None

    @Throttle(MIN_THROTTLE_INTERVAL)
    @callback
    def tsc_update(self, event: Event[EventStateChangedData]) -> None:
        """Schedule a Places update from a tracked entity state-change event."""
        from .update_sensor import PlacesUpdater

        self.hass.async_create_task(
            PlacesUpdater(hass=self.hass, config_entry=self.config_entry, coordinator=self).do_update(
                reason="Track State Change",
                previous_attr=copy.deepcopy(self.get_internal_attr()),
            )
        )
```

- [ ] **Step 4: Store the coordinator on the config entry**

In `custom_components/places/__init__.py`, replace `entry.runtime_data = dict(entry.data)` with:

```python
name = entry.data.get(CONF_NAME, entry.entry_id)
persistence = PlacesStorage(hass=hass, entry_id=entry.entry_id, name=name)
coordinator = PlacesUpdateCoordinator(
    hass=hass,
    config_entry=entry,
    imported_attributes=await persistence.async_load(),
    persistence=persistence,
)
entry.runtime_data = coordinator
await coordinator.async_added_to_hass()
```

Import `PlacesUpdateCoordinator`.

- [ ] **Step 5: Unload the coordinator**

In `async_unload_entry`, after unloading platforms succeeds, add:

```python
if unload_ok:
    coordinator = entry.runtime_data
    await coordinator.async_shutdown()
```

- [ ] **Step 6: Update pipeline/updater names**

In `custom_components/places/update_sensor.py`, change `PlacesUpdater.__init__` to accept `coordinator: PlacesUpdateCoordinator`, set `self.coordinator = coordinator`, and replace `self.sensor` references with `self.coordinator`. Keep method names stable unless a rename is required by type checking; only the owner object changes.

In `custom_components/places/pipeline.py`, replace the local `sensor = self.updater.sensor` with:

```python
coordinator = self.updater.coordinator
```

Then replace `sensor.get_attr(...)` with `coordinator.get_attr(...)`. At successful update completion, call:

```python
coordinator.publish_update()
```

- [ ] **Step 7: Run the tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_places_data_copies_attributes tests/test_sensor.py::test_coordinator_device_info_uses_config_entry tests/test_sensor.py::test_coordinator_main_attributes_are_location_context_only -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/places/coordinator.py custom_components/places/__init__.py custom_components/places/pipeline.py custom_components/places/update_sensor.py tests/test_sensor.py
git commit -m "feat: add places update coordinator"
```

## Task 3: Add Places Entity Base Classes and CoordinatorEntity Sensors

**Files:**
- Modify: `custom_components/places/sensor.py`
- Test: `tests/test_sensor.py`

- [ ] **Step 1: Write failing tests for child sensors**

Add to `tests/test_sensor.py`:

```python
from custom_components.places.entity import PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
from custom_components.places.sensor import Places, PlacesAttributeSensor, PlacesEntity


def _description(key: str):
    """Return one Places child sensor description by key."""
    return next(
        description
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
        if description.key == key
    )


def test_attribute_sensor_reads_coordinator_attribute(mock_hass: MagicMock) -> None:
    """Child sensors should update their native value from coordinator data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("place_name", "Library")
    coordinator.publish_update()
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))

    assert entity.unique_id == "entry123_place_name"
    assert entity.native_value == "Library"
    assert entity.device_info == coordinator.device_info
    assert isinstance(entity, PlacesEntity)


def test_distance_attribute_sensor_reads_meter_value(mock_hass: MagicMock) -> None:
    """Distance sensors should expose one native meter value instead of km/mi/m variants."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("distance_from_home_m", 123.4)
    coordinator.publish_update()
    entity = PlacesAttributeSensor(coordinator, _description("distance_from_home"))

    assert entity.native_value == 123.4
    assert entity.native_unit_of_measurement == "m"


def test_main_places_sensor_uses_coordinator_state(mock_hass: MagicMock) -> None:
    """The main display sensor should copy coordinator state into _attr fields."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_native_value("Library")
    coordinator.set_attr("current_latitude", 1.25)
    coordinator.set_attr("city", "Richmond")
    coordinator.publish_update()
    entity = Places(coordinator)
    entity.async_write_ha_state = MagicMock()

    entity._handle_coordinator_update()

    assert entity.native_value == "Library"
    assert entity.extra_state_attributes == {"current_latitude": 1.25}
    assert entity._attr_native_value == "Library"
    assert entity._attr_extra_state_attributes == {"current_latitude": 1.25}
    entity.async_write_ha_state.assert_called_once_with()


def test_attribute_sensor_handle_coordinator_update_writes_state(mock_hass: MagicMock) -> None:
    """Attribute child sensors should refresh _attr_native_value in coordinator updates."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))
    entity.async_write_ha_state = MagicMock()
    coordinator.set_attr("place_name", "Library")
    coordinator.publish_update()

    entity._handle_coordinator_update()

    assert entity.native_value == "Library"
    assert entity._attr_native_value == "Library"
    entity.async_write_ha_state.assert_called_once_with()

```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_attribute_sensor_reads_coordinator_attribute tests/test_sensor.py::test_distance_attribute_sensor_reads_meter_value tests/test_sensor.py::test_main_places_sensor_uses_coordinator_state tests/test_sensor.py::test_attribute_sensor_handle_coordinator_update_writes_state -v
```

Expected: FAIL because `PlacesAttributeSensor` does not exist.

- [ ] **Step 3: Import shared Places entity bases**

In `custom_components/places/sensor.py`, import the shared bases and descriptions from `entity.py`:

```python
from .entity import (
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesAttributeSensorEntityDescription,
    PlacesEntity,
    PlacesSensorEntity,
)
```

Do not add `@property def native_value(...)` or `@property def extra_state_attributes(...)` to any Places sensor class. The Home Assistant base classes should read `_attr_native_value` and `_attr_extra_state_attributes`.

Also import:

```python
from homeassistant.helpers.typing import StateType
from .coordinator import PlacesUpdateCoordinator
```

- [ ] **Step 4: Implement the main display sensor**

Add below `PlacesSensorEntity`:

```python
class Places(PlacesSensorEntity):
    """Main Places display sensor backed by the entry coordinator."""

    _attr_name = None

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the main Places display sensor."""
        super().__init__(coordinator, unique_suffix=None)
        self._attr_icon = DEFAULT_ICON
        self._attr_extra_state_attributes = coordinator.main_state_attributes
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy display state and narrow attributes from coordinator data."""
        self._attr_native_value = self.coordinator.data.native_value if self.coordinator.data else None
        self._attr_extra_state_attributes = self.coordinator.main_state_attributes
```

- [ ] **Step 5: Implement `PlacesAttributeSensor`**

Add below `Places` in `custom_components/places/sensor.py`:

```python
class PlacesAttributeSensor(PlacesSensorEntity):
    """Read-only Places child sensor backed by coordinator data."""

    entity_description: PlacesAttributeSensorEntityDescription

    def __init__(
        self,
        coordinator: PlacesUpdateCoordinator,
        entity_description: PlacesAttributeSensorEntityDescription,
    ) -> None:
        """Initialize a Places child sensor.

        Args:
            coordinator: Places coordinator that owns parsed state.
            entity_description: Child sensor description.
        """
        super().__init__(coordinator, unique_suffix=entity_description.key)
        self.entity_description = entity_description
        self._attr_entity_registry_enabled_default = (
            entity_description.entity_registry_enabled_default
        )
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy this child sensor's value from coordinator data."""
        if self.entity_description.value_fn is not None:
            self._attr_native_value = self.entity_description.value_fn(self.coordinator)
        elif self.coordinator.data is None:
            self._attr_native_value = None
        else:
            self._attr_native_value = self.coordinator.data.attributes.get(
                self.entity_description.attr_key
            )
```

Add these imports:

```python
from homeassistant.helpers.typing import StateType
from .coordinator import PlacesUpdateCoordinator
from .entity import (
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesAttributeSensorEntityDescription,
    PlacesEntity,
    PlacesSensorEntity,
)
```

- [ ] **Step 6: Add coordinator-backed entities during setup**

In `async_setup_entry`, get the coordinator from `config_entry.runtime_data`:

```python
coordinator: PlacesUpdateCoordinator = config_entry.runtime_data
entities: list[SensorEntity] = [Places(coordinator)]
entities.extend(
    PlacesAttributeSensor(coordinator, description)
    for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
)
async_add_entities(entities, update_before_add=True)
```

- [ ] **Step 7: Run child sensor tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_attribute_sensor_reads_coordinator_attribute tests/test_sensor.py::test_distance_attribute_sensor_reads_meter_value tests/test_sensor.py::test_main_places_sensor_uses_coordinator_state tests/test_sensor.py::test_attribute_sensor_handle_coordinator_update_writes_state -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/places/sensor.py tests/test_sensor.py
git commit -m "feat: add places child attribute sensors"
```

## Task 4: Implement Extended Data Sensor and Registry Cleanup

**Files:**
- Modify: `custom_components/places/sensor.py`
- Modify: `custom_components/places/__init__.py`
- Test: `tests/test_sensor.py`
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write failing tests for extended sensor behavior**

Add to `tests/test_sensor.py`:

```python
from homeassistant.const import MATCH_ALL
from custom_components.places.const import ATTR_OSM_DETAILS_DICT, ATTR_OSM_DICT, ATTR_WIKIDATA_DICT
from custom_components.places.sensor import PlacesExtendedDataSensor


def test_extended_data_sensor_exposes_raw_payload_and_is_unrecorded(
    mock_hass: MagicMock,
) -> None:
    """Extended data should stay one raw diagnostic sensor excluded from recorder."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr(ATTR_OSM_DICT, {"osm_id": 123})
    coordinator.set_attr(ATTR_OSM_DETAILS_DICT, {"extratags": {"wikidata": "Q123"}})
    coordinator.set_attr(ATTR_WIKIDATA_DICT, {"id": "Q123"})
    coordinator.publish_update()

    entity = PlacesExtendedDataSensor(coordinator)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()

    assert entity.unique_id == "entry123_extended_data"
    assert entity.native_value == "available"
    assert entity.extra_state_attributes == {
        ATTR_OSM_DICT: {"osm_id": 123},
        ATTR_OSM_DETAILS_DICT: {"extratags": {"wikidata": "Q123"}},
        ATTR_WIKIDATA_DICT: {"id": "Q123"},
    }
    assert entity._attr_native_value == "available"
    assert entity._attr_extra_state_attributes == {
        ATTR_OSM_DICT: {"osm_id": 123},
        ATTR_OSM_DETAILS_DICT: {"extratags": {"wikidata": "Q123"}},
        ATTR_WIKIDATA_DICT: {"id": "Q123"},
    }
    assert entity._unrecorded_attributes == frozenset({MATCH_ALL})
    entity.async_write_ha_state.assert_called_once_with()
```

Add to `tests/test_integration.py`:

```python
from custom_components.places import async_remove_extended_entity


async def test_async_remove_extended_entity_removes_registry_entry(mock_hass: MagicMock) -> None:
    """Turning Extended Attributes off should remove the extended_data entity."""
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.test_extended_data"
    mock_hass.helpers.entity_registry.async_get.return_value = registry
    entry = MockConfigEntry(domain="places", entry_id="entry123", data={"name": "Test"})

    await async_remove_extended_entity(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with("sensor", "places", "entry123_extended_data")
    registry.async_remove.assert_called_once_with("sensor.test_extended_data")
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_extended_data_sensor_exposes_raw_payload_and_is_unrecorded tests/test_integration.py::test_async_remove_extended_entity_removes_registry_entry -v
```

Expected: FAIL because `PlacesExtendedDataSensor` and `async_remove_extended_entity` do not exist.

- [ ] **Step 3: Implement `PlacesExtendedDataSensor`**

Add to `custom_components/places/sensor.py`:

```python
class PlacesExtendedDataSensor(PlacesSensorEntity):
    """Diagnostic sensor exposing raw extended OSM and Wikidata payloads."""

    _attr_name = "Extended data"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the extended data sensor.

        Args:
            coordinator: Places coordinator that owns extended payload state.
        """
        super().__init__(coordinator, unique_suffix="extended_data")
        self._attr_extra_state_attributes = {}
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy raw extended payloads from coordinator data."""
        attrs: dict[str, Any] = {}
        for attr in EXTENDED_ATTRIBUTE_LIST:
            if not self.coordinator.is_attr_blank(attr):
                attrs[attr] = self.coordinator.get_attr(attr)
        self._attr_extra_state_attributes = attrs
        self._attr_native_value = "available" if attrs else None
```

Add `EntityCategory` import:

```python
from homeassistant.const import EntityCategory
```

- [ ] **Step 4: Gate extended sensor creation**

In `async_setup_entry`, after adding attribute child sensors:

```python
if coordinator.config.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR):
    entities.append(PlacesExtendedDataSensor(coordinator))
else:
    await async_remove_extended_entity(hass, config_entry)
```

Import `async_remove_extended_entity` from `custom_components.places`.

- [ ] **Step 5: Implement registry cleanup**

In `custom_components/places/__init__.py`, import:

```python
from homeassistant.const import Platform
import homeassistant.helpers.entity_registry as er
```

Add:

```python
async def async_remove_extended_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the optional extended_data entity registry entry for a Places entry.

    Args:
        hass: Home Assistant instance.
        entry: Places config entry whose optional extended entity should be removed.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_extended_data",
    )
    if entity_id is not None:
        registry.async_remove(entity_id)
```

In `async_remove_entry`, before removing storage, add:

```python
await async_remove_extended_entity(hass, entry)
```

- [ ] **Step 6: Run the tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_extended_data_sensor_exposes_raw_payload_and_is_unrecorded tests/test_integration.py::test_async_remove_extended_entity_removes_registry_entry -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/places/sensor.py custom_components/places/__init__.py tests/test_sensor.py tests/test_integration.py
git commit -m "feat: add optional places extended data sensor"
```

## Task 5: Gate Extended Lookups and Event Payloads

**Files:**
- Modify: `custom_components/places/update_sensor.py`
- Test: `tests/test_update_sensor.py`

- [ ] **Step 1: Write failing tests for lookup gating and event payloads**

Add to `tests/test_update_sensor.py`:

```python
async def test_handle_state_update_skips_extended_lookup_when_option_false(
    updater: PlacesUpdater,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extended network lookups should run only when the entry option is enabled."""
    updater.coordinator.set_attr(CONF_EXTENDED_ATTR, False)
    get_extended_attr = AsyncMock()
    monkeypatch.setattr(updater, "get_extended_attr", get_extended_attr)

    await updater.handle_state_update(now=await updater.get_current_time(), prev_last_place_name="")

    get_extended_attr.assert_not_awaited()


async def test_fire_event_data_omits_raw_extended_payloads(updater: PlacesUpdater) -> None:
    """Places state update events should not carry raw extended dict payloads."""
    updater.coordinator.set_attr(CONF_EXTENDED_ATTR, True)
    updater.coordinator.set_attr(ATTR_OSM_DICT, {"raw": "payload"})
    updater.coordinator.set_attr(ATTR_OSM_DETAILS_DICT, {"details": "payload"})
    updater.coordinator.set_attr(ATTR_WIKIDATA_DICT, {"wikidata": "payload"})
    updater._hass.bus.fire = MagicMock()

    await updater.fire_event_data(prev_last_place_name="")

    event_data = updater._hass.bus.fire.call_args.args[1]
    assert ATTR_OSM_DICT not in event_data
    assert ATTR_OSM_DETAILS_DICT not in event_data
    assert ATTR_WIKIDATA_DICT not in event_data
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_update_sensor.py::test_handle_state_update_skips_extended_lookup_when_option_false tests/test_update_sensor.py::test_fire_event_data_omits_raw_extended_payloads -v
```

Expected: FAIL until `PlacesUpdater` uses `coordinator` and omits raw extended payloads from event data.

- [ ] **Step 3: Keep extended lookups option-gated**

In `PlacesUpdater.handle_state_update`, keep:

```python
if self.coordinator.get_attr(CONF_EXTENDED_ATTR):
    await self.get_extended_attr()
```

This means `Extended Attributes = false` performs no details/Wikidata network calls.

- [ ] **Step 4: Build events without raw extended payloads**

In `PlacesUpdater.fire_event_data`, build `event_data` from `EVENT_ATTRIBUTE_LIST` only. Do not add `EXTENDED_ATTRIBUTE_LIST` to event payloads:

```python
for attr in EVENT_ATTRIBUTE_LIST:
    if not self.coordinator.is_attr_blank(attr):
        event_data[attr] = self.coordinator.get_attr(attr)
```

- [ ] **Step 5: Run the tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_update_sensor.py::test_handle_state_update_skips_extended_lookup_when_option_false tests/test_update_sensor.py::test_fire_event_data_omits_raw_extended_payloads -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/places/update_sensor.py tests/test_update_sensor.py
git commit -m "feat: gate places extended event data"
```

## Task 6: Update Setup Tests and Config Flow Text

**Files:**
- Modify: `tests/test_sensor.py`
- Modify: `tests/test_config_flow.py`
- Modify: `custom_components/places/translations/en.json`
- Modify: `custom_components/places/translations/cs.json`
- Modify: `custom_components/places/translations/it.json`
- Modify: `custom_components/places/translations/ru.json`
- Modify: `custom_components/places/translations/sk.json`
- Modify: `custom_components/places/translations/uk.json`

- [ ] **Step 1: Write setup tests for entity creation counts**

Add to `tests/test_sensor.py`:

```python
@pytest.mark.asyncio
async def test_async_setup_entry_adds_main_and_child_sensors(
    mock_hass: MagicMock,
) -> None:
    """Setup should add the main sensor plus parsed child sensors."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={
            "name": "Alice",
            "devicetracker_id": "person.alice",
            "extended_attr": False,
        },
    )
    config_entry.runtime_data = PlacesUpdateCoordinator(mock_hass, config_entry, {}, MagicMock())
    added: list[SensorEntity] = []

    await async_setup_entry(mock_hass, config_entry, lambda entities, update_before_add: added.extend(entities))

    assert any(isinstance(entity, Places) for entity in added)
    assert any(isinstance(entity, PlacesAttributeSensor) for entity in added)
    assert not any(isinstance(entity, PlacesExtendedDataSensor) for entity in added)


@pytest.mark.asyncio
async def test_async_setup_entry_adds_extended_sensor_when_enabled(
    mock_hass: MagicMock,
) -> None:
    """Extended Attributes enabled should create the raw extended_data sensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={
            "name": "Alice",
            "devicetracker_id": "person.alice",
            "extended_attr": True,
        },
    )
    config_entry.runtime_data = PlacesUpdateCoordinator(mock_hass, config_entry, {}, MagicMock())
    added: list[SensorEntity] = []

    await async_setup_entry(mock_hass, config_entry, lambda entities, update_before_add: added.extend(entities))

    assert any(isinstance(entity, PlacesExtendedDataSensor) for entity in added)
```

- [ ] **Step 2: Run setup tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_async_setup_entry_adds_main_and_child_sensors tests/test_sensor.py::test_async_setup_entry_adds_extended_sensor_when_enabled -v
```

Expected: PASS after Tasks 3 and 4. If this fails, fix setup wiring before touching docs.

- [ ] **Step 3: Update English translation text**

In `custom_components/places/translations/en.json`, replace both `extended_attr` descriptions with:

```json
"extended_attr": "Create an Extended data diagnostic sensor and fetch raw OSM details/Wikidata payloads. When disabled, the sensor is removed and the extra lookups are skipped."
```

- [ ] **Step 4: Update non-English translation text conservatively**

For `cs.json`, `it.json`, `ru.json`, `sk.json`, and `uk.json`, replace both `extended_attr` descriptions with the same English text from Step 3. This repo already has untranslated English fallback strings in these files; do not invent machine translations.

- [ ] **Step 5: Run config flow and translation-adjacent tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_config_flow.py tests/test_sensor.py::test_async_setup_entry_adds_main_and_child_sensors tests/test_sensor.py::test_async_setup_entry_adds_extended_sensor_when_enabled -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/places/translations tests/test_sensor.py tests/test_config_flow.py
git commit -m "docs: clarify extended attributes option"
```

## Task 7: Document the Breaking Migration

**Files:**
- Modify: `README.md`
- Test: `tests/test_prek_autoupdate_workflow.py` is unaffected; no README test exists.

- [ ] **Step 1: Update README configuration text**

In `README.md`, change the `Extended Attributes` row to:

```markdown
`Extended Attributes` | `No` | `False` | Create an enabled diagnostic `Extended data` sensor and fetch raw OSM details/Wikidata payloads. When disabled, the sensor is removed and the extra lookups are skipped. The extended sensor is excluded from recorder.
```

- [ ] **Step 2: Replace the sample attributes section**

Replace the current sample attributes block with:

```markdown
<details>
<summary>Entity model and migration notes</summary>

The main Places sensor keeps the Display Options state. It only exposes location-context attributes:

* `current_latitude`
* `current_longitude`
* `gps_accuracy`
* `entity_picture`
* `attribution`

Most values that used to be attributes are now child sensors under the same Places device. For example:

* `state_attr('sensor.alice', 'place_name')` becomes `states('sensor.alice_place_name')`
* `state_attr('sensor.alice', 'city')` becomes `states('sensor.alice_city')`
* `state_attr('sensor.alice', 'state_province')` becomes `states('sensor.alice_state_province')`
* `state_attr('sensor.alice', 'map_link')` becomes `states('sensor.alice_map_link')`

The integration no longer creates a `formatted_address` child sensor.

`country` and detailed address/diagnostic sensors are disabled by default. Enable them from the Places device page if you use them in automations.

When Extended Attributes is enabled, raw payloads move to `sensor.<name>_extended_data`:

* `state_attr('sensor.alice_extended_data', 'osm_dict')`
* `state_attr('sensor.alice_extended_data', 'osm_details_dict')`
* `state_attr('sensor.alice_extended_data', 'wikidata_dict')`
* `state_attr('sensor.alice_extended_data', 'wikidata_id')`

</details>
```

- [ ] **Step 3: Verify README wording**

Run:

```bash
rg -n "Show extended attributes|formatted_address|Sample attributes|attributes very long" README.md
```

Expected: README describes the new Extended data sensor behavior. `formatted_address` may appear only in historical Display Options documentation, not as a child sensor.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document places entity model migration"
```

## Task 8: Full Validation

**Files:**
- No production files.
- Validation: full pytest and prek.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
./.venv/bin/python -m pytest
```

Expected: all tests pass without `--disable-warnings`.

- [ ] **Step 2: Run prek**

Run:

```bash
./.venv/bin/python -m prek run -a
```

Expected: all hooks pass. If `ruff` rewrites files, run this command again after staging the formatter output.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git diff --stat upstream/master...HEAD
git diff --check
```

Expected: diff contains the entity model redesign, tests, translations, and README updates only; `git diff --check` prints no whitespace errors.

- [ ] **Step 4: Verify branch tracking**

Run:

```bash
git status --short --branch
git branch -vv
git rev-parse --abbrev-ref --symbolic-full-name @{u}
```

Expected: branch is `revamp-places-entities`, upstream is `origin/revamp-places-entities`, and the worktree is clean after commits.

- [ ] **Step 5: Final commit if validation changed files**

Only if validation rewrote files:

```bash
git add custom_components tests README.md
git commit -m "chore: apply entity redesign formatting"
```

## Self-Review

- Spec coverage: coordinator-driven runtime, centralized `PlacesEntity`/`PlacesSensorEntity` hierarchy, `_handle_coordinator_update` sensor refresh into `_attr_*` fields, main Display Options state, location-only main attributes, no `formatted_address` child sensor, `country` disabled by default, one Device per entry, optional extended-data sensor, no extended lookups when disabled, registry cleanup when disabled, recorder exclusion only for `extended_data`, normal recorder behavior for other sensors, and docs migration are covered.
- Placeholder scan: no banned placeholder wording or open-ended edge-case instructions remain.
- Type consistency: child descriptions use `PlacesAttributeSensorEntityDescription`; child unique IDs use `<entry_id>_<description.key>`; extended unique ID uses `<entry_id>_extended_data`; distance sensors expose meter-valued native sensors keyed by `distance_from_home` and `distance_traveled`.
