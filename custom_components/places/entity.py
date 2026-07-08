"""Shared Places entity bases and descriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
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
    ATTR_DISTANCE_TRAVELED,
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


class PlacesEntity(CoordinatorEntity["PlacesUpdateCoordinator"]):
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
        """Initialize a Places sensor entity.

        Args:
            coordinator: Places coordinator that owns runtime data.
            unique_suffix: Optional unique-id suffix for child entities.
        """
        super().__init__(coordinator, unique_suffix)
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh cached entity attributes from coordinator data and write state."""
        self._attr_device_info = self.coordinator.device_info
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        """Copy coordinator data into this entity's cached attributes."""
        raise NotImplementedError


class PlacesAttributeSensorEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Description for a Places child sensor backed by the parent attribute store."""

    value_fn: PlacesValueFn | None = None


def _meters_attr(attr_key: str) -> PlacesValueFn:
    """Return a value function that reads a meter-valued parent attribute.

    Args:
        attr_key: Coordinator attribute storing the meter value.

    Returns:
        A callable that reads the configured meter attribute.
    """

    def _value(coordinator: PlacesUpdateCoordinator) -> StateType:
        value = coordinator.get_attr(attr_key)
        return coordinator.get_attr_safe_float(attr_key) if value is not None else None

    return _value


PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS: tuple[PlacesAttributeSensorEntityDescription, ...] = (
    PlacesAttributeSensorEntityDescription(key=ATTR_PLACE_NAME),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE_NAME,
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_CITY),
    PlacesAttributeSensorEntityDescription(key=ATTR_REGION),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DIRECTION_OF_TRAVEL,
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_MAP_LINK),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_FROM_HOME,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=_meters_attr(ATTR_DISTANCE_FROM_HOME),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_TRAVELED,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=_meters_attr(ATTR_DISTANCE_TRAVELED),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY_CODE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_NUMBER,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_REF,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_NEIGHBOURHOOD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_TOWN,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_CODE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STATE_ABBR,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_TYPE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_CATEGORY,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_NAME_NO_DUPE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LATITUDE_OLD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LONGITUDE_OLD,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_PLACE_NAME,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_CHANGED,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LAST_UPDATED,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_OSM_ID,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_OSM_TYPE,
        entity_registry_enabled_default=False,
    ),
)
