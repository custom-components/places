"""Tests for one-time legacy JSON snapshot migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.places.const import ATTR_CITY
from custom_components.places.migration import async_migrate_legacy_snapshot, legacy_json_path


class _FakeStore:
    """Small Store test double for legacy snapshot migration."""

    next_data: object | None = None
    saved: ClassVar[list[dict[str, object]]] = []
    load_error: ClassVar[Exception | None] = None
    save_error: OSError | None = None

    def __init__(
        self,
        _hass: MagicMock,
        _version: int,
        _key: str,
        *,
        atomic_writes: bool,
        serialize_in_event_loop: bool,
    ) -> None:
        """Initialize the fake with the Store constructor contract."""
        _ = atomic_writes, serialize_in_event_loop

    async def async_load(self) -> object | None:
        """Return configured Store data."""
        load_error = type(self).load_error
        if load_error is not None:
            raise load_error
        return type(self).next_data

    async def async_save(self, data: dict[str, object]) -> None:
        """Record saved data or raise the configured write error."""
        save_error = type(self).save_error
        if save_error is not None:
            raise save_error
        type(self).saved.append(data)


@pytest.fixture(autouse=True)
def reset_fake_store_state() -> None:
    """Reset shared fake Store state for each test."""
    _FakeStore.next_data = None
    _FakeStore.saved = []
    _FakeStore.load_error = None
    _FakeStore.save_error = None


def _hass_for_legacy_path(tmp_path: Path) -> MagicMock:
    """Return a Home Assistant mock with config path and executor passthrough."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


def _write_legacy_snapshot(path: Path, contents: str) -> None:
    """Write a legacy snapshot and create its containing folder."""
    path.parent.mkdir(parents=True)
    path.write_text(contents)


@pytest.mark.asyncio
async def test_valid_snapshot_is_saved_then_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid legacy object is normalized, saved, and removed."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry 1")
    _write_legacy_snapshot(
        path,
        json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}),
    )

    await async_migrate_legacy_snapshot(hass, "entry 1", "Test Place")

    assert _FakeStore.saved == [{ATTR_CITY: "Legacy City"}]
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", ["{", json.dumps(["not", "an", "object"])])
async def test_unusable_snapshot_is_removed_without_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    """Malformed and non-object snapshots are discarded without a Store write."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-2")
    _write_legacy_snapshot(path, contents)

    await async_migrate_legacy_snapshot(hass, "entry-2", "Test Place")

    assert _FakeStore.saved == []
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_invalid_utf8_snapshot_is_removed_without_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot containing invalid UTF-8 is discarded without a Store write."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-invalid-utf8")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff")

    await async_migrate_legacy_snapshot(hass, "entry-invalid-utf8", "Test Place")

    assert _FakeStore.saved == []
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_store_write_error_still_removes_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Store write failure does not leave the legacy source behind."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    _FakeStore.save_error = OSError("write failed")
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-3")
    _write_legacy_snapshot(path, json.dumps({ATTR_CITY: "Legacy City"}))

    await async_migrate_legacy_snapshot(hass, "entry-3", "Test Place")

    assert _FakeStore.saved == []
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "load_error",
    [
        HomeAssistantError("load failed"),
        KeyError("version"),
        NotImplementedError("migration unsupported"),
    ],
    ids=["home-assistant", "missing-version", "unsupported-migration"],
)
async def test_store_load_error_still_removes_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, load_error: Exception
) -> None:
    """A Store load failure does not leave the legacy source behind."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    _FakeStore.load_error = load_error
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-load-error")
    _write_legacy_snapshot(path, json.dumps({ATTR_CITY: "Legacy City"}))

    await async_migrate_legacy_snapshot(hass, "entry-load-error", "Test Place")

    assert _FakeStore.saved == []
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_existing_store_data_wins_and_legacy_snapshot_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing Store data prevents stale JSON from being saved."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    _FakeStore.next_data = {}
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-4")
    _write_legacy_snapshot(path, json.dumps({ATTR_CITY: "Legacy City"}))

    await async_migrate_legacy_snapshot(hass, "entry-4", "Test Place")

    assert _FakeStore.saved == []
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_cleanup_error_is_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cleanup failure is swallowed after one removal attempt."""
    monkeypatch.setattr("custom_components.places.migration.Store", _FakeStore)
    cleanup = MagicMock(side_effect=OSError("cleanup failed"))
    monkeypatch.setattr("custom_components.places.migration._remove_legacy_snapshot", cleanup)
    hass = _hass_for_legacy_path(tmp_path)
    path = legacy_json_path(hass, "entry-5")
    _write_legacy_snapshot(path, json.dumps({ATTR_CITY: "Legacy City"}))

    await async_migrate_legacy_snapshot(hass, "entry-5", "Test Place")

    cleanup.assert_called_once_with(path, "Test Place")
