"""Unit tests for the PlacesUpdater class and related update logic."""

import asyncio
from datetime import datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import aiohttp
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
from custom_components.places.update_sensor import PlacesUpdater
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
from tests.conftest import assert_awaited_count, stub_in_zone, stubbed_parser, stubbed_sensor

# Preserve original constructor reference so helper can delegate to it when needed
_OriginalPlacesUpdater = PlacesUpdater


def make_updater(*args, **kwargs):
    """Create a fresh PlacesUpdater instance for tests via the preserved constructor.

    Accepts arbitrary args/kwargs so tests that pass positional or keyword arguments
    continue to work without signature mismatches.
    """
    return _OriginalPlacesUpdater(*args, **kwargs)


@pytest.fixture
def mock_config_entry():
    """Create and return a mock configuration entry with default sensor name and empty options for testing purposes."""
    return MockConfigEntry(domain="places", data={CONF_NAME: "TestSensor"}, options={})


def register_aioclient(aioclient_mock, url: str, **kwargs):
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
    "check_result,should_rollback,should_handle",
    [
        (UpdateStatus.PROCEED, False, True),
        (UpdateStatus.SKIP, True, False),
    ],
)
async def test_do_update_flow_variants(
    mock_hass,
    mock_config_entry,
    sensor,
    stubbed_updater,
    check_result,
    should_rollback,
    should_handle,
):
    """Parametrized test covering both PROCEED and SKIP paths for do_update."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("get_current_time", {"return_value": datetime(2024, 1, 1, 12, 0)}),
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


@pytest.mark.asyncio
async def test_handle_state_update_sets_native_value_and_calls_helpers(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Set native value and process extended attributes during state update."""
    # Ensure extended attribute logic is triggered and show_time path exercised
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    # Sensor reports extended attrs enabled and show_time enabled
    sensor.get_attr.side_effect = (
        lambda k: True
        if k in (CONF_EXTENDED_ATTR, CONF_SHOW_TIME)
        else "TestSensor"
        if k == CONF_NAME
        else None
    )
    sensor.get_attr_safe_str.side_effect = lambda k: "TestState" if k == ATTR_NATIVE_VALUE else ""
    sensor.is_attr_blank.side_effect = lambda k: False

    # Patch async helpers so we don't hit external logic
    with stubbed_updater(updater, [("get_extended_attr", {}), ("fire_event_data", {})]) as mocks:
        now = datetime(2024, 1, 1, 12, 0)
        await updater.handle_state_update(now=now, prev_last_place_name="PrevPlace")

    # Extended attr logic should have been invoked and event fired
    mocks["get_extended_attr"].assert_awaited_once()
    mocks["fire_event_data"].assert_awaited_once()
    # show_time path should set a native value with suffix
    assert sensor.native_value is not None
    # write_sensor_to_json is executed via hass.async_add_executor_job
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_new_name(
    mock_hass, mock_config_entry, sensor
):
    """Test that the entity name is updated and the config entry is updated when a new friendly name is detected."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.entity_id = "sensor.test"
    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    sensor.get_attr.return_value = "OldName"
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "show_time, expected",
    [
        (True, "TestVal"),
        (False, False),
    ],
)
async def test_update_previous_state_variants(
    mock_hass, mock_config_entry, sensor, show_time, expected
):
    """Parametrized: previous state handling when show-time enabled or disabled."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

    if show_time:
        sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
        sensor.get_attr.side_effect = lambda k: True if k == CONF_SHOW_TIME else "TestVal"
        # Use side_effect to keep behaviour consistent with other branches
        sensor.get_attr_safe_str.side_effect = lambda k: "TestVal" if k == ATTR_NATIVE_VALUE else ""
    else:
        sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
        sensor.get_attr.side_effect = (
            lambda k: "PrevStateValue" if k == ATTR_PREVIOUS_STATE else False
        )
        sensor.get_attr_safe_str.side_effect = (
            lambda k: "PrevStateValue" if k in [ATTR_NATIVE_VALUE, ATTR_PREVIOUS_STATE] else ""
        )

    await updater.update_previous_state()
    assert sensor.attrs[ATTR_PREVIOUS_STATE] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lat_val, lon_val, expect_lat_old, expect_lon_old",
    [
        (1.0, 1.0, 1.0, 1.0),
        ("not_a_float", 2.0, None, 2.0),
        (1.0, "not_a_float", 1.0, None),
    ],
)
async def test_update_old_coordinates_param(
    mock_hass, mock_config_entry, sensor, lat_val, lon_val, expect_lat_old, expect_lon_old
):
    """Parametrized: update_old_coordinates sets only valid numeric old coordinate attributes."""
    sensor.attrs[ATTR_LATITUDE] = lat_val
    sensor.attrs[ATTR_LONGITUDE] = lon_val
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "gps_result,expected",
    [
        (UpdateStatus.PROCEED, UpdateStatus.PROCEED),
        (UpdateStatus.SKIP, UpdateStatus.SKIP),
    ],
)
async def test_check_device_tracker_and_update_coords_param(
    mock_hass, mock_config_entry, sensor, stubbed_updater, gps_result, expected
):
    """Parametrized test: check_device_tracker_and_update_coords propagates GPS accuracy results and always updates coordinates first."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    if gps_result == UpdateStatus.PROCEED:
        mocks["get_gps_accuracy"].assert_awaited_once()


@pytest.mark.asyncio
async def test_get_gps_accuracy_sets_accuracy(mock_hass, mock_config_entry, sensor):
    """Retrieve GPS accuracy and set sensor attribute when available."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "tracker_attrs, use_gps, expected",
    [
        ({ATTR_GPS_ACCURACY: 5.0}, True, UpdateStatus.PROCEED),
        ({ATTR_GPS_ACCURACY: 0}, True, UpdateStatus.SKIP),
    ],
)
async def test_get_gps_accuracy_variants(
    mock_hass, mock_config_entry, sensor, tracker_attrs, use_gps, expected
):
    """Parametrized variants for get_gps_accuracy: valid accuracy, zero accuracy, and missing tracker."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

    tracker_state = MagicMock() if tracker_attrs is not None else None
    if tracker_attrs is not None:
        tracker_state.attributes = tracker_attrs
    mock_hass.states.get.return_value = tracker_state

    # Populate required attributes where relevant
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.attrs[CONF_USE_GPS] = use_gps

    # is_attr_blank should evaluate based on actual attrs
    sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs or sensor.attrs.get(k) in (
        None,
        "",
    )

    result = await updater.get_gps_accuracy()
    assert result == expected


@pytest.mark.asyncio
async def test_update_coordinates_variants_present_and_missing(
    mock_hass, mock_config_entry, sensor, caplog
):
    """Parametrized-like variant: when tracker present set coords, when missing log warning."""
    # Present case
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Test that `determine_update_criteria` calls all required helper methods and returns the correct update status."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "in_zone,place_name,zone_name,expected",
    [
        (False, "PlaceName", None, "PlaceName"),
        (True, None, "ZoneName", "ZoneName"),
    ],
)
async def test_get_initial_last_place_name_param(
    mock_hass, mock_config_entry, sensor, in_zone, place_name, zone_name, expected
):
    """Parametrized test for get_initial_last_place_name covering zone and non-zone cases."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "scenario,setup_func,expected_zone,expected_zone_name_present,expected_zone_name",
    [
        (
            "not_zone",
            lambda sensor, mock_hass: (
                sensor.get_attr_safe_str.__setattr__(
                    "side_effect",
                    (
                        lambda k: "home"
                        if k == ATTR_DEVICETRACKER_ZONE_NAME
                        else "device_tracker.test"
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
                        lambda eid: MagicMock(attributes={CONF_ZONE: "home"})
                        if eid == "device_tracker.test"
                        else MagicMock(attributes={CONF_FRIENDLY_NAME: "Home Zone"})
                        if eid == "zone.home"
                        else None
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
                        lambda eid: MagicMock(attributes={CONF_ZONE: "home"})
                        if eid == "device_tracker.test"
                        else None
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
    mock_hass,
    mock_config_entry,
    sensor,
    scenario,
    setup_func,
    expected_zone,
    expected_zone_name_present,
    expected_zone_name,
):
    """Parametrized variants for get_zone_details covering zone and non-zone flows."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
async def test_process_osm_update_calls(mock_hass, mock_config_entry, sensor, stubbed_updater):
    """Test that `process_osm_update` calls attribute reset, map link generation, and OSM query finalization methods as expected."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("async_reset_attributes", {}),
            ("get_map_link", {}),
            ("query_osm_and_finalize", {}),
        ],
    ) as mocks:
        await updater.process_osm_update(datetime(2024, 1, 1, 12, 0))
    mocks["async_reset_attributes"].assert_awaited_once()
    mocks["get_map_link"].assert_awaited_once()
    mocks["query_osm_and_finalize"].assert_awaited_once()


def assert_map_link_set(sensor):
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
async def test_get_map_link_providers_all(mock_hass, mock_config_entry, sensor, provider):
    """Parametrized: verify map link generation for multiple providers including OSM."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    if provider == "osm":
        # OSM needs lat/lon floats
        sensor.get_attr.side_effect = lambda k: "osm" if k == CONF_MAP_PROVIDER else 10
        sensor.get_attr_safe_float.side_effect = (
            lambda k: 1.23456789 if k == ATTR_LATITUDE else 9.87654321
        )
    else:
        sensor.get_attr.side_effect = (
            lambda k: provider
            if k == CONF_MAP_PROVIDER
            else "loc"
            if k == ATTR_LOCATION_CURRENT
            else 10
        )
    await updater.get_map_link()
    assert_map_link_set(sensor)


@pytest.mark.asyncio
async def test_async_reset_attributes_calls(mock_hass, mock_config_entry, sensor):
    """Test that `async_reset_attributes` clears sensor attributes and performs asynchronous cleanup."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    await updater.async_reset_attributes()
    sensor.clear_attr.assert_called()
    sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prev_val, native_val, expected",
    [
        ("a", "b", True),
        ("a", "a", False),
    ],
)
async def test_should_update_state_param(
    mock_hass, mock_config_entry, sensor, prev_val, native_val, expected
):
    """Parametrized test for `should_update_state` for differing and equal values."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = (
        lambda k: prev_val
        if k == ATTR_PREVIOUS_STATE
        else native_val
        if k == ATTR_NATIVE_VALUE
        else ""
    )
    sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now())
    assert result is expected


@pytest.mark.asyncio
async def test_rollback_update_calls_restore_and_helpers(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Restore previous attributes and conditionally call helper routines."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
        await updater.rollback_update({"a": 1}, datetime.now(), UpdateStatus.SKIP_SET_STATIONARY)
    sensor.restore_previous_attr.assert_awaited_once()
    # Based on the test setup (proceed SKIP_SET_STATIONARY, default direction not 'stationary', seconds=100),
    # change_dot_to_stationary should have been awaited once; show_time helper should not be awaited.
    mocks["change_dot_to_stationary"].assert_awaited_once()
    mocks["change_show_time_to_date"].assert_not_awaited()


@pytest.mark.asyncio
async def test_build_osm_url_returns_url(mock_hass, mock_config_entry, sensor):
    """Test that `build_osm_url` constructs a valid OpenStreetMap reverse geocoding URL using sensor attributes."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    sensor.get_attr.side_effect = (
        lambda k: "en" if k == CONF_LANGUAGE else "apikey" if k == CONF_API_KEY else 18
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
    "cached,payload,expected_attr,network_error",
    [
        (True, None, {"a": 1}, False),
        (False, '[{"a": 1}]', {"a": 1}, False),
        (False, None, None, True),
    ],
)
async def test_get_dict_from_url_variants(
    mock_hass,
    mock_config_entry,
    aioclient_mock,
    sensor,
    cached,
    payload,
    expected_attr,
    network_error,
):
    """Parametrized: cache hit, list-payload behavior, and network-error for get_dict_from_url."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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


# Network-error case moved into parametrized `test_get_dict_from_url_variants`


@pytest.mark.asyncio
async def test_determine_if_update_needed_initial_update(mock_hass, mock_config_entry, sensor):
    """Test that `determine_if_update_needed` returns `PROCEED` when the initial update attribute is set to True."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_update_location_attributes_sets_locations(mock_hass, mock_config_entry, sensor):
    """Test that `update_location_attributes` sets current, previous, and home location attributes to the expected values."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_location_attributes()
    assert sensor.attrs[ATTR_LOCATION_CURRENT] == "1.0,1.0"
    assert sensor.attrs[ATTR_LOCATION_PREVIOUS] == "1.0,1.0"
    assert sensor.attrs[ATTR_HOME_LOCATION] == "1.0,1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name, expected_m_attr, expected_mi_attr",
    [
        ("calculate_distances", ATTR_DISTANCE_FROM_HOME_M, ATTR_DISTANCE_FROM_HOME_MI),
        ("calculate_travel_distance", ATTR_DISTANCE_TRAVELED_M, ATTR_DISTANCE_TRAVELED_MI),
    ],
)
async def test_calculate_distance_methods(
    mock_hass, mock_config_entry, sensor, method_name, expected_m_attr, expected_mi_attr
):
    """Parametrized test for distance calculation methods to validate m and mi attributes are set appropriately."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Call coordinate and distance helpers and return PROCEED."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
async def test_get_seconds_from_last_change_param(mock_hass, mock_config_entry, sensor, scenario):
    """Parametrized variants for get_seconds_from_last_change covering various error and success paths."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    now = datetime.now()

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

        class BadDatetime(datetime):
            def __sub__(self, other):
                raise TypeError("test")

        bad_dt = BadDatetime.now()
        sensor.get_attr_safe_str.return_value = bad_dt.isoformat()
        with patch("custom_components.places.update_sensor.datetime") as mock_dt:
            # Use side_effect for fromisoformat to avoid mixing return_value and side_effect
            mock_dt.fromisoformat.side_effect = lambda s: bad_dt
            mock_dt.now.return_value = bad_dt
            result = await updater.get_seconds_from_last_change(bad_dt)
            assert result == 3600
        return

    # value_error
    sensor.get_attr_safe_str.return_value = "bad-date"
    with patch("custom_components.places.update_sensor.datetime") as mock_dt:
        mock_dt.fromisoformat.side_effect = ValueError("bad date format")
        mock_dt.now.return_value = now
        result = await updater.get_seconds_from_last_change(now)
        assert result == 3600


@pytest.mark.asyncio
@pytest.mark.parametrize("date_format", ["dd/mm", "mm/dd"])
async def test_change_show_time_to_date_param(mock_hass, mock_config_entry, sensor, date_format):
    """Parametrized test for change_show_time_to_date handling both dd/mm and mm/dd formats."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else date_format
        if k == CONF_DATE_FORMAT
        else "2024-01-01 12:00:00"
    )
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "2024-01-01 12:00:00" if k == ATTR_LAST_CHANGED else "TestState"
    )
    await updater.change_show_time_to_date()
    assert sensor.native_value is not None
    assert sensor.attrs[ATTR_SHOW_DATE] is True
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_dot_to_stationary_sets_direction_and_last_changed(
    mock_hass, mock_config_entry, sensor
):
    """Set direction to 'stationary' and update last_changed, scheduling executor job."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    await updater.change_dot_to_stationary(datetime(2024, 1, 1, 12, 0), 100)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"
    assert sensor.attrs[ATTR_LAST_CHANGED] == "2024-01-01 12:00:00"
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tracker_available,has_valid_coords,expected",
    [
        (False, None, UpdateStatus.SKIP),
        (True, False, UpdateStatus.SKIP),
        (True, True, UpdateStatus.PROCEED),
    ],
)
async def test_is_devicetracker_set_param(
    mock_hass,
    mock_config_entry,
    sensor,
    stubbed_updater,
    tracker_available,
    has_valid_coords,
    expected,
):
    """Parametrized test for is_devicetracker_set covering not available, invalid coords, and proceed."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "tracker_state, expected_result",
    [
        (None, False),
        ("unavailable", False),
        (MagicMock(state="home"), True),
    ],
)
async def test_is_tracker_available_param(
    mock_hass, mock_config_entry, sensor, tracker_state, expected_result
):
    """Test is_tracker_available for missing, unavailable, and valid tracker states."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    "tracker_attrs, expected_result",
    [
        (None, False),
        ({CONF_LATITUDE: None, CONF_LONGITUDE: None}, False),
        ({CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0}, True),
    ],
)
async def test_has_valid_coordinates_param(
    mock_hass, mock_config_entry, sensor, tracker_attrs, expected_result
):
    """Test has_valid_coordinates for missing, bad, and valid lat/lon attributes."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
async def test_log_tracker_issue_param(mock_hass, mock_config_entry, sensor, caplog, warn_flag):
    """Test log_tracker_issue for both warn and info levels."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Test that query_osm_and_finalize runs the OSM parser, finalizes the last place name, processes display options, and sets last_changed."""
    sensor.attrs["osm_dict"] = {"some": "value"}
    sensor.attrs["last_place_name"] = "TestPlace"
    mock_parser = AsyncMock()
    # Create a single updater instance and stub its methods; do NOT create a second instance
    # inside the context (previous version created a new instance whose methods were not stubbed,
    # leading to the real get_dict_from_url accessing hass.data and raising KeyError).
    updater = make_updater(
        hass=mock_hass,
        config_entry=mock_config_entry,
        sensor=sensor,
    )
    with (
        stubbed_sensor(sensor, [("process_display_options", {})]) as sensor_mocks,
        stubbed_parser(
            mock_parser, [("parse_osm_dict", {}), ("finalize_last_place_name", {})]
        ) as parser_mocks,
        patch("custom_components.places.update_sensor.OSMParser", return_value=mock_parser),
        stubbed_updater(
            updater,
            [
                ("build_osm_url", {"return_value": "http://test-url"}),
                ("get_dict_from_url", {}),
            ],
        ) as updater_mocks,
    ):
        now = datetime(2024, 1, 1, 12, 0, 0)
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
    mock_hass, mock_config_entry, sensor, blank_attr
):
    """Test calculate_distances does NOT set distance attributes if any required attribute is blank."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    # Patch is_attr_blank to return True for the blank_attr, False otherwise
    sensor.is_attr_blank = lambda k: k == blank_attr
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    await updater.calculate_distances()
    # None of the distance attributes should be set
    assert ATTR_DISTANCE_FROM_HOME_M not in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_KM not in sensor.attrs
    assert ATTR_DISTANCE_FROM_HOME_MI not in sensor.attrs


@pytest.mark.asyncio
async def test_calculate_distances_distance_from_home_m_blank(mock_hass, mock_config_entry, sensor):
    """Test calculate_distances does NOT set KM/MI if ATTR_DISTANCE_FROM_HOME_M is blank after calculation."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

    # Patch is_attr_blank so ATTR_DISTANCE_FROM_HOME_M is blank after calculation
    def is_attr_blank(key):
        # Only ATTR_DISTANCE_FROM_HOME_M is blank
        return key == ATTR_DISTANCE_FROM_HOME_M

    sensor.is_attr_blank = is_attr_blank
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    # Patch get_attr_safe_float to return valid floats
    sensor.get_attr_safe_float = lambda k: 1.0
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
    "mode, blank_attr, expected_direction, expect_mi",
    [
        ("normal", None, None, True),
        ("missing_old_coord", ATTR_LATITUDE_OLD, "stationary", True),
        ("blank_traveled_m", ATTR_DISTANCE_TRAVELED_M, None, False),
    ],
)
async def test_calculate_travel_distance_variants(
    mock_hass, mock_config_entry, sensor, mode, blank_attr, expected_direction, expect_mi
):
    """Parametrized variants for calculate_travel_distance covering normal, missing old coords, and blank traveled m."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

    # Default behaviors
    sensor.get_attr_safe_float = lambda k: 1.0

    if mode == "missing_old_coord":
        sensor.is_attr_blank = lambda k: k == blank_attr
        # Ensure set_attr updates attrs for this branch
        sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
        await updater.calculate_travel_distance()
        assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == expected_direction
        assert sensor.attrs[ATTR_DISTANCE_TRAVELED_M] == 0
        assert sensor.attrs[ATTR_DISTANCE_TRAVELED_MI] == 0
        return

    if mode == "blank_traveled_m":
        sensor.is_attr_blank = lambda k: k == blank_attr
        # Provide old coords so calculation proceeds
        for attr in [ATTR_LATITUDE_OLD, ATTR_LONGITUDE_OLD]:
            sensor.attrs[attr] = 1.0
        # Ensure set_attr updates attrs for this branch
        sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
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
async def test_get_gps_accuracy_zero_accuracy_skip(mock_hass, mock_config_entry, sensor):
    """GPS accuracy 0 with use_gps True causes SKIP."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {ATTR_GPS_ACCURACY: 0}
    mock_hass.states.get.return_value = tracker_state
    # Populate required attributes
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.attrs[CONF_USE_GPS] = True
    # is_attr_blank should evaluate based on actual attrs (don't force False globally)
    sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs or sensor.attrs.get(k) in (
        None,
        "",
    )
    result = await updater.get_gps_accuracy()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_check_device_tracker_and_update_coords_get_gps_accuracy_skip(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """If get_gps_accuracy returns SKIP that status is propagated."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    with stubbed_updater(
        updater,
        [
            ("is_devicetracker_set", {"return_value": UpdateStatus.PROCEED}),
            ("update_coordinates", {}),
            ("get_gps_accuracy", {"return_value": UpdateStatus.SKIP}),
        ],
    ) as mocks:
        result = await updater.check_device_tracker_and_update_coords()
    assert result == UpdateStatus.SKIP
    mocks["update_coordinates"].assert_awaited_once()


@pytest.mark.asyncio
async def test_update_coordinates_device_tracker_missing(
    mock_hass, mock_config_entry, caplog, sensor
):
    """update_coordinates logs warning and returns when tracker missing."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    mock_hass.states.get.return_value = None
    await updater.update_coordinates()
    assert any("Device tracker entity not found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_determine_update_criteria_skip_before_determine_if_update_needed(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """If update_coordinates_and_distance returns SKIP then determine_if_update_needed not called."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    mock_hass, mock_config_entry, sensor
):
    """Retains previous last_place_name when not in zone and place_name blank."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_PLACE_NAME
    sensor.attrs["last_place_name"] = "Prev"
    with stub_in_zone(sensor, False):
        await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == "Prev"


@pytest.mark.asyncio
async def test_query_osm_and_finalize_no_osm_dict(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """If OSM dict blank parser isn't invoked and last_changed not set."""
    sensor.attrs[ATTR_OSM_DICT] = None
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    with (
        patch("custom_components.places.update_sensor.OSMParser") as mock_parser_cls,
        stubbed_sensor(sensor, [("process_display_options", {})]),
        stubbed_updater(
            updater,
            [("build_osm_url", {"return_value": "http://url"}), ("get_dict_from_url", {})],
        ),
    ):
        now = datetime(2024, 1, 1, 0, 0, 0)
        await updater.query_osm_and_finalize(now)
    mock_parser_cls.assert_not_called()
    assert ATTR_LAST_CHANGED not in sensor.attrs


@pytest.mark.asyncio
async def test_should_update_state_initial_update_true(mock_hass, mock_config_entry, sensor):
    """Returns True when ATTR_INITIAL_UPDATE flag set (forces update)."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: k == ATTR_INITIAL_UPDATE
    sensor.is_attr_blank.return_value = True
    result = await updater.should_update_state(datetime.now())
    assert result is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,seconds,show_time,expect_dot,expect_show",
    [
        (UpdateStatus.SKIP_SET_STATIONARY, 120, False, True, False),
        (UpdateStatus.PROCEED, 90000, True, False, True),
    ],
)
async def test_rollback_update_triggers_helpers(
    mock_hass,
    mock_config_entry,
    sensor,
    status,
    seconds,
    show_time,
    expect_dot,
    expect_show,
    stubbed_updater,
):
    """Parametrized test for rollback_update helper triggers (dot->stationary and show_time->date)."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
        await updater.rollback_update({}, datetime.now(), status)
    if expect_dot:
        mocks["change_dot_to_stationary"].assert_awaited_once()
    else:
        mocks["change_dot_to_stationary"].assert_not_awaited()
    if expect_show:
        mocks["change_show_time_to_date"].assert_awaited_once()
    else:
        mocks["change_show_time_to_date"].assert_not_awaited()


@pytest.mark.asyncio
async def test_get_extended_attr_unknown_type(mock_hass, mock_config_entry, caplog, sensor):
    """Logs warning for unknown OSM type and returns early."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "foo"
    sensor.get_attr.side_effect = (
        lambda k: "123" if k == ATTR_OSM_ID else "foo" if k == ATTR_OSM_TYPE else None
    )
    await updater.get_extended_attr()
    assert any("Unknown OSM type" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "osm_type, expect_call, expect_log",
    [
        ("way", True, False),
        ("foo", False, True),
    ],
)
async def test_get_extended_attr_variants(
    mock_hass,
    mock_config_entry,
    sensor,
    osm_type,
    expect_call,
    expect_log,
    caplog,
    stubbed_updater,
):
    """Parametrized: extended attr behavior for known and unknown OSM types."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: osm_type
    sensor.get_attr.side_effect = (
        lambda k: "12345"
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
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Test node OSM type triggers details fetch and Wikidata lookup."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

    # Prepare sensor to look like it has an OSM node id/type
    sensor.attrs[ATTR_OSM_ID] = "12345"
    sensor.attrs[ATTR_OSM_TYPE] = "node"
    # Ensure is_attr_blank returns False for checks in get_extended_attr
    sensor.is_attr_blank.side_effect = lambda k: False

    async def fake_get_dict(url, name, dict_name):
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
    "payload, expect_log_substr, expect_cached, expect_sensor_attr",
    [
        ("{bad json}", "JSON Decode Error", False, False),
        ('{"error_message": "bad"}', "error occurred contacting the web service", False, False),
        ('[{"k": "v"}]', None, True, True),
    ],
)
async def test_get_dict_from_url_network_variants(
    mock_hass,
    mock_config_entry,
    sensor,
    caplog,
    aioclient_mock,
    payload,
    expect_log_substr,
    expect_cached,
    expect_sensor_attr,
):
    """Parametrized network-response variants for get_dict_from_url covering JSON errors, service errors, and 1-item list payloads."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    monkeypatch, mock_hass, mock_config_entry, aioclient_mock, sensor
):
    """Ensure get_dict_from_url respects throttle wait and converts single-item list payloads to a dict."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

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
    "native,prev,cur,prev_loc,distance,expected",
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
    mock_hass, mock_config_entry, sensor, native, prev, cur, prev_loc, distance, expected
):
    """Parametrized variants for determine_if_update_needed covering skip and proceed cases."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
        sensor.get_attr_safe_str.side_effect = (
            lambda k: cur
            if k == ATTR_LOCATION_CURRENT
            else prev_loc
            if k == ATTR_LOCATION_PREVIOUS
            else ""
        )
        sensor.get_attr_safe_float.side_effect = (
            lambda k: distance if k == ATTR_DISTANCE_TRAVELED_M else 0
        )
    result = await updater.determine_if_update_needed()
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_last_distance,reported_distance,last_distance_arg,expected",
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
    mock_hass,
    mock_config_entry,
    sensor,
    has_last_distance,
    reported_distance,
    last_distance_arg,
    expected,
):
    """Parametrized variants for determine_direction_of_travel covering towards/away/stationary cases."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    if has_last_distance is not None:
        sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = has_last_distance
    sensor.get_attr_safe_float.side_effect = (
        lambda k: reported_distance if k == ATTR_DISTANCE_FROM_HOME_M else 0
    )
    # If a previous travel distance exists, emulate is_attr_blank behavior accordingly
    if expected == "towards home":
        # Match original single-case test: explicit side effects
        sensor.is_attr_blank.side_effect = lambda k: False
        sensor.get_attr_safe_float.side_effect = (
            lambda k: 500.0 if k == ATTR_DISTANCE_FROM_HOME_M else 1000.0
        )
    elif has_last_distance is not None:
        sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs
    else:
        sensor.is_attr_blank.side_effect = lambda k: False
    await updater.determine_direction_of_travel(last_distance_arg)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == expected


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_skip_missing_attr(
    mock_hass, mock_config_entry, sensor, stubbed_updater
):
    """Returns SKIP when required lat/long/home coordinates are blank after updates."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
async def test_is_tracker_available_valid(mock_hass, mock_config_entry, sensor):
    """Returns True for existing tracker state object (not string unavailable)."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    # Provide tracker id in attrs and let default get_attr work
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.test"
    sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs or sensor.attrs.get(k) in (
        None,
        "",
    )
    state = MagicMock()
    state.attributes = {}
    mock_hass.states.get.return_value = state
    result = await updater.is_tracker_available()
    assert result is True


@pytest.mark.asyncio
async def test_has_valid_coordinates_non_numeric(mock_hass, mock_config_entry, sensor):
    """Returns False when latitude not numeric though attribute exists."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: "a", CONF_LONGITUDE: 2.0}
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is False


@pytest.mark.asyncio
async def test_log_tracker_issue_initial_update(mock_hass, mock_config_entry, sensor, caplog):
    """Logs warning during initial update even if warn flag not set."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = False
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    await updater.log_tracker_issue("Msg")
    assert any("Msg" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fire_event_data_includes_extended_and_attributes(
    mock_hass, mock_config_entry, sensor
):
    """Builds and fires event with expected keys including extended attributes."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)

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

    # Ensure extended attributes are included
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
async def test_log_coordinate_issue_warn_flag(mock_hass, mock_config_entry, sensor, caplog):
    """Logs warning when warn_if_device_tracker_prob set for coordinate issue."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = True
    sensor.get_attr.side_effect = lambda k: (
        "device_tracker.test" if k == CONF_DEVICETRACKER_ID else False
    )
    await updater.log_coordinate_issue()
    assert any("Latitude/Longitude is not set" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("tz", ["UTC", None])
async def test_get_current_time_variants(mock_hass, mock_config_entry, sensor, tz):
    """Return timezone-aware datetime when hass.config.time_zone set, naive when not."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
    mock_hass.config.time_zone = tz
    dt = await updater.get_current_time()
    if tz:
        assert dt.tzinfo is not None
    else:
        assert dt.tzinfo is None


@pytest.mark.asyncio
async def test_get_dict_from_url_respects_throttle(
    monkeypatch, mock_hass, mock_config_entry, aioclient_mock, sensor
):
    """Ensure the throttle path calls asyncio.sleep when last_query indicates we must wait."""
    updater = make_updater(mock_hass, mock_config_entry, sensor)
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
    monkeypatch, mock_hass, mock_config_entry, caplog, aioclient_mock, sensor
):
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
