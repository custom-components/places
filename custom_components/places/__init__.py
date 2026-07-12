"""Initialize Home Assistant places integration."""

import asyncio
from collections.abc import Callable
import logging
import re

import cachetools
from homeassistant.components.recorder import DATA_INSTANCE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_NAME,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DOMAIN,
    EVENT_TYPE,
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
_EXTENDED_ENTRY_COUNT_KEY = "_extended_attr_entry_count"
_EXTENDED_ENTRY_SETUP_STATE_KEY = "_extended_attr_entry_setup_state"

CONFIG_SCHEMA: Callable[[dict], dict] = cv.empty_config_schema(DOMAIN)


def _ensure_osm_runtime_state(hass: HomeAssistant) -> None:
    """Initialize shared OSM cache and throttle state.

    Args:
        hass: Home Assistant instance that owns integration runtime data.
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
        hass: Home Assistant instance.
        entry: Config entry to migrate.

    Returns:
        ``True`` when migration completes.
    """
    if entry.version != 1:
        return True

    name = entry.data.get(CONF_NAME, entry.entry_id)
    await async_migrate_legacy_snapshot(hass, entry.entry_id, name)
    update_kwargs: dict = {"version": 2, "minor_version": 1}
    display_options = entry.data.get(CONF_DISPLAY_OPTIONS, "")
    migrated_display_options = re.sub(
        r"\bformatted_address\b",
        "osm_formatted_address",
        display_options,
        flags=re.IGNORECASE,
    )
    if migrated_display_options != display_options:
        update_kwargs["data"] = {
            **entry.data,
            CONF_DISPLAY_OPTIONS: migrated_display_options,
        }
    display_options = migrated_display_options
    options = [option.strip().lower() for option in display_options.split(",")]
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Places from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry to set up.

    Returns:
        ``True`` when setup completes successfully.
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

    extended_attr_enabled = bool(entry.data.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        hass_data = hass.data.setdefault(DOMAIN, {})
        hass_data.setdefault(_EXTENDED_ENTRY_SETUP_STATE_KEY, {})[entry.entry_id] = (
            extended_attr_enabled
        )
        if extended_attr_enabled:
            _increment_extended_attr_ref(hass)
        await coordinator.async_request_refresh()
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
        hass: Home Assistant instance.
        entry: Config entry whose setup failed.
        coordinator: Coordinator created for the failed setup attempt.
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
        _release_extended_attr_ref(hass, entry.entry_id)


async def _async_resume_failed_unload(
    entry: ConfigEntry,
    coordinator: PlacesUpdateCoordinator,
) -> None:
    """Best-effort resume for entries that remain loaded after unload failure.

    Args:
        entry: Config entry whose unload failed.
        coordinator: Coordinator that still owns runtime state.
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
        hass: Home Assistant instance.
        entry: Config entry to unload.

    Returns:
        ``True`` when all Places platforms unload successfully.
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
    finally:
        entry.runtime_data = None
        _release_extended_attr_ref(hass, entry.entry_id)

    return True


def _release_extended_attr_ref(hass: HomeAssistant, entry_id: str) -> None:
    """Release recorder exclusion state owned by one loaded entry.

    Args:
        hass: Home Assistant instance that owns recorder runtime data.
        entry_id: Config-entry ID whose setup-owned extended state should be released.
    """
    try:
        domain_data = hass.data.get(DOMAIN)
        if not isinstance(domain_data, dict):
            return
        extended_entry_state = domain_data.get(_EXTENDED_ENTRY_SETUP_STATE_KEY, {})
        if not isinstance(extended_entry_state, dict):
            return
        if extended_entry_state.pop(entry_id, False):
            _decrement_extended_attr_ref(hass)
    except Exception:
        # Recorder cleanup must not mask the setup or unload terminal state.
        _LOGGER.exception(
            "Places cleanup step release_extended_attr_ref failed for entry %s",
            entry_id,
        )


def _increment_extended_attr_ref(hass: HomeAssistant) -> None:
    """Track active extended-attributes entries and enable event exclusion.

    Args:
        hass: Home Assistant instance that owns recorder runtime data.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    count = int(domain_data.get(_EXTENDED_ENTRY_COUNT_KEY, 0)) + 1
    domain_data[_EXTENDED_ENTRY_COUNT_KEY] = count
    recorder = hass.data.get(DATA_INSTANCE)
    if recorder is None:
        return
    recorder.exclude_event_types.add(EVENT_TYPE)


def _decrement_extended_attr_ref(hass: HomeAssistant) -> None:
    """Release one active extended-attributes entry and clean up exclusion when last unloads.

    Args:
        hass: Home Assistant instance that owns recorder runtime data.
    """
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return
    count = int(domain_data.get(_EXTENDED_ENTRY_COUNT_KEY, 0)) - 1
    if count > 0:
        domain_data[_EXTENDED_ENTRY_COUNT_KEY] = count
        return
    domain_data.pop(_EXTENDED_ENTRY_COUNT_KEY, None)
    recorder = hass.data.get(DATA_INSTANCE)
    if recorder is None:
        return
    recorder.exclude_event_types.discard(EVENT_TYPE)


async def async_remove_extended_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the optional extended-data sensor registry entry if it exists.

    Args:
        hass: Home Assistant instance.
        entry: Config entry whose extended-data entity should be removed.
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
        hass: Home Assistant instance.
        entry: Config entry being removed.

    Returns:
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
