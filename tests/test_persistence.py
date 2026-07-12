"""Tests for Store-backed Places persistence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places.const import (
    ATTR_CITY,
    ATTR_DEVICETRACKER_ID,
    ATTR_LAST_UPDATED,
    ATTR_NATIVE_VALUE,
    ATTR_OSM_DICT,
)
from custom_components.places.persistence import PlacesStorage, normalize_snapshot, store_key


def test_normalize_snapshot_keeps_persisted_attributes_and_native_value() -> None:
    """Persist only attributes that are valid for Places restore."""
    snapshot = {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
        ATTR_DEVICETRACKER_ID: "device_tracker.person",
        "unknown": "ignored",
    }

    normalized = normalize_snapshot(snapshot)

    assert normalized == {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
    }


def test_normalize_snapshot_omits_datetime_values() -> None:
    """Datetime values are omitted from persisted snapshots."""
    snapshot = {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
        ATTR_LAST_UPDATED: datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    }

    normalized = normalize_snapshot(snapshot)

    assert normalized == {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
    }


def test_normalize_snapshot_coerces_non_serializable_values() -> None:
    """Non-serializable values for allowed keys are stringified."""
    non_json = object()
    snapshot = {ATTR_CITY: non_json}

    normalized = normalize_snapshot(snapshot)

    assert normalized == {ATTR_CITY: str(non_json)}


def test_normalize_snapshot_copies_nested_values() -> None:
    """Nested snapshot values are isolated before executor-thread serialization."""
    osm_dict = {"address": {"city": "Original"}}
    normalized = normalize_snapshot({ATTR_OSM_DICT: osm_dict})

    osm_dict["address"]["city"] = "Mutated"

    assert normalized == {ATTR_OSM_DICT: {"address": {"city": "Original"}}}


class _FakeStore:
    """Small Store test double for PlacesStorage."""

    next_data: object | None = None
    last_saved: dict[str, object] | None = None
    remove_calls = 0
    remove_error: BaseException | None = None
    init_calls: ClassVar[list[tuple[int, str, bool, bool]]] = []

    def __init__(
        self,
        _hass: MagicMock,
        version: int,
        store_key: str,
        *,
        atomic_writes: bool,
        serialize_in_event_loop: bool = True,
    ) -> None:
        """Initialize fake Store without Home Assistant storage internals."""
        self._hass = _hass
        self._version = version
        self._store_key = store_key
        self.path = str(_hass.config.path(".storage", store_key))
        type(self).init_calls.append((version, store_key, atomic_writes, serialize_in_event_loop))

    async def async_load(self) -> object | None:
        """Return configured fake Store data."""
        return type(self).next_data

    async def async_save(self, data: dict[str, object]) -> None:
        """Record data saved by PlacesStorage."""
        type(self).last_saved = data
        await self._hass.async_add_executor_job(
            _write_fake_store_snapshot,
            Path(self.path),
            {
                "version": self._version,
                "minor_version": 1,
                "key": self._store_key,
                "data": data,
            },
        )

    async def async_remove(self) -> None:
        """Record Store removal."""
        type(self).remove_calls += 1
        remove_error = type(self).remove_error
        if remove_error is not None:
            raise remove_error


@pytest.fixture(autouse=True)
def reset_fake_store_state() -> None:
    """Reset shared fake Store state for each test."""
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    _FakeStore.remove_calls = 0
    _FakeStore.remove_error = None
    _FakeStore.init_calls = []


def _hass_for_store_path(tmp_path: Path) -> MagicMock:
    """Return a Home Assistant mock with config.path and executor passthrough."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


def _write_fake_store_snapshot(path: Path, data: dict[str, object]) -> None:
    """Write a fake Home Assistant Store snapshot to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store_data", "expected"),
    [
        ({ATTR_CITY: "Store City"}, {ATTR_CITY: "Store City"}),
        (None, {}),
    ],
    ids=["existing-store-data", "missing-store-data"],
)
async def test_load_returns_store_data_or_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_data: object | None,
    expected: dict[str, object],
) -> None:
    """Load existing Store data or return an empty mapping when missing."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = store_data
    hass = _hass_for_store_path(tmp_path)

    storage = PlacesStorage(hass, "entry-1", "Test")
    loaded = await storage.async_load()

    assert loaded == expected
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
async def test_remove_deletes_store_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config-entry deletion removes the Store snapshot."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.remove_calls = 0
    hass = _hass_for_store_path(tmp_path)

    storage = PlacesStorage(hass, "entry-6", "Test")
    await storage.async_remove()

    assert _FakeStore.remove_calls == 1


def test_store_key_is_slugified_per_entry() -> None:
    """Store key generation is stable and slugified for config entry IDs."""
    assert store_key("entry-1") == "places.sensor_entry_1"
    assert store_key("entry_1") == "places.sensor_entry_1"


@pytest.mark.asyncio
async def test_places_storage_constructs_store_with_expected_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store construction should use the expected per-entry persistence options."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_store_path(tmp_path)

    storage = PlacesStorage(hass, "entry-1", "Test")
    await storage.async_load()

    assert len(_FakeStore.init_calls) == 1
    version, store_key_value, atomic_writes, serialize_in_event_loop = _FakeStore.init_calls[0]
    assert version == 1
    assert store_key_value == "places.sensor_entry_1"
    assert atomic_writes is True
    assert serialize_in_event_loop is False


@pytest.mark.asyncio
async def test_places_storage_constructs_distinct_store_per_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Different config entries must initialize different Store keys."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_store_path(tmp_path)

    PlacesStorage(hass, "entry-1", "Test")
    PlacesStorage(hass, "entry-2", "Test")
    PlacesStorage(hass, "entry 3", "Test")

    assert len(_FakeStore.init_calls) == 3
    assert _FakeStore.init_calls[0][1] == "places.sensor_entry_1"
    assert _FakeStore.init_calls[1][1] == "places.sensor_entry_2"
    assert _FakeStore.init_calls[2][1] == "places.sensor_entry_3"


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_error", [None, OSError("store remove failed")])
@pytest.mark.parametrize("store_data", [["bad", "payload"], "bad"])
async def test_load_ignores_non_mapping_store_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remove_error: OSError | None,
    store_data: object,
) -> None:
    """Invalid Store snapshots are removed and return empty state."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = store_data
    _FakeStore.remove_error = remove_error
    hass = _hass_for_store_path(tmp_path)

    storage = PlacesStorage(hass, "entry-8", "Test")
    loaded = await storage.async_load()

    assert loaded == {}
    assert _FakeStore.remove_calls == 1
    assert _FakeStore.last_saved is None
