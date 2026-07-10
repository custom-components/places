"""Text entities for Places configuration."""

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DISPLAY_OPTIONS
from .coordinator import PlacesUpdateCoordinator
from .entity import PlacesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Display Options configuration entity."""
    async_add_entities([PlacesDisplayOptionsText(config_entry.runtime_data)])


class PlacesDisplayOptionsText(PlacesEntity, TextEntity):
    """Edit the display options used by the main Places sensor."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "display_options"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Display Options text entity."""
        super().__init__(coordinator, unique_suffix=CONF_DISPLAY_OPTIONS)

    @property
    def native_value(self) -> str:
        """Return the configured display options."""
        return self.coordinator.get_attr_safe_str(CONF_DISPLAY_OPTIONS)

    async def async_set_value(self, value: str) -> None:
        """Validate, save, and apply new display options."""
        await self.coordinator.async_update_setting(CONF_DISPLAY_OPTIONS, value)
