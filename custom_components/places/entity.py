"""Shared Places entity bases and descriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
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
    ATTR_GPS_ACCURACY,
    ATTR_LAST_CHANGED,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_MAP_LINK,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_REGION,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
    CONF_NAME,
    DOMAIN,
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared HA Device metadata for this config entry.

        Returns:
            Device metadata used to group Places entities in Home Assistant.
        """
        current_name = self.coordinator.get_attr_safe_str(CONF_NAME)
        if not current_name:
            current_name = str(
                self.coordinator.config_entry.data.get(
                    CONF_NAME,
                    self.coordinator.config_entry.entry_id,
                )
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=current_name,
            manufacturer="Places",
            model="OpenStreetMap reverse geocode",
        )


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
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        """Copy coordinator data into this entity's cached attributes."""
        raise NotImplementedError


class PlacesAttributeSensorEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Description for a Places child sensor backed by the parent attribute store."""

    value_fn: PlacesValueFn | None = None


PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS: tuple[PlacesAttributeSensorEntityDescription, ...] = (
    PlacesAttributeSensorEntityDescription(key=ATTR_PLACE_NAME, icon="mdi:map-marker"),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE_NAME,
        icon="mdi:map-marker-radius",
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_CITY, icon="mdi:city-variant"),
    PlacesAttributeSensorEntityDescription(key=ATTR_REGION, icon="mdi:land-plots-marker"),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DIRECTION_OF_TRAVEL,
        icon="mdi:compass",
    ),
    PlacesAttributeSensorEntityDescription(key=ATTR_MAP_LINK, icon="mdi:map"),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_FROM_HOME,
        icon="mdi:home-import-outline",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=lambda coordinator: (
            coordinator.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME)
            if coordinator.get_attr(ATTR_DISTANCE_FROM_HOME) is not None
            else None
        ),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DISTANCE_TRAVELED,
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=lambda coordinator: (
            coordinator.get_attr_safe_float(ATTR_DISTANCE_TRAVELED)
            if coordinator.get_attr(ATTR_DISTANCE_TRAVELED) is not None
            else None
        ),
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY,
        icon="mdi:earth",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTRY_CODE,
        icon="mdi:earth",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_NUMBER,
        icon="mdi:pound-box",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET,
        icon="mdi:road",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STREET_REF,
        icon="mdi:road-variant",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_NEIGHBOURHOOD,
        icon="mdi:home-group",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_TOWN,
        icon="mdi:city-variant-outline",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_POSTAL_CODE,
        icon="mdi:postage-stamp",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_COUNTY,
        icon="mdi:image-marker",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_STATE_ABBR,
        icon="mdi:land-plots-marker",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_TYPE,
        icon="mdi:form-dropdown",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_PLACE_CATEGORY,
        icon="mdi:form-select",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_DEVICETRACKER_ZONE,
        icon="mdi:map-marker-radius-outline",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LATITUDE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_LONGITUDE,
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_GPS_ACCURACY,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
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
        icon="mdi:map-marker-question",
        entity_registry_enabled_default=False,
    ),
    PlacesAttributeSensorEntityDescription(
        key=ATTR_OSM_TYPE,
        icon="mdi:map-marker-question-outline",
        entity_registry_enabled_default=False,
    ),
)
