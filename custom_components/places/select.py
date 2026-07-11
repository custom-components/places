"""Select entities for Places configuration."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_schema import MAP_PROVIDER_OPTIONS
from .const import CONF_MAP_PROVIDER
from .coordinator import PlacesUpdateCoordinator
from .entity import PlacesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Map Provider configuration entity."""
    async_add_entities([PlacesMapProviderSelect(config_entry.runtime_data)])


class PlacesMapProviderSelect(PlacesEntity, SelectEntity):
    """Select the provider used by the map-link sensor."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = MAP_PROVIDER_OPTIONS
    _attr_translation_key = "map_provider"

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the Map Provider select entity."""
        super().__init__(coordinator, unique_suffix=CONF_MAP_PROVIDER)

    @property
    def current_option(self) -> str:
        """Return the configured map provider."""
        return self.coordinator.get_attr_safe_str(CONF_MAP_PROVIDER)

    async def async_select_option(self, option: str) -> None:
        """Save and locally apply a map provider."""
        option = option.lower()
        if option not in MAP_PROVIDER_OPTIONS:
            msg = f"Unsupported map provider: {option}"
            raise ValueError(msg)
        await self.coordinator.async_update_setting(CONF_MAP_PROVIDER, option)
