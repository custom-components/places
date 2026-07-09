"""Store-backed persistence for Places sensor snapshots."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from .const import ATTR_NATIVE_VALUE, DOMAIN, PERSISTED_ATTRIBUTE_LIST

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
STORE_WRITE_ERRORS = (OSError, TypeError, ValueError, SerializationError, WriteError)

type Snapshot = dict[str, Any]


def store_key(entry_id: str) -> str:
    """Return the per-config-entry Store key.

    Args:
        entry_id: Home Assistant config entry ID.

    Returns:
        Stable Store key for this config entry.
    """
    return f"{DOMAIN}.sensor_{slugify(entry_id)}"


def normalize_snapshot(attributes: Mapping[str, Any]) -> Snapshot:
    """Prepare sensor attributes for persistence.

    Args:
        attributes: Runtime sensor attribute mapping.

    Returns:
        JSON-compatible snapshot containing only restorable Places attributes.
    """
    allowed = set(PERSISTED_ATTRIBUTE_LIST)
    allowed.add(ATTR_NATIVE_VALUE)
    normalized: Snapshot = {}
    for key, value in attributes.items():
        if key not in allowed or isinstance(value, datetime):
            continue
        try:
            serialized_value = json.dumps(value)
        except TypeError, ValueError:
            normalized[key] = str(value)
        else:
            normalized[key] = json.loads(serialized_value)
    return normalized


class PlacesStorage:
    """Persist Places sensor snapshots with Home Assistant Store."""

    def __init__(self, hass: HomeAssistant, entry_id: str, name: str) -> None:
        """Initialize Store persistence for one Places config entry.

        Args:
            hass: Home Assistant instance.
            entry_id: Config entry ID used for Store naming.
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
            serialize_in_event_loop=False,
        )

    async def async_load(self) -> MutableMapping[str, Any]:
        """Load a persisted snapshot.

        Returns:
            Persisted attribute mapping, or an empty mapping when no valid
            snapshot exists.
        """
        store_data = await self._store.async_load()
        if store_data is not None:
            if not isinstance(store_data, Mapping):
                _LOGGER.debug(
                    "(%s) Invalid Store snapshot root is %s, expected mapping: %s",
                    self._name,
                    type(store_data).__name__,
                    store_key(self._entry_id),
                )
                try:
                    await self._store.async_remove()
                except STORE_WRITE_ERRORS as error:
                    _LOGGER.warning(
                        "(%s) Could not remove invalid Store snapshot (%s): %s: %s",
                        self._name,
                        store_key(self._entry_id),
                        type(error).__name__,
                        error,
                    )
            else:
                return dict(store_data)
        return {}

    async def async_save(self, attributes: Mapping[str, Any]) -> None:
        """Persist the current sensor attributes immediately.

        Args:
            attributes: Runtime sensor attribute mapping to save.
        """
        await self._store.async_save(normalize_snapshot(attributes))

    async def async_remove(self) -> None:
        """Remove Store data for a deleted config entry."""
        await self._store.async_remove()
