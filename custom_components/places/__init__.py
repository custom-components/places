"""Initialize Home Assistant places integration."""

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_NAME, DOMAIN, PLATFORMS
from .persistence import PlacesStorage

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONFIG_SCHEMA: Callable[[dict], dict] = cv.empty_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    # _LOGGER.debug("[init async_setup_entry] entry: %s", entry.data)
    entry.runtime_data = dict(entry.data)

    # This creates each HA object for each platform your device requires.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    _LOGGER.info("Unloading Places entry: %s", entry.entry_id)
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove config-entry specific persisted state."""
    _LOGGER.info("Removing Places entry: %s", entry.entry_id)
    name = entry.data.get(CONF_NAME, entry.entry_id)
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
