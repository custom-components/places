"""Initialize Home Assistant places integration."""

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import CONF_NAME, DOMAIN, PLATFORMS
from .coordinator import PlacesUpdateCoordinator
from .persistence import PlacesStorage

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONFIG_SCHEMA: Callable[[dict], dict] = cv.empty_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    name = entry.data.get(CONF_NAME, entry.entry_id)
    persistence = PlacesStorage(hass=hass, entry_id=entry.entry_id, name=name)
    coordinator = PlacesUpdateCoordinator(
        hass=hass,
        config_entry=entry,
        imported_attributes=await persistence.async_load(),
        persistence=persistence,
    )
    entry.runtime_data = coordinator

    try:
        await coordinator.async_added_to_hass()
    except Exception:
        await coordinator.async_shutdown()
        entry.runtime_data = None
        raise

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown()
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        entry.runtime_data = None
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    _LOGGER.info("Unloading Places entry: %s", entry.entry_id)
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = entry.runtime_data
        await coordinator.async_shutdown()

    return unload_ok


async def async_remove_extended_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the optional extended-data sensor registry entry if it exists."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_extended_data",
    )
    if entity_id is not None:
        registry.async_remove(entity_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove config-entry specific persisted state."""
    _LOGGER.info("Removing Places entry: %s", entry.entry_id)
    name = entry.data.get(CONF_NAME, entry.entry_id)
    await async_remove_extended_entity(hass, entry)
    try:
        await PlacesStorage(
            hass=hass,
            entry_id=entry.entry_id,
            name=name,
        ).async_remove()
    except OSError as error:
        _LOGGER.warning(
            "Could not remove persisted Places data for entry %s: %s: %s",
            entry.entry_id,
            type(error).__name__,
            error,
        )
    return True
