"""Integration tests for the custom_components.places module."""

import asyncio
import logging
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import cachetools
from homeassistant.components.recorder import DATA_INSTANCE
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places import (
    _ensure_osm_runtime_state,
    async_migrate_entry,
    async_remove_entry,
    async_remove_extended_entity,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.places.const import (
    CONF_API_KEY,
    CONF_EXTENDED_ATTR,
    CONF_NAME,
    DOMAIN,
    EVENT_TYPE,
    OSM_CACHE,
    OSM_THROTTLE,
    PLATFORMS,
)
from tests.conftest import MockSensor, assert_awaited_count


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a MockConfigEntry pre-populated with sample data for tests."""
    return MockConfigEntry(domain="places", data={"name": "test", "other": "value"})


@pytest.fixture
def sensitive_entry() -> MockConfigEntry:
    """Return a config entry containing data that must not be logged."""
    return MockConfigEntry(
        domain="places",
        data={CONF_NAME: "test", CONF_API_KEY: "secret@example.com"},
    )


class _FakePlacesStorage:
    """Test double for `PlacesStorage` used to assert removal calls."""

    remove_calls = 0
    remove_calls_args: ClassVar[list[tuple[str, str]]] = []
    remove_error: OSError | None = None

    def __init__(self, hass: object, entry_id: str, name: str) -> None:
        """Record constructor arguments for assertions."""
        self.hass = hass
        self.entry_id = entry_id
        self.name = name

    async def async_remove(self) -> None:
        """Record a removal request from async_remove_entry."""
        remove_error = type(self).remove_error
        if remove_error is not None:
            raise remove_error
        type(self).remove_calls += 1
        type(self).remove_calls_args.append((self.entry_id, self.name))


class _FakeSetupPlacesStorage:
    """Test double for setup-time PlacesStorage interactions."""

    instances: ClassVar[list[_FakeSetupPlacesStorage]] = []
    load_result: ClassVar[dict[str, object]] = {}

    def __init__(self, hass: object, entry_id: str, name: str) -> None:
        """Record constructor arguments for assertions."""
        self.hass = hass
        self.entry_id = entry_id
        self.name = name
        self.instances.append(self)

    async def async_load(self) -> dict[str, object]:
        """Return the configured persisted snapshot for setup tests."""
        return dict(type(self).load_result)


class _FakeCoordinator:
    """Test double for setup and unload coordinator ownership."""

    instances: ClassVar[list[_FakeCoordinator]] = []

    def __init__(
        self,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Record construction arguments and expose async hooks for assertions."""
        self.hass = hass
        self.config_entry = config_entry
        self.imported_attributes = imported_attributes
        self.persistence = persistence
        self.async_added_to_hass = AsyncMock()
        self.async_request_refresh = AsyncMock()
        self.async_prepare_unload = AsyncMock()
        self.async_resume_after_failed_unload = AsyncMock()
        self.async_shutdown = AsyncMock()
        self.instances.append(self)


@pytest.fixture(autouse=True)
def reset_fake_storage() -> None:
    """Reset fake storage accounting for each integration test."""
    _FakePlacesStorage.remove_calls = 0
    _FakePlacesStorage.remove_calls_args = []
    _FakePlacesStorage.remove_error = None
    _FakeSetupPlacesStorage.instances = []
    _FakeSetupPlacesStorage.load_result = {}
    _FakeCoordinator.instances = []


@pytest.mark.asyncio
@pytest.mark.parametrize(("version", "update_calls"), [(1, 1), (2, 0)])
async def test_async_migrate_entry_gates_legacy_snapshot_migration_by_version(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    version: int,
    update_calls: int,
) -> None:
    """Config-entry migration should run only for legacy entry versions."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        data={CONF_NAME: "Test Place"},
    )
    migrate_legacy_snapshot = AsyncMock()
    monkeypatch.setattr(
        "custom_components.places.async_migrate_legacy_snapshot",
        migrate_legacy_snapshot,
    )

    result = await async_migrate_entry(mock_hass, entry)

    assert result is True
    assert migrate_legacy_snapshot.await_count == update_calls
    assert mock_hass.config_entries.async_update_entry.call_count == update_calls
    if version == 1:
        migrate_legacy_snapshot.assert_awaited_once_with(
            mock_hass,
            entry.entry_id,
            "Test Place",
        )
        mock_hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            version=2,
            minor_version=1,
        )


@pytest.mark.asyncio
async def test_async_remove_entry_removes_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Config-entry deletion should remove the per-entry Store snapshot."""
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)

    result = await async_remove_entry(mock_hass, mock_entry)

    assert result is True
    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{mock_entry.entry_id}_extended_data"
    )
    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [
        (mock_entry.entry_id, mock_entry.data[CONF_NAME])
    ]


@pytest.mark.asyncio
async def test_async_remove_entry_uses_entry_id_if_name_missing(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock
) -> None:
    """async_remove_entry should use entry_id when no config entry name exists."""
    entry = MockConfigEntry(domain="places", data={})
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)

    await async_remove_entry(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{entry.entry_id}_extended_data"
    )
    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [(entry.entry_id, entry.entry_id)]


@pytest.mark.asyncio
async def test_async_remove_extended_entity_removes_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Extended-data entity cleanup should remove the registry entry when present."""
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.test_extended_data"
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    entry = MockConfigEntry(domain="places", entry_id="entry123", data={"name": "Test"})

    await async_remove_extended_entity(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", "entry123_extended_data"
    )
    registry.async_remove.assert_called_once_with("sensor.test_extended_data")


@pytest.mark.asyncio
async def test_async_remove_extended_entity_ignores_missing_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Extended-data cleanup should no-op when no registry entry exists."""
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    entry = MockConfigEntry(domain="places", entry_id="entry123", data={"name": "Test"})

    await async_remove_extended_entity(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", "entry123_extended_data"
    )
    registry.async_remove.assert_not_called()


@pytest.mark.asyncio
async def test_async_remove_entry_logs_storage_errors_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry deletion should not be blocked by storage cleanup errors."""
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    _FakePlacesStorage.remove_error = OSError("storage unavailable")

    with caplog.at_level(logging.WARNING, logger="custom_components.places"):
        result = await async_remove_entry(mock_hass, sensitive_entry)

    assert result is True
    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{sensitive_entry.entry_id}_extended_data"
    )
    assert sensitive_entry.entry_id in caplog.text
    assert "storage unavailable" in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_logs_safe_identifier(
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry unload should not log the full entry data mapping."""
    sensitive_entry.runtime_data = _FakeCoordinator(
        mock_hass,
        sensitive_entry,
        {},
        MagicMock(),
    )

    with caplog.at_level(logging.INFO, logger="custom_components.places"):
        await async_unload_entry(mock_hass, sensitive_entry)

    assert sensitive_entry.entry_id in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_async_setup_entry_calls_forward_setups(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Ensure setup creates the coordinator runtime owner and forwards platforms."""
    _FakeSetupPlacesStorage.load_result = {"native_value": "Restored"}
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    call_order: list[str] = []

    async def record_subscription() -> None:
        """Record coordinator subscription before platform forwarding."""
        call_order.append("subscribe")

    async def record_forward(*_args: object, **_kwargs: object) -> None:
        """Record platform forwarding after subscription."""
        call_order.append("forward")

    original_init = _FakeCoordinator.__init__

    def init_with_recorded_subscription(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a recorded async_added_to_hass hook on the fake coordinator."""
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_added_to_hass.side_effect = record_subscription

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_recorded_subscription)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = record_forward

    result = await async_setup_entry(mock_hass, mock_entry)
    await asyncio.sleep(0)

    assert result is True
    assert isinstance(mock_entry.runtime_data, _FakeCoordinator)
    assert isinstance(mock_hass.data[DOMAIN][OSM_CACHE], cachetools.TTLCache)
    assert isinstance(mock_hass.data[DOMAIN][OSM_THROTTLE]["lock"], asyncio.Lock)
    assert mock_hass.data[DOMAIN][OSM_THROTTLE]["last_query"] == 0.0
    assert _FakeSetupPlacesStorage.instances[0].entry_id == mock_entry.entry_id
    assert _FakeSetupPlacesStorage.instances[0].name == mock_entry.data[CONF_NAME]
    assert mock_entry.runtime_data.imported_attributes == {"native_value": "Restored"}
    assert mock_entry.runtime_data.persistence is _FakeSetupPlacesStorage.instances[0]
    mock_entry.runtime_data.async_added_to_hass.assert_awaited_once_with()
    mock_entry.runtime_data.async_request_refresh.assert_awaited_once_with()
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )
    assert call_order == ["subscribe", "forward"]


def test_ensure_osm_runtime_state_preserves_existing_state(mock_hass: MagicMock) -> None:
    """OSM runtime setup should not replace existing shared cache or throttle."""
    cache: dict[str, object] = {"cached": {"ok": True}}
    throttle = {"lock": asyncio.Lock(), "last_query": 42.0}
    mock_hass.data = {
        DOMAIN: {
            OSM_CACHE: cache,
            OSM_THROTTLE: throttle,
        }
    }

    _ensure_osm_runtime_state(mock_hass)

    assert mock_hass.data[DOMAIN][OSM_CACHE] is cache
    assert mock_hass.data[DOMAIN][OSM_THROTTLE] is throttle


@pytest.mark.asyncio
async def test_async_setup_entry_does_not_subscribe_when_platform_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Forwarding failure should unsubscribe the coordinator and clear runtime data."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_raises", [False, True])
async def test_async_setup_entry_clears_runtime_when_platform_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
    cleanup_raises: bool,
) -> None:
    """Forwarding failure cleanup should not resume a never-loaded coordinator."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("setup failed")
    if cleanup_raises:
        mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("cleanup failed")
    else:
        mock_hass.config_entries.async_unload_platforms.return_value = False

    with pytest.raises(RuntimeError, match="setup failed"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_resume_after_failed_unload.assert_not_awaited()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_unloads_platforms_when_initial_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Initial refresh failure should clean up forwarded platforms and runtime state."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    call_order: list[str] = []

    async def raise_refresh_error() -> None:
        """Raise after platforms have been forwarded."""
        raise RuntimeError("refresh boom")

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return True

    async def mark_shutdown() -> None:
        call_order.append("shutdown")

    original_init = _FakeCoordinator.__init__

    def init_with_failing_refresh(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a failing initial refresh hook on the fake coordinator."""
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_request_refresh.side_effect = raise_refresh_error
        self.async_prepare_unload.side_effect = mark_prepare_unload
        self.async_shutdown.side_effect = mark_shutdown

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_failing_refresh)
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    with pytest.raises(RuntimeError, match="refresh boom"):
        await async_setup_entry(mock_hass, entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
    assert entry.runtime_data is None
    assert EVENT_TYPE not in recorder.exclude_event_types
    assert call_order == ["prepare_unload", "unload_platforms", "shutdown"]


@pytest.mark.asyncio
async def test_async_setup_entry_shuts_down_when_subscription_step_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Subscription failure should shutdown the coordinator before any platform unload."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    async def raise_subscription_error() -> None:
        """Raise a subscription error after platform forwarding succeeds."""
        raise RuntimeError("subscribe boom")

    original_init = _FakeCoordinator.__init__

    def init_with_failing_subscription(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a failing async_added_to_hass hook on the fake coordinator."""
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_added_to_hass.side_effect = raise_subscription_error

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_failing_subscription)

    with pytest.raises(RuntimeError, match="subscribe boom"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_with_empty_data(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Setup should fall back to entry_id when no config-entry name exists."""
    entry = MockConfigEntry(domain="places", data={})
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    result = await async_setup_entry(mock_hass, entry)

    assert result is True
    assert isinstance(entry.runtime_data, _FakeCoordinator)
    assert _FakeSetupPlacesStorage.instances[0].name == entry.entry_id


@pytest.mark.asyncio
async def test_async_setup_entry_adds_event_exclusion_for_extended_attributes(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Setup should add `places_state_update` to recorder exclusions when extended mode is enabled."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry)

    assert EVENT_TYPE in recorder.exclude_event_types


@pytest.mark.asyncio
async def test_async_unload_entry_uses_setup_state_when_extended_attr_turns_off(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Unload should remove exclusion even if entry data was changed to false."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry)
    unload_entry = MockConfigEntry(
        domain="places",
        entry_id=entry.entry_id,
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: False,
        },
    )
    unload_entry.runtime_data = entry.runtime_data
    result = await async_unload_entry(mock_hass, unload_entry)

    assert result is True
    assert EVENT_TYPE not in recorder.exclude_event_types


@pytest.mark.asyncio
async def test_async_unload_entry_uses_setup_state_when_extended_attr_turns_on(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Unload should keep exclusion untouched when a previously off entry is turned on."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: False,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry)
    unload_entry = MockConfigEntry(
        domain="places",
        entry_id=entry.entry_id,
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    unload_entry.runtime_data = entry.runtime_data
    result = await async_unload_entry(mock_hass, unload_entry)

    assert result is True
    assert EVENT_TYPE not in recorder.exclude_event_types


@pytest.mark.asyncio
async def test_async_unload_entry_keeps_and_clears_recorder_exclusion_by_active_extended_count(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Unloading one extended entry should keep exclusions until the last extended entry is unloaded."""
    entry_one = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor One",
            "devicetracker_id": "person.one",
            CONF_EXTENDED_ATTR: True,
        },
    )
    entry_two = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor Two",
            "devicetracker_id": "person.two",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry_one)
    await async_setup_entry(mock_hass, entry_two)
    await async_unload_entry(mock_hass, entry_one)
    assert EVENT_TYPE in recorder.exclude_event_types
    await async_unload_entry(mock_hass, entry_two)

    assert EVENT_TYPE not in recorder.exclude_event_types


@pytest.mark.asyncio
@pytest.mark.parametrize(("unload_return", "expected"), [(True, True), (False, False)])
async def test_async_unload_entry_result(
    mock_hass: MagicMock, mock_entry: MockConfigEntry, unload_return: bool, expected: bool
) -> None:
    """Unload should proxy the platform result and only finalize shutdown on success."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    mock_hass.config_entries.async_unload_platforms.return_value = unload_return

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is expected
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    coordinator.async_prepare_unload.assert_awaited_once_with()
    if unload_return:
        coordinator.async_shutdown.assert_awaited_once_with()
        coordinator.async_resume_after_failed_unload.assert_not_awaited()
        assert mock_entry.runtime_data is None
    else:
        coordinator.async_shutdown.assert_not_awaited()
        coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
        assert mock_entry.runtime_data is coordinator


@pytest.mark.asyncio
async def test_async_unload_entry_prepares_unload_before_platform_unload_and_shutdowns_after_success(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Teardown should stop update work before unloading and finalize after success."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    call_order: list[str] = []

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return True

    async def mark_shutdown() -> None:
        call_order.append("shutdown")

    coordinator.async_prepare_unload.side_effect = mark_prepare_unload
    coordinator.async_shutdown.side_effect = mark_shutdown
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is True
    assert call_order == ["prepare_unload", "unload_platforms", "shutdown"]


@pytest.mark.asyncio
async def test_async_unload_entry_clears_owned_state_when_shutdown_raises(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Shutdown failure after platform unload should not leave entry-owned state active."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    await async_setup_entry(mock_hass, entry)
    coordinator = entry.runtime_data
    coordinator.async_shutdown.side_effect = RuntimeError("shutdown boom")

    with pytest.raises(RuntimeError, match="shutdown boom"):
        await async_unload_entry(mock_hass, entry)

    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
    coordinator.async_prepare_unload.assert_awaited_once_with()
    assert entry.runtime_data is None
    assert EVENT_TYPE not in recorder.exclude_event_types


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_platform_unload_fails(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """A failed platform unload should leave the still-loaded coordinator active."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    call_order: list[str] = []

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return False

    async def mark_resume() -> None:
        call_order.append("resume")

    coordinator.async_prepare_unload.side_effect = mark_prepare_unload
    coordinator.async_resume_after_failed_unload.side_effect = mark_resume
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is False
    assert call_order == ["prepare_unload", "unload_platforms", "resume"]
    coordinator.async_shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_prepare_unload_raises(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """A prepare failure should leave the still-loaded coordinator active."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    coordinator.async_prepare_unload.side_effect = RuntimeError("prepare boom")

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.places"),
        pytest.raises(RuntimeError, match="prepare boom"),
    ):
        await async_unload_entry(mock_hass, mock_entry)

    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
    coordinator.async_shutdown.assert_not_awaited()
    assert mock_entry.runtime_data is coordinator
    assert "prepare_unload" in caplog.text
    assert mock_entry.entry_id in caplog.text
    assert repr(coordinator) in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_platform_unload_raises(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """An unload exception should leave the still-loaded coordinator active."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("unload boom")

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.places"),
        pytest.raises(RuntimeError, match="unload boom"),
    ):
        await async_unload_entry(mock_hass, mock_entry)

    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_not_awaited()
    assert "unload_platforms" in caplog.text
    assert mock_entry.entry_id in caplog.text
    assert repr(coordinator) in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_path", "expected_error", "expected_result"),
    [
        ("prepare_exception", "prepare boom", None),
        ("unload_exception", "unload boom", None),
        ("unload_false", None, False),
    ],
)
async def test_async_unload_entry_resume_failure_preserves_unload_result(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
    failure_path: str,
    expected_error: str | None,
    expected_result: bool | None,
) -> None:
    """Resume cleanup failures should not mask the unload terminal state."""
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    coordinator.async_resume_after_failed_unload.side_effect = RuntimeError("resume boom")
    if failure_path == "prepare_exception":
        coordinator.async_prepare_unload.side_effect = RuntimeError("prepare boom")
    elif failure_path == "unload_exception":
        mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("unload boom")
    else:
        mock_hass.config_entries.async_unload_platforms.return_value = False

    with caplog.at_level(logging.ERROR, logger="custom_components.places"):
        if expected_error is not None:
            with pytest.raises(RuntimeError, match=expected_error):
                await async_unload_entry(mock_hass, mock_entry)
        else:
            assert await async_unload_entry(mock_hass, mock_entry) is expected_result

    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_not_awaited()
    assert mock_entry.runtime_data is coordinator
    assert "resume_after_failed_unload" in caplog.text
    assert "resume boom" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_path", "expected_error", "expected_result"),
    [
        ("setup_refresh_exception", "refresh boom", None),
        ("unload_shutdown_exception", "shutdown boom", None),
        ("unload_success", None, True),
    ],
)
async def test_recorder_release_failure_preserves_terminal_state(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    terminal_path: str,
    expected_error: str | None,
    expected_result: bool | None,
) -> None:
    """Recorder release failures should not mask setup or unload terminal state."""
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = set()
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    def fail_release(_hass: MagicMock) -> None:
        raise RuntimeError("release boom")

    if terminal_path == "setup_refresh_exception":
        original_init = _FakeCoordinator.__init__

        def init_with_failing_refresh(
            self: _FakeCoordinator,
            hass: object,
            config_entry: MockConfigEntry,
            imported_attributes: dict[str, object],
            persistence: _FakeSetupPlacesStorage | MagicMock,
        ) -> None:
            """Install a failing initial refresh hook on the fake coordinator."""
            original_init(self, hass, config_entry, imported_attributes, persistence)
            self.async_request_refresh.side_effect = RuntimeError("refresh boom")

        monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_failing_refresh)
    else:
        await async_setup_entry(mock_hass, entry)
        if terminal_path == "unload_shutdown_exception":
            entry.runtime_data.async_shutdown.side_effect = RuntimeError("shutdown boom")

    monkeypatch.setattr("custom_components.places._decrement_extended_attr_ref", fail_release)

    async def run_terminal_path() -> bool:
        """Run the configured setup or unload terminal path."""
        if terminal_path == "setup_refresh_exception":
            return await async_setup_entry(mock_hass, entry)
        return await async_unload_entry(mock_hass, entry)

    with caplog.at_level(logging.ERROR, logger="custom_components.places"):
        if expected_error is not None:
            with pytest.raises(RuntimeError, match=expected_error):
                await run_terminal_path()
        else:
            assert await run_terminal_path() is expected_result

    assert entry.runtime_data is None
    assert "release_extended_attr_ref" in caplog.text
    assert "release boom" in caplog.text


@pytest.mark.asyncio
async def test_mock_sensor_restore_previous_attr_replaces_internal_mapping() -> None:
    """MockSensor should replace attrs entirely instead of merging during restore."""
    sensor = MockSensor(attrs={"keep": "old", "remove": "old"})
    original_attrs = sensor.get_internal_attr()
    previous = {"restored": "state"}

    await sensor.restore_previous_attr(previous)

    assert sensor.get_internal_attr() == previous
    assert sensor.get_internal_attr() is not original_attrs


@pytest.mark.asyncio
async def test_runtime_data_isolation(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Each config entry should receive its own coordinator instance."""
    entry1 = MockConfigEntry(domain="places", data={"name": "entry1"})
    entry2 = MockConfigEntry(domain="places", data={"name": "entry2"})
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)

    assert isinstance(entry1.runtime_data, _FakeCoordinator)
    assert isinstance(entry2.runtime_data, _FakeCoordinator)
    assert entry1.runtime_data is not entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Repeated setup calls should still forward platforms each time."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)

    assert_awaited_count(mock_hass.config_entries.async_forward_entry_setups, 2)


@pytest.mark.asyncio
async def test_async_unload_entry_does_not_remove_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Unloading/reloading an entry should not remove Store state."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    mock_entry.runtime_data = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())

    await async_unload_entry(mock_hass, mock_entry)

    assert _FakePlacesStorage.remove_calls == 0
