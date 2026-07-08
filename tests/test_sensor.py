"""Tests for coordinator-backed Places sensor entities."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.const import (
    CONF_ZONE,
    MATCH_ALL,
    MAX_LENGTH_STATE_STATE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.entity import EntityCategory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_ATTRIBUTION,
    ATTR_CITY,
    ATTR_DEVICETRACKER_ID,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DRIVING,
    ATTR_GPS_ACCURACY,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_OSM_DETAILS_DICT,
    ATTR_OSM_DICT,
    ATTR_PICTURE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
    ATTR_WIKIDATA_DICT,
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_NAME,
    DOMAIN,
)
from custom_components.places.coordinator import SCAN_INTERVAL, PlacesData, PlacesUpdateCoordinator
from custom_components.places.entity import (
    PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS,
    PlacesAttributeSensorEntityDescription,
    PlacesEntity,
)
from custom_components.places.sensor import (
    Places,
    PlacesAttributeSensor,
    PlacesExtendedDataSensor,
    async_setup_entry,
)


def _description(key: str) -> PlacesAttributeSensorEntityDescription:
    """Return one Places child sensor description by key."""
    return next(
        description
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
        if description.key == key
    )


def test_places_data_copies_attributes() -> None:
    """Coordinator data snapshots should not expose mutable internal state."""
    source = {ATTR_LATITUDE: 1.25}
    data = PlacesData(native_value="Library", attributes=source)
    source[ATTR_LATITUDE] = 9.5

    assert data.attributes == {ATTR_LATITUDE: 1.25}


def test_places_entity_device_info_uses_config_entry(mock_hass: MagicMock) -> None:
    """All Places entities for one entry should group under one HA Device."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = Places(coordinator)

    assert entity.device_info == {
        "identifiers": {("places", "entry123")},
        "name": "TestSensor",
        "manufacturer": "Places",
        "model": "OpenStreetMap reverse geocode",
    }


def test_coordinator_main_attributes_are_location_context_only(
    mock_hass: MagicMock,
) -> None:
    """The display sensor should expose only location-context attributes."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr(ATTR_LATITUDE, 1.25)
    coordinator.set_attr(ATTR_LONGITUDE, -2.5)
    coordinator.set_attr(ATTR_GPS_ACCURACY, 8.0)
    coordinator.set_attr(ATTR_PICTURE, "/local/person.png")
    coordinator.set_attr(ATTR_ATTRIBUTION, "OpenStreetMap")
    coordinator.set_attr(ATTR_CITY, "Richmond")

    assert coordinator.main_state_attributes == {
        ATTR_LATITUDE: 1.25,
        ATTR_LONGITUDE: -2.5,
        ATTR_GPS_ACCURACY: 8.0,
        ATTR_PICTURE: "/local/person.png",
        ATTR_ATTRIBUTION: "OpenStreetMap",
    }


async def test_coordinator_tsc_update_schedules_updater_with_snapshot(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tracker state changes should schedule one updater task with copied attrs."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("place_name", "Library")
    captured: dict[str, object] = {}

    class _FakeUpdater:
        """Capture coordinator update scheduling arguments."""

        def __init__(self, **kwargs: object) -> None:
            """Store constructor arguments for assertions."""
            captured.update(kwargs)

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Capture scheduled update arguments."""
            captured["reason"] = reason
            captured["previous_attr"] = previous_attr

    tasks: list[asyncio.Task[None]] = []

    def _create_task(coro: Coroutine[object, object, None]) -> asyncio.Task[None]:
        """Schedule the coroutine on the active event loop for the test."""
        task: asyncio.Task[None] = asyncio.create_task(coro)
        tasks.append(task)
        return task

    mock_hass.async_create_task.side_effect = _create_task
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", _FakeUpdater)

    coordinator.tsc_update(MagicMock(data={"new_state": MagicMock(state="home")}))
    await asyncio.gather(*tasks)

    assert captured["hass"] is mock_hass
    assert captured["config_entry"] is entry
    assert captured["coordinator"] is coordinator
    assert captured["reason"] == "Track State Change"
    previous_attr = captured["previous_attr"]
    assert isinstance(previous_attr, dict)
    assert previous_attr["place_name"] == "Library"
    assert previous_attr[ATTR_DEVICETRACKER_ID] == "person.test"
    assert previous_attr["name"] == "TestSensor"
    assert previous_attr is not coordinator.get_internal_attr()


async def test_coordinator_tsc_update_cancelled_on_shutdown(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tracker updates should be cancelled and awaited when the coordinator shuts down."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    updater_state: dict[str, bool | asyncio.Event] = {
        "constructed": False,
        "entered": False,
        "cancelled": asyncio.Event(),
    }

    class SlowUpdater:
        """Tracker updater that verifies construction and cancellation."""

        def __init__(self, **kwargs: object) -> None:
            """Record updater construction."""
            updater_state["constructed"] = True

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Wait long enough for coordinator shutdown to cancel the running task."""
            updater_state["entered"] = True
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                updater_state["cancelled"].set()
                raise

    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", SlowUpdater)

    coordinator.tsc_update(MagicMock(data={"new_state": MagicMock(state="home")}))
    await asyncio.sleep(0)
    assert coordinator._tracker_update_tasks
    assert updater_state["constructed"] is True
    assert updater_state["entered"] is True

    await coordinator.async_shutdown()
    assert await asyncio.wait_for(updater_state["cancelled"].wait(), timeout=1.0)
    assert coordinator._tracker_update_tasks == set()


async def test_coordinator_resume_after_failed_unload_resubscribes(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed unload recovery should restart tracker listening and refresh state."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    old_unsubscribe = MagicMock()
    new_unsubscribe = MagicMock()
    coordinator._tracker_unsubscribe = old_unsubscribe
    coordinator.async_request_refresh = AsyncMock()
    captured: dict[str, object] = {}

    def track_state_change(hass: object, entity_ids: list[str], callback: object) -> MagicMock:
        """Record tracker subscription arguments."""
        captured["hass"] = hass
        captured["entity_ids"] = entity_ids
        captured["callback"] = callback
        return new_unsubscribe

    monkeypatch.setattr(
        "custom_components.places.coordinator.async_track_state_change_event",
        track_state_change,
    )

    await coordinator.async_prepare_unload()
    await coordinator.async_resume_after_failed_unload()

    old_unsubscribe.assert_called_once_with()
    assert coordinator.is_shutting_down is False
    assert coordinator._tracker_unsubscribe is new_unsubscribe
    assert captured == {
        "hass": mock_hass,
        "entity_ids": ["person.test"],
        "callback": coordinator.tsc_update,
    }
    coordinator.async_request_refresh.assert_awaited_once_with()


async def test_coordinator_resume_after_failed_unload_forces_refresh(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed unload recovery should refresh even inside the scan throttle window."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator._is_shutting_down = True
    coordinator._last_scan_update = 1000.0
    coordinator.async_request_refresh = AsyncMock(side_effect=coordinator.async_scan_update)
    update_calls: list[str] = []

    class RecordingUpdater:
        """Updater that records recovery refresh execution."""

        def __init__(self, **kwargs: object) -> None:
            """Accept production updater constructor kwargs."""

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Record the refresh reason."""
            update_calls.append(reason)

    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: 1001.0)
    monkeypatch.setattr(
        "custom_components.places.coordinator.async_track_state_change_event",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", RecordingUpdater)

    await coordinator.async_resume_after_failed_unload()

    assert update_calls == ["Scan Interval"]


async def test_coordinator_prepare_unload_waits_for_active_update(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unload preparation should wait for any active coordinator update."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    update_started = asyncio.Event()
    release_update = asyncio.Event()

    class SlowUpdater:
        """Updater that keeps the coordinator update lock occupied."""

        def __init__(self, **kwargs: object) -> None:
            """Accept production updater constructor kwargs."""

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Block until the test releases the active update."""
            update_started.set()
            await release_update.wait()

    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", SlowUpdater)

    update_task = asyncio.create_task(coordinator._run_update("Scan Interval"))
    await update_started.wait()
    prepare_task = asyncio.create_task(coordinator.async_prepare_unload())
    await asyncio.sleep(0)

    assert prepare_task.done() is False

    release_update.set()
    await asyncio.wait_for(prepare_task, timeout=1.0)
    await update_task


async def test_coordinator_scan_update_runs_updater_with_snapshot(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scan interval refreshes should run the updater with copied attrs."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("place_name", "Library")
    captured: dict[str, object] = {}

    class _FakeUpdater:
        """Capture scan update arguments and mutate coordinator state."""

        def __init__(self, **kwargs: object) -> None:
            """Store constructor arguments for assertions."""
            captured.update(kwargs)

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Capture scheduled update arguments and publish a new value."""
            captured["reason"] = reason
            captured["previous_attr"] = previous_attr
            coordinator.set_native_value("Updated")

    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: 1000.0)
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", _FakeUpdater)

    data = await coordinator.async_scan_update()

    assert coordinator.update_interval == SCAN_INTERVAL
    assert data.native_value == "Updated"
    assert captured["hass"] is mock_hass
    assert captured["config_entry"] is entry
    assert captured["coordinator"] is coordinator
    assert captured["reason"] == "Scan Interval"
    previous_attr = captured["previous_attr"]
    assert isinstance(previous_attr, dict)
    assert previous_attr["place_name"] == "Library"
    assert previous_attr is not coordinator.get_internal_attr()


async def test_coordinator_scan_update_failure_still_sets_throttle_marker(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scan failures should still set the throttle marker and suppress immediate retries."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    call_tracker: dict[str, int] = {"constructors": 0}

    class _FailingUpdater:
        """Updater that always fails for scan attempts."""

        def __init__(self, **kwargs: object) -> None:
            """Track updater instantiation for throttle assertions."""
            call_tracker["constructors"] += 1
            _ = kwargs

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Raise a deterministic failure."""
            raise RuntimeError("scan failed")

    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: 1000.0)
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", _FailingUpdater)

    with pytest.raises(RuntimeError, match="scan failed"):
        await coordinator.async_scan_update()

    assert coordinator._last_scan_update == 1000.0

    data = await coordinator.async_scan_update()

    assert data is not None
    assert call_tracker["constructors"] == 1


async def test_coordinator_scan_update_throttles_repeated_refreshes(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scan interval refreshes inside the throttle window should reuse data."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_native_value("Restored")
    coordinator._last_scan_update = 1000.0
    updater_ctor = MagicMock()
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: 1200.0)
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", updater_ctor)

    data = await coordinator.async_scan_update()

    assert data.native_value == "Restored"
    updater_ctor.assert_not_called()


async def test_coordinator_run_update_recheck_after_lock_on_shutdown(
    mock_hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutting down should block queued _run_update executions behind the lock."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_ran = asyncio.Event()
    construct_calls: list[int] = []

    class _FakeUpdater:
        """Update stub that blocks the first call to create a lock queue."""

        def __init__(self, **kwargs: object) -> None:
            """Track constructor calls by sequence number."""
            construct_calls.append(len(construct_calls) + 1)
            self._index = len(construct_calls)

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Block first run and let any later run flag itself."""
            if self._index == 1:
                first_started.set()
                await release_first.wait()
            else:
                second_ran.set()

    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", _FakeUpdater)

    first_task = asyncio.create_task(coordinator._run_update("first"))
    await first_started.wait()
    second_task = asyncio.create_task(coordinator._run_update("second"))
    await asyncio.sleep(0)
    shutdown_task = asyncio.create_task(coordinator.async_shutdown())
    await asyncio.sleep(0)
    release_first.set()

    await asyncio.gather(first_task, second_task, shutdown_task)

    assert len(construct_calls) == 1
    assert not second_ran.is_set()


async def test_coordinator_updates_are_serialized_between_scan_and_tracker_events(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialized update path should prevent concurrent mutation races."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    created_tasks: list[asyncio.Task[None]] = []

    class FakeUpdater:
        """Concurrent execution counter for update calls."""

        active_count = 0
        max_active_count = 0

        def __init__(self, **kwargs: object) -> None:
            """Capture constructor kwargs for parity with the production path."""

        async def do_update(self, reason: str, previous_attr: dict[str, object]) -> None:
            """Record concurrent overlap while the update is in-flight."""
            FakeUpdater.active_count += 1
            FakeUpdater.max_active_count = max(
                FakeUpdater.max_active_count, FakeUpdater.active_count
            )
            await asyncio.sleep(0.05)
            FakeUpdater.active_count -= 1

    def _create_task(coro: Coroutine[object, object, None]) -> asyncio.Task[None]:
        """Capture scheduler-created update tasks."""
        task = asyncio.create_task(coro)
        created_tasks.append(task)
        return task

    mock_hass.async_create_task.side_effect = _create_task
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", FakeUpdater)
    scan_task = asyncio.create_task(coordinator.async_scan_update())

    event = MagicMock(data={"new_state": MagicMock(state="home")})
    coordinator.tsc_update(event)
    coordinator.tsc_update(event)

    await asyncio.gather(scan_task, *created_tasks)
    assert FakeUpdater.max_active_count == 1


async def test_coordinator_tsc_update_ignores_blankish_tracker_states(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tracker events with unavailable-like states should not schedule updates."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    updater_ctor = MagicMock()
    monkeypatch.setattr("custom_components.places.coordinator.PlacesUpdater", updater_ctor)

    for state in (None, "none", STATE_UNKNOWN, STATE_UNAVAILABLE, "NoNe", "UNKNOWN"):
        coordinator.tsc_update(
            MagicMock(data={"new_state": None if state is None else MagicMock(state=state)})
        )

    mock_hass.async_create_task.assert_not_called()
    updater_ctor.assert_not_called()


async def test_coordinator_in_zone_variants(
    mock_hass: MagicMock,
) -> None:
    """Zone classification should reject non-real, passive, and zone-backed states."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())

    coordinator.set_attr(ATTR_DEVICETRACKER_ZONE, "work")
    mock_hass.states.get.return_value = MagicMock(attributes={ATTR_PASSIVE: False})
    assert await coordinator.in_zone() is True

    coordinator.set_attr(ATTR_DEVICETRACKER_ZONE, "stationary")
    assert await coordinator.in_zone() is False

    coordinator.set_attr(ATTR_DEVICETRACKER_ZONE, "not_home")
    assert await coordinator.in_zone() is False

    coordinator.set_attr(ATTR_DEVICETRACKER_ZONE, "park")
    mock_hass.states.get.return_value = MagicMock(attributes={ATTR_PASSIVE: True})
    assert await coordinator.in_zone() is False

    coordinator.set_attr(CONF_DEVICETRACKER_ID, f"{CONF_ZONE}.home")
    coordinator.set_attr(ATTR_DEVICETRACKER_ZONE, "home")
    mock_hass.states.get.return_value = MagicMock(attributes={ATTR_PASSIVE: False})
    assert await coordinator.in_zone() is False


async def test_coordinator_get_driving_status_variants(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driving status should depend on zone state, direction, and road classification."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())

    monkeypatch.setattr(coordinator, "in_zone", AsyncMock(return_value=False))
    coordinator.set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
    coordinator.set_attr(ATTR_PLACE_CATEGORY, "highway")
    coordinator.clear_attr(ATTR_PLACE_TYPE)
    await coordinator.get_driving_status()
    assert coordinator.get_attr(ATTR_DRIVING) == "Driving"

    coordinator.set_attr(ATTR_DRIVING, "Driving")
    monkeypatch.setattr(coordinator, "in_zone", AsyncMock(return_value=True))
    await coordinator.get_driving_status()
    assert coordinator.get_attr(ATTR_DRIVING) is None

    monkeypatch.setattr(coordinator, "in_zone", AsyncMock(return_value=False))
    coordinator.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
    coordinator.set_attr(ATTR_PLACE_CATEGORY, "highway")
    await coordinator.get_driving_status()
    assert coordinator.get_attr(ATTR_DRIVING) is None

    coordinator.set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
    coordinator.set_attr(ATTR_PLACE_CATEGORY, "other")
    coordinator.set_attr(ATTR_PLACE_TYPE, "motorway")
    await coordinator.get_driving_status()
    assert coordinator.get_attr(ATTR_DRIVING) == "Driving"


def test_attribute_sensor_descriptions_have_expected_default_policy() -> None:
    """The default child sensor set should stay curated and omit formatted address."""
    default_keys = {
        description.key
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
        if description.entity_registry_enabled_default
    }
    disabled_keys = {
        description.key
        for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS
        if not description.entity_registry_enabled_default
    }

    assert {
        "place_name",
        "devicetracker_zone_name",
        "city",
        "state_province",
        "direction_of_travel",
        "map_link",
        "distance_from_home",
        "distance_traveled",
    } == default_keys
    assert "formatted_address" not in default_keys
    assert "country" in disabled_keys


def test_attribute_sensor_description_keys_are_unique() -> None:
    """Each child sensor description should produce one stable unique-id suffix."""
    keys = [description.key for description in PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS]

    assert len(keys) == len(set(keys))
    assert "extended_data" not in keys


def test_places_entity_uses_coordinator_device_info(mock_hass: MagicMock) -> None:
    """PlacesEntity should expose shared device metadata."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = Places(coordinator)

    assert entity.device_info == {
        "identifiers": {("places", "entry123")},
        "name": "TestSensor",
        "manufacturer": "Places",
        "model": "OpenStreetMap reverse geocode",
    }


def test_places_entity_refreshes_device_info_after_coordinator_name_change(
    mock_hass: MagicMock,
) -> None:
    """Existing entities should reflect renamed coordinator device_info on updates."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={CONF_NAME: "OldName", CONF_DEVICETRACKER_ID: "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = Places(coordinator)
    write_state = MagicMock()
    object.__setattr__(entity, "async_write_ha_state", write_state)

    assert entity.device_info["name"] == "OldName"

    coordinator.set_attr(CONF_NAME, "NewName")
    coordinator.publish_update()
    entity._handle_coordinator_update()

    assert entity.device_info["name"] == "NewName"
    write_state.assert_called_once_with()


def test_attribute_sensor_reads_coordinator_attribute(mock_hass: MagicMock) -> None:
    """Child sensors should update their native value from coordinator data."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("place_name", "Library")
    coordinator.publish_update()
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))

    assert entity.unique_id == "entry123_place_name"
    assert entity.native_value == "Library"
    assert entity.device_info == Places(coordinator).device_info
    assert isinstance(entity, PlacesEntity)


def test_attribute_sensor_has_usable_name(mock_hass: MagicMock) -> None:
    """Child sensors should expose a simple readable entity name."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))

    assert entity.name == "Place Name"


def test_distance_attribute_sensor_reads_meter_value(mock_hass: MagicMock) -> None:
    """Distance sensors should expose one native meter value instead of km/mi/m variants."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("distance_from_home", 123.4)
    coordinator.publish_update()
    entity = PlacesAttributeSensor(coordinator, _description("distance_from_home"))

    assert entity.native_value == 123.4
    assert entity.native_unit_of_measurement == "m"


def test_attribute_sensor_clamps_long_state_to_ha_limit(mock_hass: MagicMock) -> None:
    """Very long child sensor states should be clamped to Home Assistant limits."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_attr("place_name", "x" * (MAX_LENGTH_STATE_STATE + 10))
    coordinator.publish_update()
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))

    assert entity.native_value == "x" * MAX_LENGTH_STATE_STATE


def test_main_places_sensor_uses_coordinator_state(mock_hass: MagicMock) -> None:
    """The main display sensor should copy coordinator state into _attr fields."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.set_native_value("Library")
    coordinator.set_attr("current_latitude", 1.25)
    coordinator.set_attr("city", "Richmond")
    coordinator.publish_update()
    entity = Places(coordinator)
    write_state = MagicMock()
    object.__setattr__(entity, "async_write_ha_state", write_state)

    entity._handle_coordinator_update()

    assert entity.native_value == "Library"
    assert entity.extra_state_attributes == {"current_latitude": 1.25}
    assert entity._attr_native_value == "Library"
    assert entity._attr_extra_state_attributes == {"current_latitude": 1.25}
    write_state.assert_called_once_with()


def test_attribute_sensor_handle_coordinator_update_writes_state(
    mock_hass: MagicMock,
) -> None:
    """Attribute child sensors should refresh _attr_native_value in coordinator updates."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = PlacesAttributeSensor(coordinator, _description("place_name"))
    write_state = MagicMock()
    object.__setattr__(entity, "async_write_ha_state", write_state)
    coordinator.set_attr("place_name", "Library")
    coordinator.publish_update()

    entity._handle_coordinator_update()

    assert entity.native_value == "Library"
    assert entity._attr_native_value == "Library"
    write_state.assert_called_once_with()


def test_extended_data_sensor_exposes_raw_payload_and_is_unrecorded(
    mock_hass: MagicMock,
) -> None:
    """Extended data sensor should expose raw payload dictionaries unchanged."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    osm_dict = {"place_id": 1}
    osm_details_dict = {"extratags": {"wikidata": "Q1"}}
    wikidata_dict = {"entities": {"Q1": {"labels": {"en": {"value": "Test"}}}}}
    coordinator.set_attr(ATTR_OSM_DICT, osm_dict)
    coordinator.set_attr(ATTR_OSM_DETAILS_DICT, osm_details_dict)
    coordinator.set_attr(ATTR_WIKIDATA_DICT, wikidata_dict)
    coordinator.publish_update()
    entity = PlacesExtendedDataSensor(coordinator)
    write_state = MagicMock()
    object.__setattr__(entity, "async_write_ha_state", write_state)

    entity._handle_coordinator_update()

    assert entity.unique_id == "entry123_extended_data"
    assert entity.native_value == "available"
    assert entity.entity_category is EntityCategory.DIAGNOSTIC
    assert entity.extra_state_attributes == {
        ATTR_OSM_DICT: osm_dict,
        ATTR_OSM_DETAILS_DICT: osm_details_dict,
        ATTR_WIKIDATA_DICT: wikidata_dict,
    }
    assert entity._attr_extra_state_attributes == {
        ATTR_OSM_DICT: osm_dict,
        ATTR_OSM_DETAILS_DICT: osm_details_dict,
        ATTR_WIKIDATA_DICT: wikidata_dict,
    }
    assert entity._attr_native_value == "available"
    assert entity._unrecorded_attributes == frozenset({MATCH_ALL})
    write_state.assert_called_once_with()


def test_places_sensor_marks_all_attributes_unrecorded_when_extended_attr_enabled(
    mock_hass: MagicMock,
) -> None:
    """Main Places sensor should skip recorder storage of state attributes when extended mode is on."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entity = Places(coordinator)

    assert entity._unrecorded_attributes == frozenset({MATCH_ALL})


def test_extended_data_sensor_is_empty_without_payloads(mock_hass: MagicMock) -> None:
    """Extended data sensor should be unavailable until raw payloads exist."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())

    entity = PlacesExtendedDataSensor(coordinator)

    assert entity.native_value is None
    assert entity.extra_state_attributes == {}


async def test_async_setup_entry_adds_main_and_child_sensors(
    mock_hass: MagicMock,
    patch_entity_registry: object,
) -> None:
    """Setup should add one main entity and one child entity per description."""
    _ = patch_entity_registry
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entry.runtime_data = coordinator
    added: dict[str, object] = {}

    def _add_entities(entities: list[object], **kwargs: object) -> None:
        """Capture entities added during setup."""
        added["entities"] = entities
        added["kwargs"] = kwargs

    await async_setup_entry(mock_hass, entry, _add_entities)

    entities = added["entities"]
    kwargs = added["kwargs"]
    assert isinstance(entities, list)
    assert len(entities) == 1 + len(PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS)
    assert isinstance(entities[0], Places)
    assert all(isinstance(entity, PlacesAttributeSensor) for entity in entities[1:])
    assert kwargs == {}

    disabled_entities = [
        entity
        for entity in entities[1:]
        if isinstance(entity, PlacesAttributeSensor)
        and not entity.entity_description.entity_registry_enabled_default
    ]
    assert disabled_entities
    assert all(
        entity._attr_entity_registry_enabled_default is False for entity in disabled_entities
    )


async def test_async_setup_entry_removes_extended_sensor_when_disabled(
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup should remove stale extended-data registry entry when option is disabled."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: False,
        },
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entry.runtime_data = coordinator
    remove_extended_entity = AsyncMock()
    monkeypatch.setattr(
        "custom_components.places.sensor.async_remove_extended_entity",
        remove_extended_entity,
    )

    await async_setup_entry(mock_hass, entry, lambda entities, **kwargs: None)

    remove_extended_entity.assert_awaited_once_with(mock_hass, entry)


async def test_async_setup_entry_adds_extended_sensor_when_enabled(
    mock_hass: MagicMock,
) -> None:
    """Setup should append the extended-data sensor when the option is enabled."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    entry.runtime_data = coordinator
    added: dict[str, object] = {}

    def _add_entities(entities: list[object], **kwargs: object) -> None:
        """Capture entities added during setup."""
        added["entities"] = entities
        added["kwargs"] = kwargs

    await async_setup_entry(mock_hass, entry, _add_entities)

    entities = added["entities"]
    assert isinstance(entities, list)
    assert len(entities) == 2 + len(PLACES_ATTRIBUTE_SENSOR_DESCRIPTIONS)
    assert isinstance(entities[-1], PlacesExtendedDataSensor)
