"""Migrate legacy Places JSON snapshots to Home Assistant Store."""

from __future__ import annotations

from collections.abc import Mapping
import errno
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import ATTR_DISTANCE_FROM_HOME, ATTR_DISTANCE_TRAVELED, DOMAIN
from .persistence import STORE_VERSION, STORE_WRITE_ERRORS, normalize_snapshot, store_key

_LOGGER = logging.getLogger(__name__)


def legacy_json_path(hass: HomeAssistant, entry_id: str) -> Path:
    """Return the legacy JSON snapshot path for a config entry.

    Args:
        hass: Home Assistant instance.
        entry_id: Config entry ID used for the legacy filename.

    Returns:
        Path to the legacy JSON snapshot.
    """
    return Path(
        hass.config.path(
            "custom_components",
            DOMAIN,
            "json_sensors",
            f"{DOMAIN}-{slugify(entry_id)}.json",
        )
    )


def _read_legacy_snapshot(path: Path, name: str) -> Mapping[str, Any] | None:
    """Read a legacy JSON snapshot when it is valid.

    Args:
        path: Legacy JSON snapshot path.
        name: Sensor name used for contextual logging.

    Returns:
        Snapshot mapping, or ``None`` when missing or invalid.

    Raises:
        OSError: If the snapshot cannot be read for a reason other than absence.
    """
    try:
        with path.open(encoding="utf-8") as snapshot_file:
            snapshot = json.load(snapshot_file)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        _LOGGER.warning(
            "(%s) Invalid legacy snapshot (%s): %s: %s",
            name,
            path,
            type(error).__name__,
            error,
        )
        return None

    if not isinstance(snapshot, Mapping):
        _LOGGER.warning(
            "(%s) Invalid legacy snapshot root (%s): %s",
            name,
            path,
            type(snapshot).__name__,
        )
        return None
    return snapshot


def _remove_legacy_snapshot(path: Path, name: str) -> None:
    """Remove a legacy snapshot and its directory when empty.

    Args:
        path: Legacy JSON snapshot path.
        name: Sensor name used for contextual logging.

    """
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        _LOGGER.warning(
            "(%s) Could not remove legacy snapshot (%s): %s: %s",
            name,
            path,
            type(error).__name__,
            error,
        )
        return

    try:
        path.parent.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno != errno.ENOTEMPTY:
            _LOGGER.warning(
                "(%s) Could not remove legacy snapshot directory (%s): %s: %s",
                name,
                path.parent,
                type(error).__name__,
                error,
            )
            return


async def async_migrate_legacy_snapshot(hass: HomeAssistant, entry_id: str, name: str) -> None:
    """Migrate one legacy JSON snapshot to Home Assistant Store.

    Args:
        hass: Home Assistant instance.
        entry_id: Config entry ID used for persistence naming.
        name: Sensor name used for contextual logging.
    """
    path = legacy_json_path(hass, entry_id)
    store: Store[dict[str, Any]] = Store(
        hass,
        STORE_VERSION,
        store_key(entry_id),
        atomic_writes=True,
        serialize_in_event_loop=False,
    )
    try:
        try:
            store_data = await store.async_load()
        except (
            *STORE_WRITE_ERRORS,
            HomeAssistantError,
            KeyError,
            NotImplementedError,
        ) as error:
            _LOGGER.warning(
                "(%s) Could not load Store before migrating %s: %s: %s",
                name,
                path,
                type(error).__name__,
                error,
            )
            return
        if store_data is not None:
            if isinstance(store_data, Mapping):
                return
            _LOGGER.warning(
                "(%s) Invalid Store snapshot root is %s; continuing legacy migration (%s)",
                name,
                type(store_data).__name__,
                path,
            )

        try:
            snapshot = await hass.async_add_executor_job(_read_legacy_snapshot, path, name)
        except OSError as error:
            _LOGGER.warning(
                "(%s) Could not read legacy snapshot (%s): %s: %s",
                name,
                path,
                type(error).__name__,
                error,
            )
            return
        if snapshot is None:
            return

        try:
            snapshot = dict(snapshot)
            if ATTR_DISTANCE_FROM_HOME not in snapshot and "distance_from_home_m" in snapshot:
                snapshot[ATTR_DISTANCE_FROM_HOME] = snapshot["distance_from_home_m"]
            if ATTR_DISTANCE_TRAVELED not in snapshot and "distance_traveled_m" in snapshot:
                snapshot[ATTR_DISTANCE_TRAVELED] = snapshot["distance_traveled_m"]
            await store.async_save(normalize_snapshot(snapshot))
        except STORE_WRITE_ERRORS as error:
            _LOGGER.warning(
                "(%s) Could not save migrated snapshot (%s): %s: %s",
                name,
                path,
                type(error).__name__,
                error,
            )
    finally:
        try:
            await hass.async_add_executor_job(_remove_legacy_snapshot, path, name)
        except OSError as error:
            _LOGGER.warning(
                "(%s) Could not clean up legacy snapshot (%s): %s: %s",
                name,
                path,
                type(error).__name__,
                error,
            )
