"""Switch entities for Places configuration."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SHOW_TIME
from .coordinator import PlacesUpdateCoordinator
from .entity import PlacesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Show Last Updated configuration entity."""
    async_add_entities([PlacesShowLastUpdatedSwitch(config_entry.runtime_data)])


class PlacesShowLastUpdatedSwitch(PlacesEntity, SwitchEntity):
    """Control whether the main sensor includes its last-updated suffix."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "show_last_updated"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Show Last Updated switch entity."""
        super().__init__(coordinator, unique_suffix=CONF_SHOW_TIME)

    @property
    def is_on(self) -> bool:
        """Return whether the suffix is enabled."""
        return bool(self.coordinator.get_attr(CONF_SHOW_TIME))

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the last-updated suffix."""
        await self.coordinator.async_update_setting(CONF_SHOW_TIME, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the last-updated suffix."""
        await self.coordinator.async_update_setting(CONF_SHOW_TIME, False)
