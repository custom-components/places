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
    """Set up the Force Update button for one Places entry.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        config_entry (ConfigEntry):
            Config entry being set up.
        async_add_entities (AddEntitiesCallback):
            Callback used to register created entities.
    """
    coordinator: PlacesUpdateCoordinator = config_entry.runtime_data
    async_add_entities([PlacesForceUpdateButton(coordinator)])


class PlacesForceUpdateButton(PlacesEntity, ButtonEntity):
    """Run one cache-bypassing Places update without clearing persisted data."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "force_update"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Force Update button.

        Args:
            coordinator (PlacesUpdateCoordinator):
                Places update coordinator used by the entity or test.
        """
        super().__init__(coordinator, unique_suffix="force_update")

    async def async_press(self) -> None:
        """Request one forced update from the entry coordinator."""
        await self.coordinator.async_force_update()
