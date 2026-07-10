"""Button entities for Places."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PlacesUpdateCoordinator
from .entity import PlacesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Force Update button for one Places entry."""
    async_add_entities([PlacesForceUpdateButton(config_entry.runtime_data)])


class PlacesForceUpdateButton(PlacesEntity, ButtonEntity):
    """Clear persisted data and perform one fresh Places update."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "force_update"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Force Update button."""
        super().__init__(coordinator, unique_suffix="force_update")

    async def async_press(self) -> None:
        """Request one forced update from the entry coordinator."""
        await self.coordinator.async_force_update()
