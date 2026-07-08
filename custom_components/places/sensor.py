"""Concrete sensor entities for the Places integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_remove_extended_entity
from .const import CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR, DEFAULT_ICON, EXTENDED_ATTRIBUTE_LIST
from .coordinator import PlacesUpdateCoordinator
from .entity import (
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesAttributeSensorEntityDescription,
    PlacesEntity,
    PlacesSensorEntity,
)

__all__ = [
    "Places",
    "PlacesAttributeSensor",
    "PlacesEntity",
    "PlacesExtendedDataSensor",
    "async_setup_entry",
]


def _child_sensor_name(key: str) -> str:
    """Return a simple human-readable child sensor name."""
    return key.replace("_", " ").title()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Places sensor entities for one config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry being set up.
        async_add_entities: Callback used to register created entities.
    """
    coordinator: PlacesUpdateCoordinator = config_entry.runtime_data
    entities: list[SensorEntity] = [Places(coordinator)]
    entities.extend(
        PlacesAttributeSensor(coordinator, description)
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
    )
    if coordinator.config.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR):
        entities.append(PlacesExtendedDataSensor(coordinator))
    else:
        await async_remove_extended_entity(hass, config_entry)
    async_add_entities(entities)


class Places(PlacesSensorEntity):
    """Main Places display sensor backed by the entry coordinator."""

    _attr_name = None

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the main Places display sensor.

        Args:
            coordinator: Places coordinator that owns parsed state.
        """
        super().__init__(coordinator, unique_suffix=None)
        self._attr_icon = DEFAULT_ICON
        self._attr_extra_state_attributes = coordinator.main_state_attributes
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy display state and narrow attributes from coordinator data."""
        if self.entity_id is not None:
            self.coordinator.entity_id = self.entity_id
        self._attr_native_value = (
            self.coordinator.data.native_value if self.coordinator.data else None
        )
        self._attr_extra_state_attributes = self.coordinator.main_state_attributes

    async def async_added_to_hass(self) -> None:
        """Record the HA-assigned entity ID on the coordinator."""
        await super().async_added_to_hass()
        self.coordinator.entity_id = self.entity_id


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
        self._attr_name = _child_sensor_name(entity_description.key)
        self._attr_entity_registry_enabled_default = (
            entity_description.entity_registry_enabled_default
        )
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy this child sensor's value from coordinator data."""
        if self.entity_description.value_fn is not None:
            self._attr_native_value = self.entity_description.value_fn(self.coordinator)
            return
        if self.coordinator.data is None:
            self._attr_native_value = None
            return
        self._attr_native_value = self.coordinator.data.attributes.get(
            self.entity_description.attr_key
        )


class PlacesExtendedDataSensor(PlacesSensorEntity):
    """Diagnostic sensor that exposes raw extended Places payloads."""

    _attr_name = "Extended data"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the optional extended-data sensor."""
        super().__init__(coordinator, unique_suffix="extended_data")
        self._attr_extra_state_attributes = {}
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy raw extended dictionaries from the coordinator when present."""
        attrs = {
            attr: self.coordinator.get_attr(attr)
            for attr in EXTENDED_ATTRIBUTE_LIST
            if not self.coordinator.is_attr_blank(attr)
        }
        self._attr_extra_state_attributes = attrs
        self._attr_native_value = "available" if attrs else None
