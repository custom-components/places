"""Text entities for Places configuration."""

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MAX_LENGTH_STATE_STATE
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
    """Set up the Display Options configuration entity.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        config_entry (ConfigEntry):
            Config entry being set up.
        async_add_entities (AddEntitiesCallback):
            Callback used to register created entities.
    """
    coordinator: PlacesUpdateCoordinator = config_entry.runtime_data
    async_add_entities([PlacesDisplayOptionsText(coordinator)])


class PlacesDisplayOptionsText(PlacesEntity, TextEntity):
    """Edit the display options used by the main Places sensor."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "display_options"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Display Options text entity.

        Args:
            coordinator (PlacesUpdateCoordinator):
                Places update coordinator used by the entity or test.
        """
        super().__init__(coordinator, unique_suffix=CONF_DISPLAY_OPTIONS)

    @property
    def native_value(self) -> str | None:
        """Return the configured display options.

        Returns:
            str | None:
                Current text value exposed to Home Assistant.
        """
        value = self.coordinator.get_attr_safe_str(CONF_DISPLAY_OPTIONS)
        return value if len(value) <= MAX_LENGTH_STATE_STATE else None

    async def async_set_value(self, value: str) -> None:
        """Validate, save, and apply new display options.

        Args:
            value (str):
                Display-options string saved through the coordinator.
        """
        await self.coordinator.async_update_setting(CONF_DISPLAY_OPTIONS, value)
