"""Initialize Home Assistant places integration."""

import asyncio
from collections.abc import Callable
import logging
import re

import cachetools
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    CONF_DISPLAY_OPTIONS,
    CONF_NAME,
    DEFAULT_DISPLAY_OPTIONS,
    DOMAIN,
    OSM_CACHE,
    OSM_CACHE_MAX_AGE_HOURS,
    OSM_CACHE_MAX_SIZE,
    OSM_THROTTLE,
    PLATFORMS,
)
from .coordinator import PlacesUpdateCoordinator
from .migration import async_migrate_legacy_snapshot
from .persistence import PlacesStorage

_LOGGER: logging.Logger = logging.getLogger(__name__)

CONFIG_SCHEMA: Callable[[dict], dict] = cv.empty_config_schema(DOMAIN)


def _ensure_osm_runtime_state(hass: HomeAssistant) -> None:
    """Initialize shared OSM cache and throttle state.

    Args:
        hass (HomeAssistant):
            Home Assistant instance that owns integration runtime data.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(
        OSM_CACHE,
        cachetools.TTLCache(maxsize=OSM_CACHE_MAX_SIZE, ttl=OSM_CACHE_MAX_AGE_HOURS * 3600),
    )
    domain_data.setdefault(
        OSM_THROTTLE,
        {
            "lock": asyncio.Lock(),
            "last_query": 0.0,
        },
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a Places config entry to the current version.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry to migrate.

    Returns:
        bool:
            ``True`` when migration completes.
    """
    if entry.version != 1:
        return True

    name = entry.data.get(CONF_NAME, entry.entry_id)
    await async_migrate_legacy_snapshot(hass, entry.entry_id, name)
    update_kwargs: dict = {"version": 2, "minor_version": 1}
    display_options = entry.data.get(CONF_DISPLAY_OPTIONS, "")
    migrated_display_options = _migrate_formatted_address_display_options(display_options)
    if migrated_display_options != display_options:
        update_kwargs["data"] = {
            **entry.data,
            CONF_DISPLAY_OPTIONS: migrated_display_options,
        }
    display_options = migrated_display_options
    options = [option.strip().lower() for option in _split_top_level_options(display_options)]
    if "do_not_reorder" in options:
        migrated_options_list: list[str] = []
        for option in options:
            if option in {"do_not_reorder", "do_not_show_not_home"}:
                continue
            if option == "place":
                migrated_options_list.extend(
                    [
                        "name_no_dupe",
                        "category(-, place)",
                        "type(-, yes)",
                        "neighborhood",
                        "house_number",
                        "street",
                    ]
                )
            else:
                migrated_options_list.append(option)
        options = migrated_options_list
        if options:
            if "formatted_place" not in options:
                options[0] += "[]"
            migrated_options = ", ".join(options)
        else:
            migrated_options = DEFAULT_DISPLAY_OPTIONS
        update_kwargs["data"] = {**entry.data, CONF_DISPLAY_OPTIONS: migrated_options}
    hass.config_entries.async_update_entry(entry, **update_kwargs)
    return True


def _split_top_level_options(display_options: str) -> list[str]:
    """Split display options on commas outside parentheses and brackets.

    Args:
        display_options (str):
            Raw comma-separated display-options expression.

    Returns:
        list[str]:
            Display-option expressions with nested commas kept intact.
    """
    options: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(display_options):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            options.append(display_options[start:index])
            start = index + 1
    options.append(display_options[start:])
    return options


def _migrate_formatted_address_display_options(raw_display_options: str) -> str:
    """Migrate ``formatted_address`` tokens while preserving literal filter values.

    Args:
        raw_display_options (str):
            The raw display-options string to migrate.

    Returns:
        str:
            The migrated display-options string with display-option identifiers renamed where safe.
    """
    out: list[str] = []
    paren_depth = 0
    last = 0
    for match in re.finditer(r"(?i)\bformatted_address\b", raw_display_options):
        segment = raw_display_options[last : match.start()]
        out.append(segment)
        paren_depth = max(
            0,
            paren_depth + segment.count("(") - segment.count(")"),
        )
        out.append(
            "osm_formatted_address"
            if paren_depth == 0 or raw_display_options[match.end() :].lstrip().startswith("(")
            else match.group()
        )
        last = match.end()
    out.append(raw_display_options[last:])
    return "".join(out)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Places from a config entry.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry to set up.

    Returns:
        bool:
            ``True`` when setup completes successfully.

    Raises:
        asyncio.CancelledError:
            Re-raised after failed-setup cleanup completes.
        Exception:
            Propagated when the operation fails.
    """
    _ensure_osm_runtime_state(hass)
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
    except asyncio.CancelledError:
        try:
            await coordinator.async_shutdown()
        except Exception:
            _LOGGER.exception("Cleanup failed after subscription cancellation for %s", name)
        finally:
            entry.runtime_data = None
        raise
    except Exception:
        # Keep setup failure paths observable while ensuring listener cleanup always runs.
        _LOGGER.exception("Unable to subscribe to tracker updates for %s", name)
        try:
            await coordinator.async_shutdown()
        except Exception:
            _LOGGER.exception("Cleanup failed after subscription setup failure for %s", name)
        finally:
            entry.runtime_data = None
        raise

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await coordinator.async_request_refresh()
    except asyncio.CancelledError:
        await _async_cleanup_failed_setup(hass, entry, coordinator)
        raise
    except Exception:
        # Keep entry teardown behavior deterministic before re-raising setup failures.
        _LOGGER.exception("Entry setup failed for %s", name)
        await _async_cleanup_failed_setup(hass, entry, coordinator)
        raise
    return True


async def _async_cleanup_failed_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: PlacesUpdateCoordinator,
) -> None:
    """Best-effort cleanup for setup that did not reach the loaded state.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry whose setup failed.
        coordinator (PlacesUpdateCoordinator):
            Coordinator created for the failed setup attempt.
    """
    try:
        await coordinator.async_prepare_unload()
    except Exception:
        # HA cleanup hooks can raise arbitrary integration errors; setup still failed.
        _LOGGER.exception(
            "Places setup cleanup step prepare_unload failed for entry %s coordinator %r",
            entry.entry_id,
            coordinator,
        )

    try:
        unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception:
        # Platform cleanup can raise arbitrary integration errors; setup still failed.
        _LOGGER.exception(
            "Places setup cleanup step unload_platforms failed for entry %s coordinator %r",
            entry.entry_id,
            coordinator,
        )
    else:
        if not unload_ok:
            _LOGGER.warning(
                "Places setup cleanup step unload_platforms returned false for entry %s "
                "coordinator %r",
                entry.entry_id,
                coordinator,
            )

    try:
        await coordinator.async_shutdown()
    except Exception:
        # Shutdown is best-effort here; do not mask the original setup failure.
        _LOGGER.exception(
            "Places setup cleanup step shutdown failed for entry %s coordinator %r",
            entry.entry_id,
            coordinator,
        )
    finally:
        entry.runtime_data = None


async def _async_resume_failed_unload(
    entry: ConfigEntry,
    coordinator: PlacesUpdateCoordinator,
) -> None:
    """Best-effort resume for entries that remain loaded after unload failure.

    Args:
        entry (ConfigEntry):
            Config entry whose unload failed.
        coordinator (PlacesUpdateCoordinator):
            Coordinator that still owns runtime state.
    """
    try:
        await coordinator.async_resume_after_failed_unload()
    except Exception:
        # Resume is recovery from an unload failure; do not mask the unload result.
        _LOGGER.exception(
            "Places unload step resume_after_failed_unload failed for entry %s coordinator %r",
            entry.entry_id,
            coordinator,
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Places config entry.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry to unload.

    Returns:
        bool:
            ``True`` when all Places platforms unload successfully.

    Raises:
        Exception:
            Propagated from coordinator unload preparation or platform unload;
            coordinator shutdown errors are logged and suppressed.
    """
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    _LOGGER.info("Unloading Places entry: %s", entry.entry_id)
    coordinator = entry.runtime_data
    if coordinator is not None:
        try:
            await coordinator.async_prepare_unload()
        except Exception:
            # Unload hooks can surface arbitrary failures; resume before re-raising.
            _LOGGER.exception(
                "Places unload step prepare_unload failed for entry %s coordinator %r",
                entry.entry_id,
                coordinator,
            )
            await _async_resume_failed_unload(entry, coordinator)
            raise
    try:
        unload_ok: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception:
        if coordinator is not None:
            # Platform unload can raise arbitrary integration errors; resume before re-raising.
            _LOGGER.exception(
                "Places unload step unload_platforms failed for entry %s coordinator %r",
                entry.entry_id,
                coordinator,
            )
            await _async_resume_failed_unload(entry, coordinator)
        raise

    if not unload_ok:
        if coordinator is not None:
            await _async_resume_failed_unload(entry, coordinator)
        return False

    try:
        if coordinator is not None:
            await coordinator.async_shutdown()
    except Exception:
        # Platforms are already unloaded, so teardown is terminal even if
        # coordinator cleanup fails. Do not leave HA in FAILED_UNLOAD with no
        # entities or usable runtime data.
        _LOGGER.exception(
            "Places unload step shutdown failed for entry %s coordinator %r",
            entry.entry_id,
            coordinator,
        )
    finally:
        entry.runtime_data = None

    return True


async def async_remove_extended_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the optional extended-data sensor registry entry if it exists.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry whose extended-data entity should be removed.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR,
        DOMAIN,
        f"{entry.entry_id}_extended_data",
    )
    if entity_id is not None:
        registry.async_remove(entity_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove config-entry specific persisted state.

    Args:
        hass (HomeAssistant):
            Home Assistant instance.
        entry (ConfigEntry):
            Config entry being removed.

    Returns:
        bool:
            ``True`` after best-effort persisted-state cleanup completes.
    """
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
