"""Tests for Store-backed Places persistence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places.const import (
    ATTR_CITY,
    ATTR_DEVICETRACKER_ID,
    ATTR_JSON_FILENAME,
    ATTR_NATIVE_VALUE,
)
from custom_components.places.persistence import PlacesStorage, legacy_json_path, normalize_snapshot


def test_normalize_snapshot_keeps_json_attributes_and_native_value() -> None:
    """Persist only attributes that are valid for Places restore."""
    snapshot = {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
        ATTR_DEVICETRACKER_ID: "device_tracker.person",
        ATTR_JSON_FILENAME: "places-entry.json",
        "unknown": "ignored",
    }

    normalized = normalize_snapshot(snapshot)

    assert normalized == {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
    }


def test_normalize_snapshot_omits_datetime_values() -> None:
    """Datetime values are omitted to preserve the current JSON persistence contract."""
    snapshot = {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
        "last_seen": datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    }

    normalized = normalize_snapshot(snapshot)

    assert normalized == {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
    }


def test_normalize_snapshot_coerces_non_json_values() -> None:
    """Non-JSON values for allowed keys are stringified like the old writer fallback."""
    non_json = object()
    snapshot = {ATTR_CITY: non_json}

    normalized = normalize_snapshot(snapshot)

    assert normalized == {ATTR_CITY: str(non_json)}


class _FakeStore:
    """Small Store test double for PlacesStorage."""

    next_data: dict[str, object] | None = None
    last_saved: dict[str, object] | None = None
    remove_calls = 0
    save_error: BaseException | None = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        """Initialize fake Store without Home Assistant storage internals."""

    async def async_load(self) -> dict[str, object] | None:
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
    _FakeStore.last_saved = None
    _FakeStore.save_error = None
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
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    _FakeStore.save_error = None
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
    """Migration preserves legacy JSON when Store persistence fails."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    _FakeStore.save_error = RuntimeError("store save failed")
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = legacy_json_path(hass, "entry-4")
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-4", "Test")

    with pytest.raises(RuntimeError, match="store save failed"):
        await storage.async_load()

    assert legacy_file.exists()
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["{", "[1, 2, 3]"])
async def test_load_removes_invalid_legacy_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """Corrupt and non-mapping legacy JSON files are removed during startup."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    _FakeStore.save_error = None
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
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    _FakeStore.save_error = None
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
    _FakeStore.save_error = None
    hass = _hass_for_legacy_path(tmp_path)

    storage = PlacesStorage(hass, "entry-6", "Test")
    await storage.async_remove()

    assert _FakeStore.remove_calls == 1
