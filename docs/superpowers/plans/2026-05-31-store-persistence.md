# Store Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Places' manual JSON sensor snapshot persistence with Home Assistant `homeassistant.helpers.storage.Store`, while cleaning up legacy JSON snapshots during first Store-backed startup.

**Architecture:** Add a focused persistence module that owns Store load/save/remove behavior and legacy JSON cleanup. `sensor.py` creates one persistence object per config entry, passes it into each `Places` entity, and `PlacesUpdater` persists by calling a sensor method instead of knowing about Store or JSON files. Config entry versioning remains unchanged because this is runtime persistence migration, not config entry schema migration.

**Tech Stack:** Home Assistant custom integration APIs, `homeassistant.helpers.storage.Store`, pytest, pytest-homeassistant-custom-component, ruff/mypy via prek.

---

## File Structure

- Create `custom_components/places/persistence.py`: Store wrapper, legacy JSON loader/remover, snapshot normalization.
- Modify `custom_components/places/sensor.py`: use Store-backed persistence at setup, inject persistence into entities, remove entity-unload JSON deletion, add `async_persist_attributes()`.
- Modify `custom_components/places/update_sensor.py`: replace all JSON executor writes with `await self.sensor.async_persist_attributes()`.
- Modify `custom_components/places/helpers.py`: remove JSON-only persistence helpers after callers/tests are migrated; keep non-persistence helpers.
- Modify `tests/conftest.py`: add `async_persist_attributes = AsyncMock()` to `MockSensor`.
- Create `tests/test_persistence.py`: unit coverage for Store save/load normalization and legacy cleanup behavior.
- Modify `tests/test_sensor.py`: update setup/removal tests from JSON helper expectations to persistence expectations.
- Modify `tests/test_update_sensor.py`: assert updater paths persist through the sensor method.
- Modify `tests/test_helpers.py`: remove JSON persistence tests; keep `is_float`, `clear_since_from_state`, and `safe_truncate` coverage.

## Task 1: Add Store Persistence Module

**Files:**
- Create: `custom_components/places/persistence.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write failing tests for snapshot normalization**

Add `tests/test_persistence.py` with these tests first:

```python
"""Tests for Store-backed Places persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.places.const import (
    ATTR_CITY,
    ATTR_DEVICETRACKER_ID,
    ATTR_NATIVE_VALUE,
)
from custom_components.places.persistence import normalize_snapshot


def test_normalize_snapshot_keeps_json_attributes_and_native_value() -> None:
    """Persist only attributes that are valid for Places restore."""
    snapshot = {
        ATTR_CITY: "New York",
        ATTR_NATIVE_VALUE: "Koreatown",
        ATTR_DEVICETRACKER_ID: "device_tracker.person",
        "json_filename": "places-entry.json",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_persistence.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.places.persistence'`.

- [ ] **Step 3: Implement normalization and Store wrapper skeleton**

Create `custom_components/places/persistence.py`:

```python
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

from .const import (
    ATTR_NATIVE_VALUE,
    DOMAIN,
    JSON_ATTRIBUTE_LIST,
)

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
        except (TypeError, ValueError):
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
            data = json.load(jsonfile)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.debug(
            "(%s) Legacy Places JSON snapshot is not importable (%s): %s: %s",
            name,
            path,
            type(err).__name__,
            err,
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
    except OSError as err:
        _LOGGER.debug(
            "(%s) Could not remove legacy Places JSON snapshot (%s): %s: %s",
            name,
            path,
            type(err).__name__,
            err,
        )
    else:
        _LOGGER.debug("(%s) Removed legacy Places JSON snapshot: %s", name, path)
```

- [ ] **Step 4: Run normalization tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_persistence.py -v
```

Expected: PASS for the three normalization tests.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/persistence.py tests/test_persistence.py
git commit -m "feat: add places Store persistence wrapper"
```

## Task 2: Cover Legacy JSON Migration And Cleanup

**Files:**
- Modify: `tests/test_persistence.py`
- Modify: `custom_components/places/persistence.py`

- [ ] **Step 1: Add Store fake and migration tests**

Append these tests to `tests/test_persistence.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from custom_components.places.persistence import PlacesStorage


class _FakeStore:
    """Small Store test double for PlacesStorage."""

    next_data: dict[str, object] | None = None
    last_saved: dict[str, object] | None = None
    remove_calls = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        """Initialize fake Store without using Home Assistant storage internals."""

    async def async_load(self) -> dict[str, object] | None:
        """Return configured fake Store data."""
        return self.next_data

    async def async_save(self, data: dict[str, object]) -> None:
        """Record data saved by PlacesStorage."""
        self.last_saved = data

    async def async_remove(self) -> None:
        """Record Store removal."""
        self.remove_calls += 1


def _hass_for_legacy_path(tmp_path: Path) -> MagicMock:
    """Return a Home Assistant mock with config.path and executor passthrough."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda *parts: str(tmp_path.joinpath(*parts))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.mark.asyncio
async def test_load_uses_store_and_removes_legacy_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing Store data wins and matching legacy JSON is removed."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = {ATTR_CITY: "Store City"}
    _FakeStore.last_saved = None
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = tmp_path / "custom_components" / "places" / "json_sensors" / "places-entry-1.json"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City"}))

    storage = PlacesStorage(hass, "entry-1", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Store City"}
    assert not legacy_file.exists()
    assert _FakeStore.last_saved is None


@pytest.mark.asyncio
async def test_load_migrates_valid_legacy_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid legacy JSON is normalized, saved to Store, and removed."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = tmp_path / "custom_components" / "places" / "json_sensors" / "places-entry-2.json"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({ATTR_CITY: "Legacy City", "unknown": "ignored"}))

    storage = PlacesStorage(hass, "entry-2", "Test")
    loaded = await storage.async_load()

    assert loaded == {ATTR_CITY: "Legacy City"}
    assert _FakeStore.last_saved == {ATTR_CITY: "Legacy City"}
    assert not legacy_file.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["{", "[1, 2, 3]"])
async def test_load_removes_invalid_legacy_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> None:
    """Corrupt and non-mapping legacy JSON files are removed during startup."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.next_data = None
    _FakeStore.last_saved = None
    hass = _hass_for_legacy_path(tmp_path)
    legacy_file = tmp_path / "custom_components" / "places" / "json_sensors" / "places-entry-3.json"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(payload)

    storage = PlacesStorage(hass, "entry-3", "Test")
    loaded = await storage.async_load()

    assert loaded == {}
    assert _FakeStore.last_saved is None
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_remove_deletes_store_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config-entry deletion removes the Store snapshot."""
    monkeypatch.setattr("custom_components.places.persistence.Store", _FakeStore)
    _FakeStore.remove_calls = 0
    hass = _hass_for_legacy_path(tmp_path)

    storage = PlacesStorage(hass, "entry-4", "Test")
    await storage.async_remove()

    assert _FakeStore.remove_calls == 1
```

- [ ] **Step 2: Run tests and verify behavior**

Run:

```bash
./.venv/bin/python -m pytest tests/test_persistence.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add custom_components/places/persistence.py tests/test_persistence.py
git commit -m "test: cover Places Store legacy migration"
```

## Task 3: Wire Store Persistence Into Sensor Setup

**Files:**
- Modify: `custom_components/places/sensor.py`
- Modify: `tests/test_sensor.py`

- [ ] **Step 1: Update setup test to expect Store persistence**

In `tests/test_sensor.py`, replace the JSON helper monkeypatches in `test_async_setup_entry_places_param` with a fake persistence class:

```python
class _FakePlacesStorage:
    """PlacesStorage test double used by async_setup_entry."""

    instances: list["_FakePlacesStorage"] = []

    def __init__(self, hass: object, entry_id: str, name: str) -> None:
        """Record construction arguments for assertions."""
        self.hass = hass
        self.entry_id = entry_id
        self.name = name
        self.saved: list[dict[str, object]] = []
        self.instances.append(self)

    async def async_load(self) -> dict[str, object]:
        """Return imported attributes for setup."""
        return {"native_value": "Restored"}

    async def async_save(self, attributes: object) -> None:
        """Record saved attributes."""
        self.saved.append(dict(attributes))
```

Then patch setup like this:

```python
_FakePlacesStorage.instances = []
monkeypatch.setattr("custom_components.places.sensor.PlacesStorage", _FakePlacesStorage)
monkeypatch.setattr(f"custom_components.places.sensor.{patched_class}", MagicMock())

await async_setup_entry(hass, config_entry, async_add_entities)

assert _FakePlacesStorage.instances
assert _FakePlacesStorage.instances[0].entry_id == config_entry.entry_id
```

Expected failure before implementation: import/attribute errors because `sensor.py` still imports JSON helpers and does not use `PlacesStorage`.

- [ ] **Step 2: Run setup test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_async_setup_entry_places_param -v
```

Expected: FAIL because `custom_components.places.sensor.PlacesStorage` does not exist.

- [ ] **Step 3: Update `sensor.py` imports and setup**

Change `sensor.py` imports:

```python
from .helpers import is_float
from .persistence import PlacesStorage
```

Remove these imports from `sensor.py`:

```python
ATTR_JSON_FILENAME,
ATTR_JSON_FOLDER,
create_json_folder,
get_dict_from_json_file,
remove_json_file,
```

Replace setup-time JSON loading with Store loading:

```python
    config: MutableMapping[str, Any] = dict(config_entry.data)
    unique_id: str = config_entry.entry_id
    name: str = config[CONF_NAME]
    persistence = PlacesStorage(hass=hass, entry_id=unique_id, name=name)
    imported_attributes: MutableMapping[str, Any] = await persistence.async_load()
```

Pass `persistence=persistence` into both `PlacesNoRecorder(...)` and `Places(...)`.

- [ ] **Step 4: Add persistence to `Places.__init__`**

Update the constructor signature:

```python
    def __init__(
        self,
        hass: HomeAssistant,
        config: MutableMapping[str, Any],
        config_entry: ConfigEntry,
        name: str,
        unique_id: str,
        imported_attributes: MutableMapping[str, Any],
        persistence: PlacesStorage,
    ) -> None:
```

Add to the docstring:

```python
            persistence: Store-backed persistence for this config entry.
```

Set the instance variable after `_hass` is assigned:

```python
        self._persistence = persistence
```

Remove the JSON folder/filename attribute block:

```python
        json_folder: str = hass.config.path("custom_components", DOMAIN, "json_sensors")
        _LOGGER.debug("json_sensors Location: %s", json_folder)
```

and:

```python
        self.set_attr(
            ATTR_JSON_FILENAME,
            f"{DOMAIN}-{slugify(str(self.get_attr(CONF_UNIQUE_ID)))}.json",
        )
        self.set_attr(ATTR_JSON_FOLDER, json_folder)
        _LOGGER.debug(...)
```

- [ ] **Step 5: Rename import method docs without changing import semantics**

Rename `import_attributes_from_json` to `import_persisted_attributes`, and update the call site:

```python
        self.import_persisted_attributes(imported_attributes)
```

Use this method body:

```python
    def import_persisted_attributes(self, persisted_attr: MutableMapping[str, Any]) -> None:
        """Restore persisted runtime attributes from a snapshot.

        Args:
            persisted_attr: Mutable mapping loaded from Store or migrated from
                legacy JSON. Imported and ignored keys are removed from this
                mapping.
        """
        self.set_attr(ATTR_INITIAL_UPDATE, False)
        self._attributes.import_persisted_attributes(persisted_attr)
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)

        if persisted_attr is not None and persisted_attr:
            _LOGGER.debug(
                "(%s) [import_attributes] Attributes not imported: %s",
                self.get_attr(CONF_NAME),
                persisted_attr,
            )
```

Keep a compatibility alias if tests or external callers still use the old method name:

```python
    import_attributes_from_json = import_persisted_attributes
```

- [ ] **Step 6: Add sensor persistence method and update removal**

Add to `Places`:

```python
    async def async_persist_attributes(self) -> None:
        """Persist the current runtime attributes to Home Assistant Store."""
        await self._persistence.async_save(self.get_internal_attr())
```

Remove the JSON deletion from `async_will_remove_from_hass`; the method should start with recorder exclusion cleanup only:

```python
    async def async_will_remove_from_hass(self) -> None:
        """Clean up recorder exclusions before entity removal."""
        if RECORDER_INSTANCE in self._hass.data and self.get_attr(CONF_EXTENDED_ATTR):
            ...
```

- [ ] **Step 7: Run sensor setup/removal tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_sensor.py::test_async_setup_entry_places_param tests/test_sensor.py::test_async_will_remove_from_hass_param tests/test_sensor.py::test_import_attributes_from_json -v
```

Expected: PASS after updating assertions that referenced JSON deletion.

- [ ] **Step 8: Commit**

```bash
git add custom_components/places/sensor.py tests/test_sensor.py
git commit -m "feat: load Places snapshots from Store"
```

## Task 4: Replace Updater JSON Writes With Sensor Persistence

**Files:**
- Modify: `custom_components/places/update_sensor.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_update_sensor.py`

- [ ] **Step 1: Update `MockSensor`**

In `tests/conftest.py`, add this line in `MockSensor.__init__` after `async_cleanup_attributes`:

```python
        self.async_persist_attributes = AsyncMock()
```

- [ ] **Step 2: Update updater tests to assert sensor persistence**

In `tests/test_update_sensor.py::test_handle_state_update_sets_native_value_and_calls_helpers`, replace:

```python
    # write_sensor_to_json is executed via hass.async_add_executor_job
    mock_hass.async_add_executor_job.assert_awaited_once()
```

with:

```python
    sensor.async_persist_attributes.assert_awaited_once()
```

In `test_change_show_time_to_date_param`, add:

```python
    sensor.async_persist_attributes.assert_awaited_once()
```

In `test_change_dot_to_stationary_sets_direction_and_last_changed`, add:

```python
    sensor.async_persist_attributes.assert_awaited_once()
```

- [ ] **Step 3: Run updater tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_update_sensor.py::test_handle_state_update_sets_native_value_and_calls_helpers tests/test_update_sensor.py::test_change_show_time_to_date_param tests/test_update_sensor.py::test_change_dot_to_stationary_sets_direction_and_last_changed -v
```

Expected: FAIL because production code still calls `hass.async_add_executor_job(write_sensor_to_json, ...)`.

- [ ] **Step 4: Replace persistence calls in `update_sensor.py`**

Remove these imports:

```python
    ATTR_JSON_FILENAME,
    ATTR_JSON_FOLDER,
```

Change the helper import from:

```python
from .helpers import clear_since_from_state, is_float, safe_truncate, write_sensor_to_json
```

to:

```python
from .helpers import clear_since_from_state, is_float, safe_truncate
```

In `handle_state_update`, replace:

```python
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self.sensor.get_internal_attr(),
            self.sensor.get_attr_safe_str(CONF_NAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FILENAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FOLDER),
        )
```

with:

```python
        await self.sensor.async_persist_attributes()
```

Make the same replacement in `change_show_time_to_date` and `change_dot_to_stationary`.

- [ ] **Step 5: Run updater tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_update_sensor.py::test_handle_state_update_sets_native_value_and_calls_helpers tests/test_update_sensor.py::test_change_show_time_to_date_param tests/test_update_sensor.py::test_change_dot_to_stationary_sets_direction_and_last_changed -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/places/update_sensor.py tests/conftest.py tests/test_update_sensor.py
git commit -m "feat: persist Places updates through Store"
```

## Task 5: Remove Old JSON Helper Surface

**Files:**
- Modify: `custom_components/places/helpers.py`
- Modify: `tests/test_helpers.py`
- Modify: `custom_components/places/const.py`
- Modify: `tests/test_display_options_integration.py`

- [ ] **Step 1: Remove JSON helper tests**

In `tests/test_helpers.py`, remove imports of:

```python
import json
from datetime import UTC, datetime
from pathlib import Path
```

when they are no longer used by remaining tests.

Remove these tests:

```python
test_create_json_folder_param
test_get_dict_from_json_file_param
test_get_dict_from_json_file_returns_empty_dict_for_invalid_json
test_get_dict_from_json_file_returns_empty_dict_for_non_mapping_root
test_remove_json_file_param
test_write_sensor_to_json_excludes_datetime
test_write_sensor_to_json_coerces_non_serializable_values
test_write_read_and_remove_json_file
```

Keep the tests for:

```python
test_clear_since_from_state_removes_pattern
test_safe_truncate
test_is_float_param
```

- [ ] **Step 2: Remove old helper functions**

In `custom_components/places/helpers.py`, remove these imports:

```python
from collections.abc import Mapping, MutableMapping
from datetime import datetime
import json
from os import PathLike
from pathlib import Path
from typing import Any
```

Then remove:

```python
type JsonPath = str | PathLike[str]
create_json_folder
get_dict_from_json_file
remove_json_file
write_sensor_to_json
_coerce_json_attributes
```

Keep only:

```python
"""Parsing and formatting helpers for the Places integration."""

from __future__ import annotations

import re
from typing import Any
```

and the existing `is_float`, `clear_since_from_state`, and `safe_truncate` functions.

- [ ] **Step 3: Remove JSON filename/folder constants if unused**

Run:

```bash
rg -n "ATTR_JSON_FILENAME|ATTR_JSON_FOLDER|json_filename|json_folder" custom_components tests
```

If only `const.py` and stale test fixtures remain, remove from `custom_components/places/const.py`:

```python
ATTR_JSON_FILENAME = "json_filename"
ATTR_JSON_FOLDER = "json_folder"
```

and remove them from `JSON_IGNORE_ATTRIBUTE_LIST`.

In `tests/test_display_options_integration.py`, remove these fixture keys from the hard-coded snapshot:

```python
"json_filename": "...",
"json_folder": "...",
```

- [ ] **Step 4: Run helper and display tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_helpers.py tests/test_display_options_integration.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/places/helpers.py custom_components/places/const.py tests/test_helpers.py tests/test_display_options_integration.py
git commit -m "refactor: remove legacy JSON persistence helpers"
```

## Task 6: Full Validation And Cleanup

**Files:**
- Verify all changed files.

- [ ] **Step 1: Search for stale JSON persistence references**

Run:

```bash
rg -n "json_sensors|write_sensor_to_json|get_dict_from_json_file|remove_json_file|create_json_folder|ATTR_JSON_FILENAME|ATTR_JSON_FOLDER|json_filename|json_folder" custom_components tests
```

Expected: no results, except intentional mentions in `custom_components/places/persistence.py` and `tests/test_persistence.py` related to legacy migration cleanup.

- [ ] **Step 2: Run full pytest**

Run:

```bash
./.venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 3: Run full prek**

Run:

```bash
./.venv/bin/python -m prek run -a
```

Expected: PASS. If formatting changes files, inspect them, rerun the focused affected tests, then rerun `./.venv/bin/python -m prek run -a`.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat
git diff
```

Expected: diff is limited to Store persistence, migration cleanup, tests, and direct removal of old JSON helpers.

- [ ] **Step 5: Commit validation cleanup if needed**

If prek or test-driven cleanup changed files after Task 5, commit:

```bash
git add custom_components/places tests
git commit -m "chore: finish Store persistence migration"
```

## Self-Review Notes

- Spec coverage: the plan covers Store-backed persistence, one Store document per config entry, no config entry version bump, immediate saves, existing Store wins and removes legacy JSON, corrupt/non-mapping legacy JSON is removed, valid legacy JSON is migrated then removed, normal entity unload does not remove Store data, and config-entry deletion gets a Store removal API.
- Placeholder scan: no placeholder markers or open-ended implementation steps remain.
- Type consistency: `PlacesStorage`, `normalize_snapshot`, `async_load`, `async_save`, `async_remove`, and `async_persist_attributes` are named consistently across tasks.
