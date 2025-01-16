"""Initialize Home Assistant places integration."""

from collections.abc import Callable, MutableMapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)
PLATFORMS: list[str] = [Platform.SENSOR]
CONFIG_SCHEMA: Callable[[dict], dict] = cv.empty_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""

    # _LOGGER.debug("[init async_setup_entry] entry: %s", entry.data)
    hass.data.setdefault(DOMAIN, {})
    hass_data: MutableMapping[str, Any] = dict(entry.data)
    hass.data[DOMAIN][entry.entry_id] = hass_data

    # This creates each HA object for each platform your device requires.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    _LOGGER.info("Unloading: %s", entry.data)
    unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
