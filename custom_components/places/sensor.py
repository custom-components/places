"""Concrete sensor entities for the Places integration."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_ICON
from .coordinator import PlacesUpdateCoordinator
from .entity import (
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesAttributeSensorEntityDescription,
    PlacesEntity,
    PlacesSensorEntity,
)

__all__ = ["Places", "PlacesAttributeSensor", "PlacesEntity", "async_setup_entry"]


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
    del hass
    coordinator: PlacesUpdateCoordinator = config_entry.runtime_data
    entities: list[SensorEntity] = [Places(coordinator)]
    entities.extend(
        PlacesAttributeSensor(coordinator, description)
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
    )
    async_add_entities(entities, update_before_add=True)


class Places(PlacesSensorEntity):
    """Main Places display sensor backed by the entry coordinator."""

    _attr_name = None

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the main Places display sensor.

        Args:
            coordinator: Places coordinator that owns parsed state.
        """
        super().__init__(cast("Any", coordinator), unique_suffix=None)
        self._attr_icon = DEFAULT_ICON
        self._attr_extra_state_attributes = coordinator.main_state_attributes
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Copy display state and narrow attributes from coordinator data."""
        self._attr_native_value = (
            self.coordinator.data.native_value if self.coordinator.data else None
        )
        self._attr_extra_state_attributes = self.coordinator.main_state_attributes


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
        super().__init__(cast("Any", coordinator), unique_suffix=entity_description.key)
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
