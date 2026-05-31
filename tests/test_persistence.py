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
from custom_components.places.persistence import (
    PlacesStorage,
    legacy_json_path,
    normalize_snapshot,
    store_key,
)


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
    save_error: BaseException | None = None
    remove_error: BaseException | None = None
    init_calls: ClassVar[list[tuple[int, str, bool, bool]]] = []

    def __init__(
        self,
        _hass: object,
        version: int,
        store_key: str,
        *,
        atomic_writes: bool,
        serialize_in_event_loop: bool = True,
    ) -> None:
        """Initialize fake Store without Home Assistant storage internals."""
        type(self).init_calls.append((version, store_key, atomic_writes, serialize_in_event_loop))

    async def async_load(self) -> object | None:
        """Return configured fake Store data."""
        return type(self).next_data

    async def async_save(self, data: dict[str, object]) -> None:
        """Record data saved by PlacesStorage."""
        save_error = type(self).save_error
        if save_error is not None:
            raise save_error
        type(self).last_saved = data

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
    _FakeStore.save_error = None
    _FakeStore.remove_error = None
    _FakeStore.init_calls = []


def _hass_for_legacy_path(tmp_path: Path) -> MagicMock:
    """Return a Home Assistant mock with config.path and executor passthrough."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.mark.asyncio
async def test_load_uses_store_and_removes_legacy_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing Store data wins and matching legacy JSON is removed."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = {ATTR_CITY: "Store City"}
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-1")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City"}))

    storage = PlacesStorage(hass, "entry-1", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Store City"}
    assert not legacy_file.exists()
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
async def test_load_migrates_valid_legacy_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid legacy JSON is normalized, saved to Store, and removed."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-2")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-2", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Legacy City"}
    assert _FakeStore.last_saved == {ATTR_CITY: "Legacy City"}
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_load_keeps_legacy_json_when_store_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration returns legacy data and preserves JSON when Store persistence fails."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.save_error = OSError("store save failed")
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-4")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-4", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Legacy City"}
    assert legacy_file.exists()
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["{", "[1, 2, 3]"])
async def test_load_removes_invalid_legacy_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """Corrupt and non-mapping legacy JSON files are removed during startup."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-3")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(payload)

    storage = PlacesStorage(hass, "entry-3", "Test")
    loaded = await storage.async_load()

    assert loaded == {}
    assert _FakeStore.last_saved is None
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_load_missing_legacy_json_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing legacy JSON returns an empty mapping."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)

    storage = PlacesStorage(hass, "entry-5", "Test")
    loaded = await storage.async_load()

    assert loaded == {}
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
async def test_remove_deletes_store_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config-entry deletion removes the Store snapshot."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.remove_calls = 0
    hass = _hass_for_legacy_path(tmp_path)

    storage = PlacesStorage(hass, "entry-6", "Test")
    await storage.async_remove()

    assert _FakeStore.remove_calls == 1


@pytest.mark.asyncio
async def test_remove_deletes_legacy_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config-entry deletion removes unmigrated legacy JSON snapshots."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-6")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City"}))

    storage = PlacesStorage(hass, "entry-6", "Test")
    await storage.async_remove()

    assert _FakeStore.remove_calls == 1
    assert not legacy_file.exists()


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
    hass = _hass_for_legacy_path(tmp_path)

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
    hass = _hass_for_legacy_path(tmp_path)

    PlacesStorage(hass, "entry-1", "Test")
    PlacesStorage(hass, "entry-2", "Test")
    PlacesStorage(hass, "entry 3", "Test")

    assert len(_FakeStore.init_calls) == 3
    assert _FakeStore.init_calls[0][1] == "places.sensor_entry_1"
    assert _FakeStore.init_calls[1][1] == "places.sensor_entry_2"
    assert _FakeStore.init_calls[2][1] == "places.sensor_entry_3"


@pytest.mark.asyncio
async def test_load_degrades_when_legacy_read_raises_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreadable legacy JSON is logged and startup continues with empty data."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    monkeypatch.setattr(
        "custom_components.places.persistence._read_legacy_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-7")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City"}))

    storage = PlacesStorage(hass, "entry-7", "Test")
    loaded = await storage.async_load()
    assert loaded == {}
    assert legacy_file.exists()
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
async def test_load_ignores_non_mapping_store_data_and_migrates_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid Store snapshots are removed and legacy JSON is migrated when available."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = ["bad", "payload"]
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-8")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-8", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Legacy City"}
    assert _FakeStore.remove_calls == 1
    assert _FakeStore.last_saved == {ATTR_CITY: "Legacy City"}
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_load_migrates_legacy_when_invalid_store_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid Store cleanup failures do not prevent legacy JSON migration."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = ["bad", "payload"]
    _FakeStore.remove_error = OSError("store remove failed")
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-8")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-8", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Legacy City"}
    assert _FakeStore.remove_calls == 1
    assert _FakeStore.last_saved == {ATTR_CITY: "Legacy City"}
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_load_ignores_non_mapping_store_data_and_returns_empty_without_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid Store snapshots and missing legacy data result in empty state."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = "bad"
    hass = _hass_for_legacy_path(tmp_path)

    storage = PlacesStorage(hass, "entry-9", "Test")
    loaded = await storage.async_load()

    assert loaded == {}
    assert _FakeStore.remove_calls == 1
