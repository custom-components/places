"""Unit tests for the PlacesUpdater class and related update logic."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
import json
from typing import Protocol
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import aiohttp
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_ZONE,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_DISTANCE_TRAVELED_MI,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_LAST_CHANGED,
    ATTR_LAST_PLACE_NAME,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LOCATION_CURRENT,
    ATTR_LOCATION_PREVIOUS,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
    ATTR_MAP_LINK,
    ATTR_NATIVE_VALUE,
    ATTR_OSM_DETAILS_DICT,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_NAME,
    ATTR_PREVIOUS_STATE,
    ATTR_SHOW_DATE,
    ATTR_WIKIDATA_DICT,
    ATTR_WIKIDATA_ID,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DOMAIN,
    OSM_CACHE,
    OSM_THROTTLE,
    OSM_THROTTLE_INTERVAL_SECONDS,
    UpdateStatus,
)
from custom_components.places.coordinator import PlacesUpdateCoordinator
from custom_components.places.sensor import Places
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import (
    MockSensor,
    assert_awaited_count,
    stub_in_zone,
    stubbed_parser,
    stubbed_sensor,
)

type StubbedUpdater = Callable[..., AbstractContextManager[dict[str, AsyncMock]]]
type ZoneSetup = Callable[[MockSensor, MagicMock], object]


class AioClientMock(Protocol):
    """Minimal aiohttp client mock surface used by these tests."""

    def get(self, url: str, **kwargs: object) -> object:
        """Register a mocked GET response."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create and return a mock configuration entry with default sensor name and empty options for testing purposes."""
    return MockConfigEntry(domain="places", data={CONF_NAME: "TestSensor"}, options={})


def register_aioclient(aioclient_mock: AioClientMock, url: str, **kwargs: object) -> None:
    """Register the url with aioclient_mock for common trailing-slash variants.

    This helps ensure tests don't accidentally miss registrations due to a
    trailing-slash difference between test data and the code under test.
    """
    # exact
    aioclient_mock.get(url, **kwargs)
    # without trailing slash
    if url.endswith("/"):
        aioclient_mock.get(url.rstrip("/"), **kwargs)
    else:
        aioclient_mock.get(f"{url}/", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("check_result", "should_rollback", "should_handle"),
    [
        (UpdateStatus.PROCEED, False, True),
        (UpdateStatus.SKIP, True, False),
    ],
)
async def test_do_update_flow_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
    check_result: UpdateStatus,
    should_rollback: bool,
    should_handle: bool,
) -> None:
    """Parametrized test covering both PROCEED and SKIP paths for do_update."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            (
                "get_current_time",
                # Create UTC datetime then strip tzinfo to test handling of naive datetimes.
                {"return_value": datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)},
            ),
            ("update_entity_name_and_cleanup", {}),
            ("update_previous_state", {}),
            ("update_old_coordinates", {}),
            ("check_device_tracker_and_update_coords", {"return_value": check_result}),
            ("determine_update_criteria", {"return_value": UpdateStatus.PROCEED}),
            ("process_osm_update", {}),
            ("should_update_state", {"return_value": True}),
            ("handle_state_update", {}),
            ("rollback_update", {}),
        ],
    ) as mocks:
        await updater.do_update("manual", {"a": 1})

    if should_handle:
        mocks["handle_state_update"].assert_awaited_once()
    else:
        mocks["handle_state_update"].assert_not_called()

    if should_rollback:
        mocks["rollback_update"].assert_awaited_once()
    else:
        mocks["rollback_update"].assert_not_called()

    assert sensor.attrs[ATTR_LAST_UPDATED] == "2024-01-01 12:00:00"
    sensor.publish_update.assert_called_once_with()


@pytest.mark.asyncio
async def test_do_update_runs_phases_in_expected_order(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: Callable[
        [PlacesUpdater, list[tuple[str, dict[str, object]]]],
        AbstractContextManager[dict[str, AsyncMock]],
    ],
) -> None:
    """Assert all major phases execute in the legacy ordered sequence."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    call_order: list[str] = []

    updater.coordinator.set_attr(ATTR_LAST_PLACE_NAME, "Last Place")

    def publish_update() -> None:
        call_order.append("publish")
        assert updater.coordinator.get_attr(ATTR_LAST_UPDATED) == "2024-01-01 12:00:00"

    updater.coordinator.publish_update = MagicMock(side_effect=publish_update)

    now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    def record_prev_last_place_name(key: str, _default: object = None) -> str:
        if key == ATTR_LAST_PLACE_NAME:
            call_order.append("capture_prev_last_place_name")
        return "Last Place"

    sensor.get_attr_safe_str = MagicMock(side_effect=record_prev_last_place_name)

    async def log_update_start(_: str) -> None:
        call_order.append("log_update_start")

    async def get_current_time() -> datetime:
        call_order.append("get_current_time")
        return now

    async def check_device_tracker() -> UpdateStatus:
        call_order.append("check_device_tracker_and_update_coords")
        return UpdateStatus.PROCEED

    async def determine_update_criteria() -> UpdateStatus:
        call_order.append("determine_update_criteria")
        return UpdateStatus.PROCEED

    async def should_update_state(*_args: object, **_kwargs: object) -> bool:
        call_order.append("should_update_state")
        return True

    async def finish_update(*_args: object, **_kwargs: object) -> None:
        updater.coordinator.set_attr(ATTR_LAST_UPDATED, "2024-01-01 12:00:00")
        call_order.append("finish_update")

    async def update_entity_name_and_cleanup() -> None:
        call_order.append("update_entity_name_and_cleanup")

    async def update_previous_state() -> None:
        call_order.append("update_previous_state")

    async def update_old_coordinates() -> None:
        call_order.append("update_old_coordinates")

    async def process_osm_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("process_osm_update")

    async def handle_state_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("handle_state_update")

    with stubbed_updater(
        updater,
        [
            ("log_update_start", {"side_effect": log_update_start}),
            ("get_current_time", {"side_effect": get_current_time}),
            ("update_entity_name_and_cleanup", {"side_effect": update_entity_name_and_cleanup}),
            ("update_previous_state", {"side_effect": update_previous_state}),
            ("update_old_coordinates", {"side_effect": update_old_coordinates}),
            (
                "check_device_tracker_and_update_coords",
                {"side_effect": check_device_tracker},
            ),
            (
                "determine_update_criteria",
                {"side_effect": determine_update_criteria},
            ),
            (
                "process_osm_update",
                {"side_effect": process_osm_update},
            ),
            (
                "should_update_state",
                {"side_effect": should_update_state},
            ),
            (
                "handle_state_update",
                {"side_effect": handle_state_update},
            ),
            ("rollback_update", {}),
            ("finish_update", {"side_effect": finish_update}),
        ],
    ) as mocks:
        updater._osm_client.update_sensor_name = MagicMock(
            side_effect=lambda _sensor_name: call_order.append("update_sensor_name")
        )

        await updater.do_update("manual", {"snapshot": "value"})

        assert mocks["log_update_start"].await_count == 1

    expected_order = [
        "log_update_start",
        "get_current_time",
        "update_entity_name_and_cleanup",
        "update_sensor_name",
        "update_previous_state",
        "update_old_coordinates",
        "capture_prev_last_place_name",
        "check_device_tracker_and_update_coords",
        "determine_update_criteria",
        "process_osm_update",
        "should_update_state",
        "handle_state_update",
        "finish_update",
        "publish",
    ]
    assert call_order == expected_order


@pytest.mark.asyncio
async def test_do_update_rolls_back_and_finishes_on_phase_error(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: Callable[
        [PlacesUpdater, list[tuple[str, dict[str, object]]]],
        AbstractContextManager[dict[str, AsyncMock]],
    ],
) -> None:
    """Phase errors should rollback, finish bookkeeping, then publish the rollback snapshot."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    call_order: list[str] = []
    now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    def publish_update() -> None:
        call_order.append("publish")

    updater.coordinator.publish_update = MagicMock(side_effect=publish_update)

    async def log_update_start(_: str) -> None:
        call_order.append("log_update_start")

    async def get_current_time() -> datetime:
        call_order.append("get_current_time")
        return now

    async def check_device_tracker() -> UpdateStatus:
        call_order.append("check_device_tracker_and_update_coords")
        return UpdateStatus.PROCEED

    async def determine_update_criteria() -> UpdateStatus:
        call_order.append("determine_update_criteria")
        return UpdateStatus.PROCEED

    async def process_osm_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("process_osm_update")
        msg = "OSM failed"
        raise RuntimeError(msg)

    async def rollback_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("rollback_update")

    async def finish_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("finish_update")

    with stubbed_updater(
        updater,
        [
            ("log_update_start", {"side_effect": log_update_start}),
            ("get_current_time", {"side_effect": get_current_time}),
            ("update_entity_name_and_cleanup", {}),
            ("update_previous_state", {}),
            ("update_old_coordinates", {}),
            (
                "check_device_tracker_and_update_coords",
                {"side_effect": check_device_tracker},
            ),
            (
                "determine_update_criteria",
                {"side_effect": determine_update_criteria},
            ),
            (
                "process_osm_update",
                {"side_effect": process_osm_update},
            ),
            ("rollback_update", {"side_effect": rollback_update}),
            ("finish_update", {"side_effect": finish_update}),
        ],
    ) as mocks:
        updater._osm_client.update_sensor_name = MagicMock()

        with pytest.raises(RuntimeError, match="OSM failed"):
            await updater.do_update("manual", {"snapshot": "value"})

        mocks["rollback_update"].assert_awaited_once_with(
            {"snapshot": "value"}, now, UpdateStatus.PROCEED
        )
        mocks["finish_update"].assert_awaited_once_with(now=now)
        updater.coordinator.publish_update.assert_called_once_with()

    assert call_order == [
        "log_update_start",
        "get_current_time",
        "check_device_tracker_and_update_coords",
        "determine_update_criteria",
        "process_osm_update",
        "rollback_update",
        "finish_update",
        "publish",
    ]


@pytest.mark.asyncio
async def test_do_update_publishes_after_successful_rollback_path(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: Callable[
        [PlacesUpdater, list[tuple[str, dict[str, object]]]],
        AbstractContextManager[dict[str, AsyncMock]],
    ],
) -> None:
    """Rollback-based successful exits should publish the latest coordinator snapshot."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    call_order: list[str] = []

    def publish_update() -> None:
        call_order.append("publish")
        assert updater.coordinator.get_attr(ATTR_LAST_UPDATED) == "2024-01-01 12:00:00"

    updater.coordinator.publish_update = MagicMock(side_effect=publish_update)
    now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    async def finish_update(*_args: object, **_kwargs: object) -> None:
        updater.coordinator.set_attr(ATTR_LAST_UPDATED, "2024-01-01 12:00:00")
        call_order.append("finish_update")

    with stubbed_updater(
        updater,
        [
            ("log_update_start", {}),
            ("get_current_time", {"return_value": now}),
            ("update_entity_name_and_cleanup", {}),
            ("update_previous_state", {}),
            ("update_old_coordinates", {}),
            ("check_device_tracker_and_update_coords", {"return_value": UpdateStatus.PROCEED}),
            ("determine_update_criteria", {"return_value": UpdateStatus.PROCEED}),
            ("process_osm_update", {}),
            ("should_update_state", {"return_value": False}),
            ("rollback_update", {}),
            ("finish_update", {"side_effect": finish_update}),
        ],
    ) as mocks:
        updater._osm_client.update_sensor_name = MagicMock()

        await updater.do_update("manual", {"snapshot": "value"})

        mocks["rollback_update"].assert_awaited_once_with(
            {"snapshot": "value"}, now, UpdateStatus.PROCEED
        )
        updater.coordinator.publish_update.assert_called_once_with()
        assert call_order == ["finish_update", "publish"]


@pytest.mark.asyncio
async def test_handle_state_update_sets_native_value_and_calls_helpers(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Set native value and process extended attributes during state update."""
    # Ensure extended attribute logic is triggered and show_time path exercised
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Sensor reports extended attrs enabled and show_time enabled
    sensor.get_attr.side_effect = lambda k: (
        True
        if k in (CONF_EXTENDED_ATTR, CONF_SHOW_TIME)
        else "TestSensor"
        if k == CONF_NAME
        else None
    )
    sensor.get_attr_safe_str.side_effect = lambda k: "TestState" if k == ATTR_NATIVE_VALUE else ""
    sensor.is_attr_blank.side_effect = lambda k: False

    # Patch async helpers so we don't hit external logic
    with stubbed_updater(updater, [("get_extended_attr", {}), ("fire_event_data", {})]) as mocks:
        now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        await updater.handle_state_update(now=now, prev_last_place_name="PrevPlace")

    # Extended attr logic should have been invoked and event fired
    mocks["get_extended_attr"].assert_awaited_once()
    mocks["fire_event_data"].assert_awaited_once()
    # show_time path should set a native value with suffix
    assert sensor.native_value is not None
    # State persistence now flows through sensor.async_persist_attributes.
    sensor.async_persist_attributes.assert_awaited_once()
    mock_hass.async_add_executor_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_state_update_publishes_before_firing_event(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Event-based automations should observe updated child state before event dispatch."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.attrs = {
        CONF_EXTENDED_ATTR: False,
        CONF_SHOW_TIME: False,
        CONF_NAME: "TestSensor",
        ATTR_NATIVE_VALUE: "TestState",
    }
    call_order: list[str] = []
    updater.coordinator.publish_update = MagicMock(side_effect=lambda: call_order.append("publish"))

    async def fire_event_data(*_args: object, **_kwargs: object) -> None:
        call_order.append("event")

    with stubbed_updater(updater, [("fire_event_data", {"side_effect": fire_event_data})]):
        await updater.handle_state_update(
            now=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            prev_last_place_name="PrevPlace",
        )

    assert call_order == ["publish", "event"]


@pytest.mark.asyncio
async def test_handle_state_update_skips_extended_lookup_when_option_false(
    updater: PlacesUpdater,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extended network lookups should run only when the entry option is enabled."""
    updater.coordinator.set_attr(CONF_EXTENDED_ATTR, False)
    get_extended_attr = AsyncMock()
    monkeypatch.setattr(updater, "get_extended_attr", get_extended_attr)

    await updater.handle_state_update(
        now=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        prev_last_place_name="",
    )

    get_extended_attr.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_new_name(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test that the entity name is updated and the config entry is updated when a new friendly name is detected."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.entity_id = "sensor.test"
    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    sensor.get_attr.return_value = "OldName"
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_called()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_with_real_coordinator_entity(
    mock_hass: MagicMock,
    patch_entity_registry: object,
) -> None:
    """A real Places entity should sync its resolved entity ID into the coordinator."""
    _ = patch_entity_registry
    mock_hass.states.get.return_value = MagicMock(attributes={})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "OldName", CONF_DEVICETRACKER_ID: "device_tracker.test"},
    )
    persistence = MagicMock()
    persistence.async_save = AsyncMock()
    coordinator = PlacesUpdateCoordinator(
        hass=mock_hass,
        config_entry=entry,
        imported_attributes={},
        persistence=persistence,
    )
    entry.runtime_data = coordinator
    entity = Places(coordinator)
    entity.entity_id = "sensor.oldname"
    await entity.async_added_to_hass()

    assert coordinator.entity_id == "sensor.oldname"

    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    updater = PlacesUpdater(mock_hass, entry, coordinator)

    await updater.check_for_updated_entity_name()

    mock_hass.config_entries.async_update_entry.assert_called_once()
    assert coordinator.device_info["name"] == "NewName"


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_uses_latest_coordinator_entity_id(
    mock_hass: MagicMock,
) -> None:
    """Changed Places entity IDs should refresh coordinator.entity_id before name lookup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "OldName", CONF_DEVICETRACKER_ID: "device_tracker.test"},
    )
    persistence = MagicMock()
    persistence.async_save = AsyncMock()
    coordinator = PlacesUpdateCoordinator(
        hass=mock_hass,
        config_entry=entry,
        imported_attributes={},
        persistence=persistence,
    )
    coordinator.entity_id = "sensor.old_name"
    entity = Places(coordinator)
    entity.entity_id = "sensor.new_name"
    entity._update_from_coordinator()
    assert coordinator.entity_id == "sensor.new_name"

    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    updater = PlacesUpdater(mock_hass, entry, coordinator)

    await updater.check_for_updated_entity_name()

    assert mock_hass.states.get.call_args_list[-1][0][0] == "sensor.new_name"
    assert coordinator.get_attr(CONF_NAME) == "NewName"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("show_time", "expected"),
    [
        (True, "TestVal"),
        (False, False),
    ],
)
async def test_update_previous_state_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    show_time: bool,
    expected: object,
) -> None:
    """Parametrized: previous state handling when show-time enabled or disabled."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    if show_time:
        sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
        sensor.get_attr.side_effect = lambda k: True if k == CONF_SHOW_TIME else "TestVal"
        # Use side_effect to keep behaviour consistent with other branches
        sensor.get_attr_safe_str.side_effect = lambda k: "TestVal" if k == ATTR_NATIVE_VALUE else ""
    else:
        sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
        sensor.get_attr.side_effect = lambda k: (
            "PrevStateValue" if k == ATTR_PREVIOUS_STATE else False
        )
        sensor.get_attr_safe_str.side_effect = lambda k: (
            "PrevStateValue" if k in [ATTR_NATIVE_VALUE, ATTR_PREVIOUS_STATE] else ""
        )

    await updater.update_previous_state()
    assert sensor.attrs[ATTR_PREVIOUS_STATE] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lat_val", "lon_val", "expect_lat_old", "expect_lon_old"),
    [
        (1.0, 1.0, 1.0, 1.0),
        ("not_a_float", 2.0, None, 2.0),
        (1.0, "not_a_float", 1.0, None),
    ],
)
async def test_update_old_coordinates_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    lat_val: float | str,
    lon_val: float | str,
    expect_lat_old: float | None,
    expect_lon_old: float | None,
) -> None:
    """Parametrized: update_old_coordinates sets only valid numeric old coordinate attributes."""
    sensor.attrs[ATTR_LATITUDE] = lat_val
    sensor.attrs[ATTR_LONGITUDE] = lon_val
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.update_old_coordinates()
    if expect_lat_old is None:
        assert ATTR_LATITUDE_OLD not in sensor.attrs
    else:
        assert sensor.attrs[ATTR_LATITUDE_OLD] == expect_lat_old
    if expect_lon_old is None:
        assert ATTR_LONGITUDE_OLD not in sensor.attrs
    else:
        assert sensor.attrs[ATTR_LONGITUDE_OLD] == expect_lon_old


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gps_result", "expected"),
    [
        (UpdateStatus.PROCEED, UpdateStatus.PROCEED),
        (UpdateStatus.SKIP, UpdateStatus.SKIP),
    ],
)
async def test_check_device_tracker_and_update_coords_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
    gps_result: UpdateStatus,
    expected: object,
) -> None:
    """Parametrized test: check_device_tracker_and_update_coords propagates GPS accuracy results and always updates coordinates first."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("is_devicetracker_set", {"return_value": UpdateStatus.PROCEED}),
            ("update_coordinates", {}),
            ("get_gps_accuracy", {"return_value": gps_result}),
        ],
    ) as mocks:
        result = await updater.check_device_tracker_and_update_coords()
    assert result == expected
    mocks["update_coordinates"].assert_awaited_once()
    mocks["get_gps_accuracy"].assert_awaited_once()


@pytest.mark.asyncio
async def test_get_gps_accuracy_sets_accuracy(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Retrieve GPS accuracy and set sensor attribute when available."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {ATTR_GPS_ACCURACY: 5.0}
    mock_hass.states.get.return_value = tracker_state
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.is_attr_blank.return_value = False
    sensor.get_attr.return_value = True
    sensor.get_attr_safe_float.return_value = 5.0
    result = await updater.get_gps_accuracy()
    assert result == UpdateStatus.PROCEED
    assert sensor.attrs[ATTR_GPS_ACCURACY] == 5.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tracker_attrs", "use_gps", "expected"),
    [
        ({ATTR_GPS_ACCURACY: 5.0}, True, UpdateStatus.PROCEED),
        ({ATTR_GPS_ACCURACY: 0}, True, UpdateStatus.SKIP),
    ],
)
async def test_get_gps_accuracy_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_attrs: dict[str, object] | None,
    use_gps: bool,
    expected: object,
) -> None:
    """Parametrized variants for get_gps_accuracy: valid accuracy, zero accuracy, and missing tracker."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    tracker_state = MagicMock() if tracker_attrs is not None else None
    if tracker_attrs is not None:
        tracker_state.attributes = tracker_attrs
    mock_hass.states.get.return_value = tracker_state

    # Populate required attributes where relevant
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.attrs[CONF_USE_GPS] = use_gps

    # is_attr_blank should evaluate based on actual attrs
    sensor.is_attr_blank.side_effect = lambda k: (
        k not in sensor.attrs
        or sensor.attrs.get(k)
        in (
            None,
            "",
        )
    )

    result = await updater.get_gps_accuracy()
    assert result == expected
    if tracker_attrs is not None:
        assert sensor.attrs[ATTR_GPS_ACCURACY] == float(tracker_attrs[ATTR_GPS_ACCURACY])


@pytest.mark.asyncio
async def test_update_coordinates_variants_present_and_missing(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Parametrized-like variant: when tracker present set coords, when missing log warning."""
    # Present case
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker_state = MagicMock()
    tracker_state.attributes = {CONF_LATITUDE: 1.23, CONF_LONGITUDE: 4.56}
    mock_hass.states.get.return_value = tracker_state
    await updater.update_coordinates()
    assert sensor.attrs[ATTR_LATITUDE] == 1.23
    assert sensor.attrs[ATTR_LONGITUDE] == 4.56

    # Missing case
    mock_hass.states.get.return_value = None
    await updater.update_coordinates()
    assert any("Device tracker entity not found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_determine_update_criteria_calls(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Test that `determine_update_criteria` calls all required helper methods and returns the correct update status."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("get_initial_last_place_name", {}),
            ("get_zone_details", {}),
            ("update_coordinates_and_distance", {"return_value": UpdateStatus.PROCEED}),
            ("determine_if_update_needed", {"return_value": UpdateStatus.PROCEED}),
        ],
    ) as mocks:
        result = await updater.determine_update_criteria()
    assert result == UpdateStatus.PROCEED
    mocks["get_initial_last_place_name"].assert_awaited_once()
    mocks["get_zone_details"].assert_awaited_once()
    mocks["update_coordinates_and_distance"].assert_awaited_once()
    mocks["determine_if_update_needed"].assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("in_zone", "place_name", "zone_name", "expected"),
    [
        (False, "PlaceName", None, "PlaceName"),
        (True, None, "ZoneName", "ZoneName"),
    ],
)
async def test_get_initial_last_place_name_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    in_zone: bool,
    place_name: str | None,
    zone_name: str | None,
    expected: object,
) -> None:
    """Parametrized test for get_initial_last_place_name covering zone and non-zone cases."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = False
    if place_name is not None:
        sensor.attrs[ATTR_PLACE_NAME] = place_name
    if zone_name is not None:
        sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] = zone_name
    with stub_in_zone(sensor, in_zone):
        await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "setup_func", "expected_zone", "expected_zone_name_present", "expected_zone_name"),
    [
        (
            "not_zone",
            lambda sensor, mock_hass: (
                sensor.get_attr_safe_str.__setattr__(
                    "side_effect",
                    (
                        lambda k: (
                            "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "device_tracker.test"
                        )
                    ),
                ),
                sensor.get_attr.__setattr__(
                    "side_effect",
                    (lambda k: "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "TestZone"),
                ),
                mock_hass.states.get.__setattr__("return_value", MagicMock(state="home")),
            ),
            "home",
            True,
            "TestZone",
        ),
        (
            "zone_id_equals_conf_zone",
            lambda sensor, mock_hass: (
                sensor.__setattr__(
                    "get_attr_safe_str",
                    (lambda k: CONF_ZONE + ".home" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                sensor.__setattr__(
                    "get_attr",
                    (lambda k: CONF_ZONE + ".home" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                sensor.attrs.__setitem__(ATTR_DEVICETRACKER_ZONE, "home"),
            ),
            None,
            True,
            "",
        ),
        (
            "in_zone_true",
            lambda sensor, mock_hass: (
                sensor.__setattr__(
                    "get_attr_safe_str",
                    (lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                sensor.__setattr__(
                    "get_attr",
                    (lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                mock_hass.states.get.__setattr__(
                    "side_effect",
                    (
                        lambda eid: (
                            MagicMock(attributes={CONF_ZONE: "home"})
                            if eid == "device_tracker.test"
                            else MagicMock(attributes={CONF_FRIENDLY_NAME: "Home Zone"})
                            if eid == "zone.home"
                            else None
                        )
                    ),
                ),
            ),
            None,
            True,
            "",
        ),
        (
            "in_zone_no_zone_name_state",
            lambda sensor, mock_hass: (
                sensor.__setattr__(
                    "get_attr_safe_str",
                    (lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                sensor.__setattr__(
                    "get_attr",
                    (lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""),
                ),
                mock_hass.states.get.__setattr__(
                    "side_effect",
                    (
                        lambda eid: (
                            MagicMock(attributes={CONF_ZONE: "home"})
                            if eid == "device_tracker.test"
                            else None
                        )
                    ),
                ),
            ),
            None,
            True,
            None,
        ),
    ],
)
async def test_get_zone_details_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    scenario: str,
    setup_func: ZoneSetup,
    expected_zone: str | None,
    expected_zone_name_present: bool,
    expected_zone_name: str | None,
) -> None:
    """Parametrized variants for get_zone_details covering zone and non-zone flows."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Execute scenario-specific setup
    setup_func(sensor, mock_hass)

    # Default to not in zone unless scenario setup overrides
    in_zone = scenario not in ("not_zone", "zone_id_equals_conf_zone")
    with stub_in_zone(sensor, in_zone):
        await updater.get_zone_details()

    if expected_zone is not None:
        assert sensor.attrs[ATTR_DEVICETRACKER_ZONE] == expected_zone
    if expected_zone_name_present:
        # When a zone name presence is expected, assert the attribute exists (value may be empty string)
        assert ATTR_DEVICETRACKER_ZONE_NAME in sensor.attrs
        if expected_zone_name is not None:
            assert sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] == expected_zone_name


@pytest.mark.asyncio
async def test_get_zone_details_uses_home_zone_friendly_name_from_state(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
) -> None:
    """Default home zone state should resolve the configured zone friendly name."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker_state = MagicMock(state="home", attributes={})
    home_zone_state = MagicMock(attributes={ATTR_FRIENDLY_NAME: "Casa Concordia"})

    mock_hass.states.get.side_effect = lambda entity_id: (
        tracker_state
        if entity_id == "device_tracker.person"
        else home_zone_state
        if entity_id == "zone.home"
        else None
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    with stub_in_zone(sensor, True):
        await updater.get_zone_details()

    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE] == "home"
    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] == "Casa Concordia"


@pytest.mark.asyncio
async def test_process_osm_update_calls(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Test that `process_osm_update` calls attribute reset, map link generation, and OSM query finalization methods as expected."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("async_reset_attributes", {}),
            ("get_map_link", {}),
            ("query_osm_and_finalize", {}),
        ],
    ) as mocks:
        await updater.process_osm_update(datetime(2024, 1, 1, 12, 0, tzinfo=UTC))
    mocks["async_reset_attributes"].assert_awaited_once()
    mocks["get_map_link"].assert_awaited_once()
    mocks["query_osm_and_finalize"].assert_awaited_once()


def assert_map_link_set(sensor: MockSensor) -> None:
    """Assert that set_attr was called with ATTR_MAP_LINK and a string value."""
    found = False
    for call in sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_MAP_LINK and isinstance(call[0][1], str):
            found = True
            break
    assert found


# `osm` provider covered in parametrized `test_get_map_link_providers_all` below.


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "apple", "osm"])
async def test_get_map_link_providers_all(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor, provider: str
) -> None:
    """Parametrized: verify map link generation for multiple providers including OSM."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    if provider == "osm":
        # OSM needs lat/lon floats
        sensor.get_attr.side_effect = lambda k: "osm" if k == CONF_MAP_PROVIDER else 10
        sensor.get_attr_safe_float.side_effect = lambda k: (
            1.23456789 if k == ATTR_LATITUDE else 9.87654321
        )
    else:
        sensor.get_attr.side_effect = lambda k: (
            provider if k == CONF_MAP_PROVIDER else "loc" if k == ATTR_LOCATION_CURRENT else 10
        )
    await updater.get_map_link()
    assert_map_link_set(sensor)


@pytest.mark.asyncio
async def test_async_reset_attributes_calls(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test that `async_reset_attributes` clears sensor attributes and performs asynchronous cleanup."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.async_reset_attributes()
    sensor.clear_attr.assert_called()
    sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prev_val", "native_val", "expected"),
    [
        ("a", "b", True),
        ("a", "a", False),
    ],
)
async def test_should_update_state_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    prev_val: str,
    native_val: str,
    expected: object,
) -> None:
    """Parametrized test for `should_update_state` for differing and equal values."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: (
        prev_val if k == ATTR_PREVIOUS_STATE else native_val if k == ATTR_NATIVE_VALUE else ""
    )
    sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now(tz=UTC))
    assert result is expected


@pytest.mark.asyncio
async def test_rollback_update_calls_restore_and_helpers(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Restore previous attributes and conditionally call helper routines."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("get_seconds_from_last_change", {"return_value": 100}),
            ("change_dot_to_stationary", {}),
            ("change_show_time_to_date", {}),
        ],
    ) as mocks:
        # Ensure show_time is False and direction is not 'stationary' so change_dot_to_stationary runs
        sensor.get_attr.side_effect = lambda k: False
        await updater.rollback_update(
            {"a": 1}, datetime.now(tz=UTC), UpdateStatus.SKIP_SET_STATIONARY
        )
    sensor.restore_previous_attr.assert_awaited_once()
    # Based on the test setup (proceed SKIP_SET_STATIONARY, default direction not 'stationary', seconds=100),
    # change_dot_to_stationary should have been awaited once; show_time helper should not be awaited.
    mocks["change_dot_to_stationary"].assert_awaited_once()
    mocks["change_show_time_to_date"].assert_not_awaited()


@pytest.mark.asyncio
async def test_build_osm_url_returns_url(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test that `build_osm_url` constructs a valid OpenStreetMap reverse geocoding URL using sensor attributes."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    sensor.get_attr.side_effect = lambda k: (
        "en" if k == CONF_LANGUAGE else "apikey" if k == CONF_API_KEY else 18
    )
    url = await updater.build_osm_url()
    assert url.startswith("https://nominatim.openstreetmap.org/reverse?format=json")

    # Parse and verify URL parameters
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert params.get("lat") == ["1.0"]
    assert params.get("lon") == ["1.0"]
    assert params.get("accept-language") == ["en"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cached", "payload", "expected_attr", "network_error"),
    [
        (True, None, {"a": 1}, False),
        (False, '[{"a": 1}]', {"a": 1}, False),
        (False, None, None, True),
    ],
)
async def test_get_dict_from_url_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AioClientMock,
    sensor: MockSensor,
    cached: bool,
    payload: str | None,
    expected_attr: object | None,
    network_error: bool,
) -> None:
    """Parametrized: cache hit, list-payload behavior, and network-error for get_dict_from_url."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/test"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
        }

    if cached:
        mock_hass.data[DOMAIN][OSM_CACHE][url] = expected_attr
        await updater.get_dict_from_url(url, "Test", "dict_name")
        assert sensor.attrs["dict_name"] == expected_attr
        return

    if network_error:
        # Simulate an OSError when attempting to GET the URL
        aioclient_mock.get(url, exc=OSError("fail"))
        await updater.get_dict_from_url(url, "Test", "dict_name")
        # Should not raise; accept missing or empty dict cache behavior
        assert not sensor.attrs.get("dict_name")
        return

    # not cached -> register with aioclient_mock (aioclient_mock intercepts aiohttp calls)
    register_aioclient(aioclient_mock, url, text=payload)
    await updater.get_dict_from_url(url, "Test", "dict_name")
    assert sensor.attrs["dict_name"] == expected_attr
    assert mock_hass.data[DOMAIN][OSM_CACHE][url] == expected_attr


@pytest.mark.asyncio
async def test_get_dict_from_url_sets_empty_list_payload(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AioClientMock,
    sensor: MockSensor,
) -> None:
    """Non-mapping list payloads are cached and set directly on sensor attributes."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/empty-list"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
        }

    register_aioclient(aioclient_mock, url, text="[]")
    await updater.get_dict_from_url(url, "NetService", "dict_name")

    assert sensor.attrs["dict_name"] == []
    assert mock_hass.data[DOMAIN][OSM_CACHE].get(url) == []


@pytest.mark.asyncio
async def test_get_dict_from_url_removes_stale_cache_on_fetch_failure(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fetch removes any stale cache entry for the requested URL."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/stale"
    mock_hass.data[DOMAIN] = {
        OSM_CACHE: {url: {"stale": True}},
        OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
    }

    monkeypatch.setattr(updater._osm_client, "get_json", AsyncMock(return_value=None))

    await updater.get_dict_from_url(url, "NetService", "dict_name")

    assert sensor.attrs["dict_name"] == {}
    assert url not in mock_hass.data[DOMAIN][OSM_CACHE]


# Network-error case moved into parametrized `test_get_dict_from_url_variants`


@pytest.mark.asyncio
async def test_determine_if_update_needed_initial_update(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test that `determine_if_update_needed` returns `PROCEED` when the initial update attribute is set to True."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_update_location_attributes_sets_locations(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test that `update_location_attributes` sets current, previous, and home location attributes to the expected values."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_location_attributes()
    assert sensor.attrs[ATTR_LOCATION_CURRENT] == "1.0,1.0"
    assert sensor.attrs[ATTR_LOCATION_PREVIOUS] == "1.0,1.0"
    assert sensor.attrs[ATTR_HOME_LOCATION] == "1.0,1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_m_attr", "expected_mi_attr"),
    [
        ("calculate_distances", ATTR_DISTANCE_FROM_HOME_M, ATTR_DISTANCE_FROM_HOME_MI),
        ("calculate_travel_distance", ATTR_DISTANCE_TRAVELED_M, ATTR_DISTANCE_TRAVELED_MI),
    ],
)
async def test_calculate_distance_methods(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    method_name: str,
    expected_m_attr: str,
    expected_mi_attr: str,
) -> None:
    """Parametrized test for distance calculation methods to validate m and mi attributes are set appropriately."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    method = getattr(updater, method_name)
    await method()
    # Verify metric attribute set to 0 in these test scenarios
    assert sensor.attrs.get(expected_m_attr) == 0
    # Verify some MI attribute was set via set_attr calls
    calls = [call for call in sensor.set_attr.call_args_list if call[0][0] == expected_mi_attr]
    assert any(isinstance(c[0][1], float | int) for c in calls)


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_calls(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Call coordinate and distance helpers and return PROCEED."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    # Patch get_attr_safe_str to return a value with a dot for CONF_HOME_ZONE
    sensor.get_attr_safe_str.side_effect = lambda k: "zone.home" if k == CONF_HOME_ZONE else "other"
    with stubbed_updater(
        updater,
        [
            ("update_location_attributes", {}),
            ("calculate_distances", {}),
            ("calculate_travel_distance", {}),
            ("determine_direction_of_travel", {}),
        ],
    ) as mocks:
        result = await updater.update_coordinates_and_distance()
    assert result == UpdateStatus.PROCEED
    mocks["update_location_attributes"].assert_awaited_once()
    mocks["calculate_distances"].assert_awaited_once()
    mocks["calculate_travel_distance"].assert_awaited_once()
    mocks["determine_direction_of_travel"].assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["blank", "invalid_date", "valid_date", "type_error", "value_error"],
)
async def test_get_seconds_from_last_change_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    scenario: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parametrized variants for get_seconds_from_last_change covering various error and success paths."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    now = datetime.now(tz=UTC)

    if scenario == "blank":
        sensor.is_attr_blank.return_value = True
        result = await updater.get_seconds_from_last_change(now)
        assert result == 3600
        return

    sensor.is_attr_blank.return_value = False

    if scenario == "invalid_date":
        sensor.get_attr_safe_str.return_value = "not-a-date"
        result = await updater.get_seconds_from_last_change(now)
        assert result == 3600
        return

    if scenario == "valid_date":
        last_changed = now - timedelta(seconds=123)
        sensor.attrs[ATTR_LAST_CHANGED] = last_changed.replace(microsecond=0).isoformat()
        result = await updater.get_seconds_from_last_change(now.replace(microsecond=0))
        assert result == 123
        return

    if scenario == "type_error":
        # Create UTC datetime then strip tzinfo to test handling of naive datetimes.
        naive_last_changed = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        aware_now = datetime(2024, 1, 1, 13, 0, tzinfo=UTC)

        sensor.get_attr_safe_str.return_value = naive_last_changed.isoformat()
        mock_dt = MagicMock()
        mock_dt.fromisoformat.return_value = naive_last_changed
        mock_dt.now.return_value = aware_now
        monkeypatch.setattr("custom_components.places.update_sensor.datetime", mock_dt)
        result = await updater.get_seconds_from_last_change(aware_now)
        assert result == 3600
        return

    # value_error
    sensor.get_attr_safe_str.return_value = "bad-date"
    mock_dt = MagicMock()
    mock_dt.fromisoformat.side_effect = ValueError("bad date format")
    mock_dt.now.return_value = now
    monkeypatch.setattr("custom_components.places.update_sensor.datetime", mock_dt)
    result = await updater.get_seconds_from_last_change(now)
    assert result == 3600


@pytest.mark.asyncio
@pytest.mark.parametrize("date_format", ["dd/mm", "mm/dd"])
async def test_change_show_time_to_date_param(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor, date_format: str
) -> None:
    """Parametrized test for change_show_time_to_date handling both dd/mm and mm/dd formats."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = lambda k: (
        True
        if k == CONF_SHOW_TIME
        else date_format
        if k == CONF_DATE_FORMAT
        else "2024-01-01 12:00:00"
    )
    sensor.get_attr_safe_str.side_effect = lambda k: (
        "2024-01-01 12:00:00" if k == ATTR_LAST_CHANGED else "TestState"
    )
    await updater.change_show_time_to_date()
    assert sensor.native_value is not None
    assert sensor.attrs[ATTR_SHOW_DATE] is True
    sensor.async_persist_attributes.assert_awaited_once()
    mock_hass.async_add_executor_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_dot_to_stationary_sets_direction_and_last_changed(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Set direction to 'stationary' and update last_changed, scheduling executor job."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.change_dot_to_stationary(
        datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None), 100
    )
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"
    assert sensor.attrs[ATTR_LAST_CHANGED] == "2024-01-01 12:00:00"
    sensor.async_persist_attributes.assert_awaited_once()
    mock_hass.async_add_executor_job.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tracker_available", "has_valid_coords", "expected"),
    [
        (False, None, UpdateStatus.SKIP),
        (True, False, UpdateStatus.SKIP),
        (True, True, UpdateStatus.PROCEED),
    ],
)
async def test_is_devicetracker_set_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
    tracker_available: bool,
    has_valid_coords: bool | None,
    expected: object,
) -> None:
    """Parametrized test for is_devicetracker_set covering not available, invalid coords, and proceed."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("is_tracker_available", {"return_value": tracker_available}),
            (
                "has_valid_coordinates",
                {"return_value": has_valid_coords} if has_valid_coords is not None else {},
            ),
        ],
    ):
        result = await updater.is_devicetracker_set()
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tracker_state", "expected_result"),
    [
        (None, False),
        ("unavailable", False),
        (MagicMock(state="home"), True),
    ],
)
async def test_is_tracker_available_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_state: object,
    expected_result: object,
) -> None:
    """Test is_tracker_available for missing, unavailable, and valid tracker states."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr.return_value = "device_tracker.test"
    mock_hass.states.get.return_value = tracker_state
    # Ensure the sensor reports a configured device_tracker id so it is not
    # considered blank by MockSensor.is_attr_blank's default behavior.
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    result = await updater.is_tracker_available()
    assert result is expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tracker_attrs", "expected_result"),
    [
        (None, False),
        ({CONF_LATITUDE: None, CONF_LONGITUDE: None}, False),
        ({CONF_LATITUDE: "a", CONF_LONGITUDE: 2.0}, False),
        ({CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0}, True),
    ],
)
async def test_has_valid_coordinates_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_attrs: dict[str, object] | None,
    expected_result: object,
) -> None:
    """Test has_valid_coordinates for missing, bad, and valid lat/lon attributes."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    if tracker_attrs is not None:
        tracker.attributes = tracker_attrs
    elif hasattr(tracker, "attributes"):
        del tracker.attributes
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is expected_result


@pytest.mark.asyncio
@pytest.mark.parametrize("warn_flag", [True, False])
async def test_log_tracker_issue_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    caplog: pytest.LogCaptureFixture,
    warn_flag: bool,
) -> None:
    """Test log_tracker_issue for both warn and info levels."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = warn_flag
    await updater.log_tracker_issue("Test message")
    assert "Test message" in caplog.text

    # Verify correct log level
    if warn_flag:
        assert any(record.levelname == "WARNING" for record in caplog.records)
    else:
        assert any(record.levelname == "INFO" for record in caplog.records)


@pytest.mark.asyncio
async def test_query_osm_and_finalize_runs_parser_and_sets_last_changed(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that query_osm_and_finalize runs the OSM parser, finalizes the last place name, processes display options, and sets last_changed."""
    sensor.attrs["osm_dict"] = {"some": "value"}
    sensor.attrs["last_place_name"] = "TestPlace"
    mock_parser = AsyncMock()
    # Create a single updater instance and stub its methods; do NOT create a second instance
    # inside the context (previous version created a new instance whose methods were not stubbed,
    # leading to the real get_dict_from_url accessing hass.data and raising KeyError).
    updater = PlacesUpdater(
        hass=mock_hass,
        config_entry=mock_config_entry,
        coordinator=sensor,
    )
    mock_parser_cls = MagicMock(return_value=mock_parser)
    monkeypatch.setattr("custom_components.places.update_sensor.OSMParser", mock_parser_cls)
    with (
        stubbed_sensor(sensor, [("process_display_options", {})]) as sensor_mocks,
        stubbed_parser(
            mock_parser, [("parse_osm_dict", {}), ("finalize_last_place_name", {})]
        ) as parser_mocks,
        stubbed_updater(
            updater,
            [
                ("build_osm_url", {"return_value": "http://test-url"}),
                ("get_dict_from_url", {}),
            ],
        ) as updater_mocks,
    ):
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        await updater.query_osm_and_finalize(now)
        # Assert updater method calls
        updater_mocks["build_osm_url"].assert_awaited_once()
        updater_mocks["get_dict_from_url"].assert_awaited_once_with(
            url="http://test-url",
            name="OpenStreetMaps",
            dict_name="osm_dict",
        )
        # Assert parser interactions
        parser_mocks["parse_osm_dict"].assert_awaited_once()
        parser_mocks["finalize_last_place_name"].assert_awaited_once_with("TestPlace")
        # Assert sensor post-processing
        sensor_mocks["process_display_options"].assert_awaited_once()
        # Assert attribute updated
        assert sensor.attrs["last_changed"] == now.isoformat(sep=" ", timespec="seconds")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blank_attr",
    [ATTR_LATITUDE, ATTR_LONGITUDE, ATTR_HOME_LATITUDE, ATTR_HOME_LONGITUDE],
)
async def test_calculate_distances_not_all_attrs_set(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor, blank_attr: str
) -> None:
    """Test calculate_distances does NOT set distance attributes if any required attribute is blank."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Patch is_attr_blank to return True for the blank_attr, False otherwise
    def is_attr_blank(key: str) -> bool:
        """Report only the parameterized distance input as blank.

        Args:
            key: Attribute name checked by the updater.

        Returns:
            ``True`` when ``key`` is the scenario's blank attribute.
        """
        return key == blank_attr

    def set_attr(key: str, value: object) -> None:
        """Store calculated distance attributes on the mock sensor.

        Args:
            key: Attribute name set by the updater.
            value: Calculated value to store.
        """
        sensor.attrs[key] = value

    sensor.is_attr_blank = MagicMock(side_effect=is_attr_blank)
    # Patch set_attr to update attrs
    sensor.set_attr = MagicMock(side_effect=set_attr)
    await updater.calculate_distances()
    # None of the distance attributes should be set
    assert ATTR_DISTANCE_FROM_HOME_M not in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_KM not in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_MI not in sensor.attrs


@pytest.mark.asyncio
async def test_calculate_distances_distance_from_home_m_blank(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Test calculate_distances does NOT set KM/MI if ATTR_DISTANCE_FROM_HOME_M is blank after calculation."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Patch is_attr_blank so ATTR_DISTANCE_FROM_HOME_M is blank after calculation
    def is_attr_blank(key: str) -> bool:
        """Report the meter distance as blank after the calculation step.

        Args:
            key: Attribute name checked by the updater.

        Returns:
            ``True`` only for ``ATTR_DISTANCE_FROM_HOME_M``.
        """
        # Only ATTR_DISTANCE_FROM_HOME_M is blank
        return key == ATTR_DISTANCE_FROM_HOME_M

    def set_attr(key: str, value: object) -> None:
        """Store calculated distance attributes on the mock sensor.

        Args:
            key: Attribute name set by the updater.
            value: Calculated value to store.
        """
        sensor.attrs[key] = value

    sensor.is_attr_blank = MagicMock(side_effect=is_attr_blank)
    # Patch set_attr to update attrs
    sensor.set_attr = MagicMock(side_effect=set_attr)
    # Patch get_attr_safe_float to return valid floats
    sensor.get_attr_safe_float = MagicMock(return_value=1.0)
    # Patch all required attributes to not blank except ATTR_DISTANCE_FROM_HOME_M
    for attr in [ATTR_LATITUDE, ATTR_LONGITUDE, ATTR_HOME_LATITUDE, ATTR_HOME_LONGITUDE]:
        sensor.attrs[attr] = 1.0
    await updater.calculate_distances()
    # Only ATTR_DISTANCE_FROM_HOME_M should be set
    assert ATTR_DISTANCE_FROM_HOME_M in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_KM not in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_MI not in sensor.attrs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "blank_attr", "expected_direction"),
    [
        ("normal", None, None),
        ("missing_old_coord", ATTR_LATITUDE_OLD, "stationary"),
        ("blank_traveled_m", ATTR_DISTANCE_TRAVELED_M, None),
    ],
)
async def test_calculate_travel_distance_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    mode: str,
    blank_attr: str | None,
    expected_direction: str | None,
) -> None:
    """Parametrized variants for calculate_travel_distance covering normal, missing old coords, and blank traveled m."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Default behaviors
    sensor.get_attr_safe_float = MagicMock(return_value=1.0)

    if mode == "missing_old_coord":

        def is_attr_blank(key: str) -> bool:
            """Report the parameterized old coordinate as blank.

            Args:
                key: Attribute name checked by the updater.

            Returns:
                ``True`` when ``key`` matches the missing old coordinate.
            """
            return key == blank_attr

        def set_attr(key: str, value: object) -> None:
            """Store travel-distance fallback values on the mock sensor.

            Args:
                key: Attribute name set by the updater.
                value: Calculated or fallback value to store.
            """
            sensor.attrs[key] = value

        sensor.is_attr_blank = MagicMock(side_effect=is_attr_blank)
        # Ensure set_attr updates attrs for this branch
        sensor.set_attr = MagicMock(side_effect=set_attr)
        await updater.calculate_travel_distance()
        assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == expected_direction
        assert sensor.attrs[ATTR_DISTANCE_TRAVELED_M] == 0
        assert sensor.attrs[ATTR_DISTANCE_TRAVELED_MI] == 0
        return

    if mode == "blank_traveled_m":

        def is_attr_blank(key: str) -> bool:
            """Report the traveled-meter attribute as blank.

            Args:
                key: Attribute name checked by the updater.

            Returns:
                ``True`` when ``key`` matches the scenario blank attribute.
            """
            return key == blank_attr

        def set_attr(key: str, value: object) -> None:
            """Store travel-distance values before mile conversion is skipped.

            Args:
                key: Attribute name set by the updater.
                value: Calculated value to store.
            """
            sensor.attrs[key] = value

        sensor.is_attr_blank = MagicMock(side_effect=is_attr_blank)
        # Provide old coords so calculation proceeds
        for attr in [ATTR_LATITUDE_OLD, ATTR_LONGITUDE_OLD]:
            sensor.attrs[attr] = 1.0
        # Ensure set_attr updates attrs for this branch
        sensor.set_attr = MagicMock(side_effect=set_attr)
        await updater.calculate_travel_distance()
        assert ATTR_DISTANCE_TRAVELED_M in sensor.attrs
        assert ATTR_DISTANCE_TRAVELED_MI not in sensor.attrs
        return

    # normal
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    await updater.calculate_travel_distance()
    assert sensor.attrs[ATTR_DISTANCE_TRAVELED_M] == 0
    found = any(
        call[0][0] == ATTR_DISTANCE_TRAVELED_MI and isinstance(call[0][1], float)
        for call in sensor.set_attr.call_args_list
    )
    assert found


@pytest.mark.asyncio
async def test_determine_update_criteria_skip_before_determine_if_update_needed(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """If update_coordinates_and_distance returns SKIP then determine_if_update_needed not called."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("get_initial_last_place_name", {}),
            ("get_zone_details", {}),
            ("update_coordinates_and_distance", {"return_value": UpdateStatus.SKIP}),
            ("determine_if_update_needed", {"return_value": UpdateStatus.PROCEED}),
        ],
    ) as mocks:
        result = await updater.determine_update_criteria()
    assert result == UpdateStatus.SKIP
    mocks["determine_if_update_needed"].assert_not_awaited()


@pytest.mark.asyncio
async def test_get_initial_last_place_name_not_in_zone_blank_keeps_previous(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Retains previous last_place_name when not in zone and place_name blank."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_PLACE_NAME
    sensor.attrs["last_place_name"] = "Prev"
    with stub_in_zone(sensor, False):
        await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == "Prev"


@pytest.mark.asyncio
async def test_query_osm_and_finalize_no_osm_dict(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If OSM dict blank parser isn't invoked and last_changed not set."""
    sensor.attrs[ATTR_OSM_DICT] = None
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    mock_parser_cls = MagicMock()
    monkeypatch.setattr("custom_components.places.update_sensor.OSMParser", mock_parser_cls)
    with (
        stubbed_sensor(sensor, [("process_display_options", {})]),
        stubbed_updater(
            updater,
            [("build_osm_url", {"return_value": "http://url"}), ("get_dict_from_url", {})],
        ),
    ):
        now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        await updater.query_osm_and_finalize(now)
    mock_parser_cls.assert_not_called()
    assert ATTR_LAST_CHANGED not in sensor.attrs


@pytest.mark.asyncio
async def test_should_update_state_initial_update_true(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Returns True when ATTR_INITIAL_UPDATE flag set (forces update)."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: k == ATTR_INITIAL_UPDATE
    sensor.is_attr_blank.return_value = True
    result = await updater.should_update_state(datetime.now(tz=UTC))
    assert result is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "seconds", "show_time", "expect_dot", "expect_show"),
    [
        (UpdateStatus.SKIP_SET_STATIONARY, 120, False, True, False),
        (UpdateStatus.PROCEED, 90000, True, False, True),
    ],
)
async def test_rollback_update_triggers_helpers(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    status: UpdateStatus,
    seconds: int,
    show_time: bool,
    expect_dot: bool,
    expect_show: bool,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Parametrized test for rollback_update helper triggers (dot->stationary and show_time->date)."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("get_seconds_from_last_change", {"return_value": seconds}),
            ("change_dot_to_stationary", {}),
            ("change_show_time_to_date", {}),
        ],
    ) as mocks:
        # show_time controls whether change_show_time_to_date should be called
        sensor.get_attr.side_effect = lambda k: show_time if k == CONF_SHOW_TIME else False
        await updater.rollback_update({}, datetime.now(tz=UTC), status)
    if expect_dot:
        mocks["change_dot_to_stationary"].assert_awaited_once()
    else:
        mocks["change_dot_to_stationary"].assert_not_awaited()
    if expect_show:
        mocks["change_show_time_to_date"].assert_awaited_once()
    else:
        mocks["change_show_time_to_date"].assert_not_awaited()


@pytest.mark.asyncio
async def test_get_extended_attr_unknown_type(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    sensor: MockSensor,
) -> None:
    """Logs warning for unknown OSM type and returns early."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "foo"
    sensor.get_attr.side_effect = lambda k: (
        "123" if k == ATTR_OSM_ID else "foo" if k == ATTR_OSM_TYPE else None
    )
    await updater.get_extended_attr()
    assert any("Unknown OSM type" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("osm_type", "expect_call", "expect_log"),
    [
        ("way", True, False),
        ("foo", False, True),
    ],
)
async def test_get_extended_attr_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    osm_type: str,
    expect_call: bool,
    expect_log: bool,
    caplog: pytest.LogCaptureFixture,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Parametrized: extended attr behavior for known and unknown OSM types."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: osm_type
    sensor.get_attr.side_effect = lambda k: (
        "12345"
        if k == ATTR_OSM_ID
        else osm_type
        if k == ATTR_OSM_TYPE
        else "apikey"
        if k == CONF_API_KEY
        else "en"
        if k == CONF_LANGUAGE
        else None
    )
    with stubbed_updater(updater, [("get_dict_from_url", {})]) as mocks:
        await updater.get_extended_attr()
    if expect_call:
        mocks["get_dict_from_url"].assert_awaited()
    if expect_log:
        assert any("Unknown OSM type" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_get_extended_attr_node_triggers_wikidata_lookup(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Test node OSM type triggers details fetch and Wikidata lookup."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Prepare sensor to look like it has an OSM node id/type
    sensor.attrs[ATTR_OSM_ID] = "12345"
    sensor.attrs[ATTR_OSM_TYPE] = "node"
    # Ensure is_attr_blank returns False for checks in get_extended_attr
    sensor.is_attr_blank.side_effect = lambda k: False

    async def fake_get_dict(url: str, name: str, dict_name: str) -> None:
        """Populate staged OSM details and Wikidata responses for the updater.

        Args:
            url: Request URL generated by the updater.
            name: Logical service name used by ``get_dict_from_url``.
            dict_name: Attribute key that would receive the fetched payload.
        """
        # First call: OpenStreetMaps Details -> populate details with wikidata tag
        if name == "OpenStreetMaps Details":
            sensor.attrs[ATTR_OSM_DETAILS_DICT] = {"extratags": {"wikidata": "Q123"}}
            return
        # Second call: Wikidata -> populate wikidata dict
        if name == "Wikidata":
            sensor.attrs[ATTR_WIKIDATA_DICT] = {"id": "Q123", "label": "Test"}
            return

    with stubbed_updater(updater, [("get_dict_from_url", {"side_effect": fake_get_dict})]) as mocks:
        await updater.get_extended_attr()

    # Should have attempted the details lookup and then the wikidata lookup (2 awaits)
    assert_awaited_count(mocks["get_dict_from_url"], 2)
    # The OSM details parsing should have set the wikidata id
    assert sensor.attrs.get(ATTR_WIKIDATA_ID) == "Q123"
    # And the wikidata dict should be present after the second fetch
    assert ATTR_WIKIDATA_DICT in sensor.attrs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expect_log_substr", "expect_cached", "expect_sensor_attr"),
    [
        ("{bad json}", "JSON Decode Error", False, False),
        ('{"error_message": "bad"}', "error occurred contacting the web service", False, False),
        ('[{"k": "v"}]', None, True, True),
    ],
)
async def test_get_dict_from_url_network_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    caplog: pytest.LogCaptureFixture,
    aioclient_mock: AioClientMock,
    payload: str | None,
    expect_log_substr: str | None,
    expect_cached: bool,
    expect_sensor_attr: object,
) -> None:
    """Parametrized network-response variants for get_dict_from_url covering JSON errors, service errors, and 1-item list payloads."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/nettest"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
        }

    # Avoid real network by registering the test payload with aioclient_mock
    register_aioclient(aioclient_mock, url, text=payload)
    await updater.get_dict_from_url(url, "NetService", "dict_name")

    if expect_log_substr:
        assert any(expect_log_substr.lower() in r.getMessage().lower() for r in caplog.records)
    if expect_cached:
        assert mock_hass.data[DOMAIN][OSM_CACHE].get(url) is not None
    if expect_sensor_attr:
        assert sensor.attrs.get("dict_name") == {"k": "v"}


@pytest.mark.asyncio
async def test_get_dict_from_url_list_conversion_and_throttle(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AioClientMock,
    sensor: MockSensor,
) -> None:
    """Ensure get_dict_from_url respects throttle wait and converts single-item list payloads to a dict."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    url = "https://example.com/nominatim/reverse/"
    name = "OSM Test"
    dict_name = ATTR_OSM_DICT

    # Prepare a single-item list JSON response which should be converted to a dict
    resp_text = json.dumps([{"converted": "yes"}])
    register_aioclient(aioclient_mock, url, text=resp_text)

    # Set up throttle so wait_time > 0 and use a real Lock for 'async with' support
    loop = asyncio.get_running_loop()
    last_query = loop.time() - (OSM_THROTTLE_INTERVAL_SECONDS / 2)
    throttle = {"lock": asyncio.Lock(), "last_query": last_query}
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {}
    mock_hass.data[DOMAIN][OSM_CACHE] = {}
    mock_hass.data[DOMAIN][OSM_THROTTLE] = throttle

    # Patch asyncio.sleep so the test doesn't actually sleep but we can assert it was awaited
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    await updater.get_dict_from_url(url=url, name=name, dict_name=dict_name)

    # The single-item list should be converted to a dict and stored
    assert sensor.attrs[dict_name] == {"converted": "yes"}
    # Cache must have been populated
    assert mock_hass.data[DOMAIN][OSM_CACHE][url] == {"converted": "yes"}
    # sleep should have been awaited due to throttle
    sleep_mock.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("native", "prev", "cur", "prev_loc", "distance", "expected"),
    [
        # same location -> SKIP_SET_STATIONARY
        ("state", "state", "1,1", "1,1", 20, UpdateStatus.SKIP_SET_STATIONARY),
        # small distance -> SKIP_SET_STATIONARY
        ("state", "state", "2,2", "3,3", 5, UpdateStatus.SKIP_SET_STATIONARY),
        # different locations and large distance -> PROCEED
        (None, None, "A", "B", 50, UpdateStatus.PROCEED),
    ],
)
async def test_determine_if_update_needed_variants(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    native: object,
    prev: object,
    cur: object,
    prev_loc: object,
    distance: float,
    expected: object,
) -> None:
    """Parametrized variants for determine_if_update_needed covering skip and proceed cases."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    if native is not None:
        sensor.attrs[ATTR_NATIVE_VALUE] = native
    if prev is not None:
        sensor.attrs[ATTR_PREVIOUS_STATE] = prev
    sensor.attrs[ATTR_LOCATION_CURRENT] = cur
    sensor.attrs[ATTR_LOCATION_PREVIOUS] = prev_loc
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = distance
    if expected == UpdateStatus.PROCEED:
        sensor.get_attr.side_effect = lambda k: False
        sensor.is_attr_blank.return_value = False
        sensor.get_attr_safe_str.side_effect = lambda k: (
            cur if k == ATTR_LOCATION_CURRENT else prev_loc if k == ATTR_LOCATION_PREVIOUS else ""
        )
        sensor.get_attr_safe_float.side_effect = lambda k: (
            distance if k == ATTR_DISTANCE_TRAVELED_M else 0
        )
    result = await updater.determine_if_update_needed()
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("has_last_distance", "reported_distance", "last_distance_arg", "expected"),
    [
        # towards home: current 500 < previous 1000
        (None, 500, 1000, "towards home"),
        # away from home: previous recorded and current 1500 > previous 1000
        (1, 1500, 1000, "away from home"),
        # stationary: current equals previous
        (None, 1000, 1000, "stationary"),
    ],
)
async def test_determine_direction_of_travel_param(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    has_last_distance: bool | None,
    reported_distance: float,
    last_distance_arg: float | None,
    expected: object,
) -> None:
    """Parametrized variants for determine_direction_of_travel covering towards/away/stationary cases."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    if has_last_distance is not None:
        sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = has_last_distance
    sensor.get_attr_safe_float.side_effect = lambda k: (
        reported_distance if k == ATTR_DISTANCE_FROM_HOME_M else 0
    )
    # If a previous travel distance exists, emulate is_attr_blank behavior accordingly
    if expected == "towards home":
        # Match original single-case test: explicit side effects
        sensor.is_attr_blank.side_effect = lambda k: False
        sensor.get_attr_safe_float.side_effect = lambda k: (
            500.0 if k == ATTR_DISTANCE_FROM_HOME_M else 1000.0
        )
    elif has_last_distance is not None:
        sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs
    else:
        sensor.is_attr_blank.side_effect = lambda k: False
    await updater.determine_direction_of_travel(last_distance_arg)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == expected


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_skip_missing_attr(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: StubbedUpdater,
) -> None:
    """Returns SKIP when required lat/long/home coordinates are blank after updates."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("update_location_attributes", {}),
            ("calculate_distances", {}),
            ("calculate_travel_distance", {}),
            ("determine_direction_of_travel", {}),
        ],
    ):
        # Need home zone for logging split
        sensor.attrs[CONF_HOME_ZONE] = "zone.home"
        sensor.is_attr_blank.side_effect = lambda k: k in [ATTR_LATITUDE, ATTR_HOME_LATITUDE]
        result = await updater.update_coordinates_and_distance()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_tracker_available_valid(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Returns True for existing tracker state object (not string unavailable)."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Provide tracker id in attrs and let default get_attr work
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.is_attr_blank.side_effect = lambda k: (
        k not in sensor.attrs
        or sensor.attrs.get(k)
        in (
            None,
            "",
        )
    )
    state = MagicMock()
    state.attributes = {}
    mock_hass.states.get.return_value = state
    result = await updater.is_tracker_available()
    assert result is True


@pytest.mark.asyncio
async def test_log_tracker_issue_initial_update(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logs warning during initial update even if warn flag not set."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = False
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    await updater.log_tracker_issue("Msg")
    assert any("Msg" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fire_event_data_includes_core_attributes(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Build and fire an event with expected core keys."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Make sensor report values for several keys so event_data is populated
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = lambda k: (
        "TestName"
        if k == CONF_NAME
        else "Prev"
        if k == ATTR_PREVIOUS_STATE
        else "Now"
        if k == ATTR_NATIVE_VALUE
        else "LP"
        if k == ATTR_LAST_PLACE_NAME
        else "ext"
    )

    await updater.fire_event_data(prev_last_place_name="Other")

    # Ensure an event was fired with expected structure
    mock_hass.bus.fire.assert_called_once()
    called_event = mock_hass.bus.fire.call_args[0]
    assert called_event[0] == "places_state_update"
    assert isinstance(called_event[1], dict)
    # Check that core keys are present
    assert "entity" in called_event[1]
    assert "from_state" in called_event[1]
    assert "to_state" in called_event[1]


@pytest.mark.asyncio
async def test_fire_event_data_omits_raw_extended_payloads(updater: PlacesUpdater) -> None:
    """Places state update events should not carry raw extended dict payloads."""
    updater.coordinator.set_attr(CONF_EXTENDED_ATTR, True)
    updater.coordinator.set_attr(ATTR_OSM_DICT, {"raw": "payload"})
    updater.coordinator.set_attr(ATTR_OSM_DETAILS_DICT, {"details": "payload"})
    updater.coordinator.set_attr(ATTR_WIKIDATA_DICT, {"wikidata": "payload"})
    updater._hass.bus.fire = MagicMock()

    await updater.fire_event_data(prev_last_place_name="")

    event_data = updater._hass.bus.fire.call_args.args[1]
    assert ATTR_OSM_DICT not in event_data
    assert ATTR_OSM_DETAILS_DICT not in event_data
    assert ATTR_WIKIDATA_DICT not in event_data


@pytest.mark.asyncio
async def test_log_coordinate_issue_warn_flag(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logs warning when warn_if_device_tracker_prob set for coordinate issue."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = True
    sensor.get_attr.side_effect = lambda k: (
        "device_tracker.test" if k == CONF_DEVICETRACKER_ID else False
    )
    await updater.log_coordinate_issue()
    assert any("Latitude/Longitude is not set" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("tz", ["UTC", None])
async def test_get_current_time_variants(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor, tz: str | None
) -> None:
    """Return timezone-aware datetime with and without a configured HA timezone."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    mock_hass.config.time_zone = tz
    dt = await updater.get_current_time()
    assert dt.tzinfo is not None
    if mock_hass.config.time_zone is None:
        assert dt.tzinfo is UTC


@pytest.mark.asyncio
async def test_get_dict_from_url_respects_throttle(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AioClientMock,
    sensor: MockSensor,
) -> None:
    """Ensure the throttle path calls asyncio.sleep when last_query indicates we must wait."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/throttle/"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
        }

    # Set last_query to now so wait_time = interval (positive)
    mock_hass.data[DOMAIN][OSM_THROTTLE]["last_query"] = asyncio.get_running_loop().time()

    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    register_aioclient(aioclient_mock, url, text='{"ok": 1}')

    await updater.get_dict_from_url(url, "ThrottleService", "dict_name")
    # Ensure we attempted to sleep (throttle honored)
    sleep_mock.assert_awaited_once()
    # And the result stored in cache
    assert mock_hass.data[DOMAIN][OSM_CACHE].get(url) is not None


@pytest.mark.asyncio
async def test_get_dict_from_url_handles_network_error(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    aioclient_mock: AioClientMock,
    sensor: MockSensor,
) -> None:
    """If aiohttp raises ClientError, get_dict_from_url should log a warning and not set cache."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://example.com/network-error/"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": asyncio.Lock(), "last_query": 0},
        }

    # Simulate aiohttp.ClientError when getting the URL
    aioclient_mock.get(url, exc=aiohttp.ClientError("fail"))
    await updater.get_dict_from_url(url, "BadService", "dict_name")
    assert "Error connecting to BadService" in caplog.text
    assert mock_hass.data[DOMAIN][OSM_CACHE].get(url) is None
