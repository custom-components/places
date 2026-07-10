"""Tests for one-time legacy JSON snapshot migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

from custom_components.places.migration import async_migrate_legacy_snapshot, legacy_json_path
import pytest

from custom_components.places.const import ATTR_CITY


class _FakeStore:
    """Small Store test double for legacy snapshot migration."""

    next_data: object | None = None
    saved: ClassVar[list[dict[str, object]]] = []
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
        self.atomic_writes = atomic_writes
        self.serialize_in_event_loop = serialize_in_event_loop

    async def async_load(self) -> object | None:
        """Return configured Store data."""
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

    result = await async_migrate_legacy_snapshot(hass, "entry 1", "Test Place")

    assert result is None
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

    result = await async_migrate_legacy_snapshot(hass, "entry-2", "Test Place")

    assert result is None
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

    result = await async_migrate_legacy_snapshot(hass, "entry-3", "Test Place")

    assert result is None
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

    result = await async_migrate_legacy_snapshot(hass, "entry-4", "Test Place")

    assert result is None
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

    result = await async_migrate_legacy_snapshot(hass, "entry-5", "Test Place")

    assert result is None
    cleanup.assert_called_once_with(path, "Test Place")
