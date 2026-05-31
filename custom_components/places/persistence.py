"""Store-backed persistence for Places sensor snapshots."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import ATTR_NATIVE_VALUE, DOMAIN, JSON_ATTRIBUTE_LIST

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1

type Snapshot = dict[str, Any]


def store_key(entry_id: str) -> str:
    """Return the per-config-entry Store key.

    Args:
        entry_id: Home Assistant config entry ID.

    Returns:
        Stable Store key for this config entry.
    """
    return f"{DOMAIN}.sensor_{slugify(entry_id)}"


def legacy_json_path(hass: HomeAssistant, entry_id: str) -> Path:
    """Return the legacy JSON snapshot path for a config entry.

    Args:
        hass: Home Assistant instance.
        entry_id: Home Assistant config entry ID.

    Returns:
        Path to the legacy JSON snapshot file.
    """
    return Path(
        hass.config.path(
            "custom_components",
            DOMAIN,
            "json_sensors",
            f"{DOMAIN}-{slugify(entry_id)}.json",
        )
    )


def normalize_snapshot(attributes: Mapping[str, Any]) -> Snapshot:
    """Prepare sensor attributes for persistence.

    Args:
        attributes: Runtime sensor attribute mapping.

    Returns:
        JSON-compatible snapshot containing only restorable Places attributes.
    """
    allowed = set(JSON_ATTRIBUTE_LIST)
    allowed.add(ATTR_NATIVE_VALUE)
    normalized: Snapshot = {}
    for key, value in attributes.items():
        if key not in allowed or isinstance(value, datetime):
            continue
        try:
            json.dumps(value)
        except TypeError, ValueError:
            normalized[key] = str(value)
        else:
            normalized[key] = value
    return normalized


class PlacesStorage:
    """Persist Places sensor snapshots with Home Assistant Store."""

    def __init__(self, hass: HomeAssistant, entry_id: str, name: str) -> None:
        """Initialize Store persistence for one Places config entry.

        Args:
            hass: Home Assistant instance.
            entry_id: Config entry ID used for Store and legacy file naming.
            name: Sensor name used for contextual logging.
        """
        self._hass = hass
        self._entry_id = entry_id
        self._name = name
        self._store: Store[Snapshot] = Store(
            hass,
            STORE_VERSION,
            store_key(entry_id),
            atomic_writes=True,
        )

    async def async_load(self) -> MutableMapping[str, Any]:
        """Load a persisted snapshot and clean up any legacy JSON file.

        Returns:
            Persisted attribute mapping, or an empty mapping when no valid
            snapshot exists.
        """
        store_data = await self._store.async_load()
        legacy_path = legacy_json_path(self._hass, self._entry_id)
        if store_data is not None:
            await self._async_remove_legacy_json(legacy_path)
            return dict(store_data)

        legacy_data = await self._hass.async_add_executor_job(
            _read_legacy_json,
            legacy_path,
            self._name,
        )
        if legacy_data is None:
            await self._async_remove_legacy_json(legacy_path)
            return {}

        normalized = normalize_snapshot(legacy_data)
        await self._store.async_save(normalized)
        await self._async_remove_legacy_json(legacy_path)
        return dict(normalized)

    async def async_save(self, attributes: Mapping[str, Any]) -> None:
        """Persist the current sensor attributes immediately.

        Args:
            attributes: Runtime sensor attribute mapping to save.
        """
        await self._store.async_save(normalize_snapshot(attributes))

    async def async_remove(self) -> None:
        """Remove Store data for a deleted config entry."""
        await self._store.async_remove()

    async def _async_remove_legacy_json(self, path: Path) -> None:
        """Remove a legacy JSON file if it exists.

        Args:
            path: Legacy JSON file path.
        """
        await self._hass.async_add_executor_job(_remove_legacy_json, path, self._name)


def _read_legacy_json(path: Path, name: str) -> Snapshot | None:
    """Read a legacy JSON snapshot from disk.

    Args:
        path: Legacy JSON file path.
        name: Sensor name used for logging.

    Returns:
        Mapping from a valid legacy file, or ``None`` for missing, corrupt, or
        non-mapping files.
    """
    try:
        with path.open() as jsonfile:
            data: Any = json.load(jsonfile)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        _LOGGER.debug(
            "(%s) Legacy Places JSON snapshot is not importable (%s): %s: %s",
            name,
            path,
            type(error).__name__,
            error,
        )
        return None
    if not isinstance(data, Mapping):
        _LOGGER.debug(
            "(%s) Legacy Places JSON snapshot root is %s, expected mapping: %s",
            name,
            type(data).__name__,
            path,
        )
        return None
    return dict(data)


def _remove_legacy_json(path: Path, name: str) -> None:
    """Remove a legacy JSON snapshot file.

    Args:
        path: Legacy JSON file path.
        name: Sensor name used for logging.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        _LOGGER.debug(
            "(%s) Could not remove legacy Places JSON snapshot (%s): %s: %s",
            name,
            path,
            type(error).__name__,
            error,
        )
    else:
        _LOGGER.debug("(%s) Removed legacy Places JSON snapshot: %s", name, path)
