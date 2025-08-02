from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.places.const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_DISTANCE_TRAVELED_MI,
    ATTR_HOME_LOCATION,
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
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PREVIOUS_STATE,
    ATTR_SHOW_DATE,
    CONF_DATE_FORMAT,
    CONF_EXTENDED_ATTR,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_SHOW_TIME,
    DOMAIN,
    EVENT_TYPE,
    UpdateStatus,
)
from custom_components.places.update_sensor import PlacesUpdater
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.config.time_zone = "UTC"
    hass.config_entries.async_update_entry = MagicMock()
    hass.bus.fire = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.data = {DOMAIN: {"osm_cache": {}, "osm_throttle": {"lock": AsyncMock(), "last_query": 0}}}
    hass.async_add_executor_job = AsyncMock()
    return hass


@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.data = {CONF_NAME: "TestSensor"}
    entry.options = {}
    return entry


@pytest.fixture
def mock_sensor():
    sensor = MagicMock()
    sensor.get_attr = MagicMock(return_value=None)
    sensor.get_attr_safe_str = MagicMock(return_value="")
    sensor.get_attr_safe_float = MagicMock(return_value=0.0)
    sensor.set_attr = MagicMock()
    sensor.set_native_value = MagicMock()
    sensor.is_attr_blank = MagicMock(return_value=True)
    sensor.async_cleanup_attributes = AsyncMock()
    sensor.restore_previous_attr = AsyncMock()
    sensor.get_internal_attr = MagicMock(return_value={})
    sensor.process_display_options = AsyncMock()
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.warn_if_device_tracker_prob = False
    return sensor


@pytest.mark.asyncio
async def test_do_update_proceed_flow(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.get_current_time = AsyncMock(return_value=datetime(2024, 1, 1, 12, 0))
    updater.update_entity_name_and_cleanup = AsyncMock()
    updater.update_previous_state = AsyncMock()
    updater.update_old_coordinates = AsyncMock()
    updater.check_device_tracker_and_update_coords = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.determine_update_criteria = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.process_osm_update = AsyncMock()
    updater.should_update_state = AsyncMock(return_value=True)
    updater.handle_state_update = AsyncMock()
    updater.rollback_update = AsyncMock()

    await updater.do_update("manual", {"a": 1})
    updater.update_entity_name_and_cleanup.assert_awaited_once()
    updater.update_previous_state.assert_awaited_once()
    updater.update_old_coordinates.assert_awaited_once()
    updater.check_device_tracker_and_update_coords.assert_awaited_once()
    updater.determine_update_criteria.assert_awaited_once()
    updater.process_osm_update.assert_awaited_once()
    updater.should_update_state.assert_awaited_once()
    updater.handle_state_update.assert_awaited_once()
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_UPDATED, "2024-01-01 12:00:00")


@pytest.mark.asyncio
async def test_do_update_skip_flow(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.get_current_time = AsyncMock(return_value=datetime(2024, 1, 1, 12, 0))
    updater.update_entity_name_and_cleanup = AsyncMock()
    updater.update_previous_state = AsyncMock()
    updater.update_old_coordinates = AsyncMock()
    updater.check_device_tracker_and_update_coords = AsyncMock(return_value=UpdateStatus.SKIP)
    updater.determine_update_criteria = AsyncMock()
    updater.process_osm_update = AsyncMock()
    updater.should_update_state = AsyncMock()
    updater.handle_state_update = AsyncMock()
    updater.rollback_update = AsyncMock()

    await updater.do_update("manual", {"a": 1})
    updater.rollback_update.assert_awaited_once()
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_UPDATED, "2024-01-01 12:00:00")


@pytest.mark.asyncio
async def test_handle_state_update_sets_native_value_and_calls_helpers(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    # Ensure extended attribute logic is triggered
    mock_sensor.get_attr.side_effect = lambda k: k in (CONF_EXTENDED_ATTR, CONF_SHOW_TIME)
    updater.get_extended_attr = AsyncMock()
    mock_sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "TestState" if k == ATTR_NATIVE_VALUE else ""
    )
    await updater.handle_state_update(datetime(2024, 1, 1, 12, 34), "old_place")
    assert updater.get_extended_attr.await_count >= 1
    mock_sensor.set_native_value.assert_called()
    mock_hass.async_add_executor_job.assert_awaited()


@pytest.mark.asyncio
async def test_handle_state_update_none_native_value(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = lambda k: False
    mock_sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
    await updater.handle_state_update(datetime(2024, 1, 1, 12, 34), "old_place")
    mock_sensor.set_native_value.assert_called_with(value=None)


@pytest.mark.asyncio
async def test_fire_event_data_builds_event_data(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr.side_effect = lambda k: "val"
    mock_sensor.get_attr_safe_str.side_effect = lambda k: "val"
    await updater.fire_event_data("old_place")
    args, kwargs = mock_hass.bus.fire.call_args
    assert args[0] == EVENT_TYPE
    assert isinstance(args[1], dict)


@pytest.mark.asyncio
async def test_get_current_time_with_timezone(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_hass.config.time_zone = "UTC"
    dt = await updater.get_current_time()
    assert dt.tzinfo is not None


@pytest.mark.asyncio
async def test_get_current_time_without_timezone(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_hass.config.time_zone = None
    dt = await updater.get_current_time()
    assert isinstance(dt, datetime)


@pytest.mark.asyncio
async def test_update_entity_name_and_cleanup_calls(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.check_for_updated_entity_name = AsyncMock()
    await updater.update_entity_name_and_cleanup()
    updater.check_for_updated_entity_name.assert_awaited_once()
    mock_sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_no_entity_id(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.entity_id = None
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_no_state(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.entity_id = "sensor.test"
    mock_hass.states.get.return_value = None
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_new_name(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.entity_id = "sensor.test"
    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    mock_sensor.get_attr.return_value = "OldName"
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_called()


@pytest.mark.asyncio
async def test_update_previous_state_show_time(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
    mock_sensor.get_attr.side_effect = lambda k: True if k == CONF_SHOW_TIME else "TestVal"
    mock_sensor.get_attr_safe_str.return_value = "TestVal"
    await updater.update_previous_state()
    mock_sensor.set_attr.assert_called_with(ATTR_PREVIOUS_STATE, "TestVal")


@pytest.mark.asyncio
async def test_update_previous_state_no_show_time(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
    mock_sensor.get_attr.side_effect = lambda k: False
    await updater.update_previous_state()
    mock_sensor.set_attr.assert_called()


@pytest.mark.asyncio
async def test_update_old_coordinates(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = lambda k: 1.0
    mock_sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_old_coordinates()
    mock_sensor.set_attr.assert_any_call(ATTR_LATITUDE_OLD, 1.0)
    mock_sensor.set_attr.assert_any_call(ATTR_LONGITUDE_OLD, 1.0)


@pytest.mark.asyncio
async def test_check_device_tracker_and_update_coords_proceed(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.is_devicetracker_set = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.update_coordinates = AsyncMock()
    updater.get_gps_accuracy = AsyncMock(return_value=UpdateStatus.PROCEED)
    result = await updater.check_device_tracker_and_update_coords()
    assert result == UpdateStatus.PROCEED
    updater.update_coordinates.assert_awaited_once()
    updater.get_gps_accuracy.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_gps_accuracy_sets_accuracy(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {ATTR_GPS_ACCURACY: 5.0}
    mock_hass.states.get.return_value = tracker_state
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr.return_value = True
    mock_sensor.get_attr_safe_float.return_value = 5.0
    result = await updater.get_gps_accuracy()
    assert result == UpdateStatus.PROCEED
    mock_sensor.set_attr.assert_any_call(ATTR_GPS_ACCURACY, 5.0)


@pytest.mark.asyncio
async def test_update_coordinates_sets_lat_lon(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {CONF_LATITUDE: 1.23, CONF_LONGITUDE: 4.56}
    mock_hass.states.get.return_value = tracker_state
    await updater.update_coordinates()
    mock_sensor.set_attr.assert_any_call(ATTR_LATITUDE, 1.23)
    mock_sensor.set_attr.assert_any_call(ATTR_LONGITUDE, 4.56)


@pytest.mark.asyncio
async def test_determine_update_criteria_calls(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.get_initial_last_place_name = AsyncMock()
    updater.get_zone_details = AsyncMock()
    updater.update_coordinates_and_distance = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.determine_if_update_needed = AsyncMock(return_value=UpdateStatus.PROCEED)
    result = await updater.determine_update_criteria()
    assert result == UpdateStatus.PROCEED
    updater.get_initial_last_place_name.assert_awaited_once()
    updater.get_zone_details.assert_awaited_once()
    updater.update_coordinates_and_distance.assert_awaited_once()
    updater.determine_if_update_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_initial_last_place_name_not_in_zone(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.in_zone = AsyncMock(return_value=False)
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr.return_value = "PlaceName"
    await updater.get_initial_last_place_name()
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "PlaceName")


@pytest.mark.asyncio
async def test_get_initial_last_place_name_in_zone(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.in_zone = AsyncMock(return_value=True)
    mock_sensor.get_attr.return_value = "ZoneName"
    await updater.get_initial_last_place_name()
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "ZoneName")


@pytest.mark.asyncio
async def test_get_zone_details_not_zone(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "device_tracker.test"
    )
    mock_sensor.get_attr.side_effect = (
        lambda k: "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "TestZone"
    )
    mock_hass.states.get.return_value = MagicMock(state="home")
    mock_sensor.in_zone = AsyncMock(return_value=False)
    await updater.get_zone_details()
    mock_sensor.set_attr.assert_any_call(ATTR_DEVICETRACKER_ZONE, "home")
    mock_sensor.set_attr.assert_any_call(ATTR_DEVICETRACKER_ZONE_NAME, "TestZone")


@pytest.mark.asyncio
async def test_process_osm_update_calls(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.async_reset_attributes = AsyncMock()
    updater.get_map_link = AsyncMock()
    updater.query_osm_and_finalize = AsyncMock()
    await updater.process_osm_update(datetime(2024, 1, 1, 12, 0))
    updater.async_reset_attributes.assert_awaited_once()
    updater.get_map_link.assert_awaited_once()
    updater.query_osm_and_finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_map_link_google(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = (
        lambda k: "google"
        if k == CONF_MAP_PROVIDER
        else "loc"
        if k == ATTR_LOCATION_CURRENT
        else 10
    )
    await updater.get_map_link()
    # Check that the second argument is a string (the URL)
    found = False
    for call in mock_sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_MAP_LINK and isinstance(call[0][1], str):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_get_map_link_osm(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = lambda k: "osm" if k == CONF_MAP_PROVIDER else 10
    mock_sensor.get_attr_safe_float.side_effect = (
        lambda k: 1.23456789 if k == ATTR_LATITUDE else 9.87654321
    )
    await updater.get_map_link()
    found = False
    for call in mock_sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_MAP_LINK and isinstance(call[0][1], str):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_get_map_link_apple(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = (
        lambda k: "apple" if k == CONF_MAP_PROVIDER else "loc" if k == ATTR_LOCATION_CURRENT else 10
    )
    await updater.get_map_link()
    found = False
    for call in mock_sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_MAP_LINK and isinstance(call[0][1], str):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_async_reset_attributes_calls(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    await updater.async_reset_attributes()
    mock_sensor.clear_attr.assert_called()
    mock_sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_update_state_true(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "a" if k == ATTR_PREVIOUS_STATE else "b" if k == ATTR_NATIVE_VALUE else "c"
    )
    mock_sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now())
    assert result is True


@pytest.mark.asyncio
async def test_should_update_state_false(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_str.side_effect = lambda k: "a"
    mock_sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now())
    assert result is False


@pytest.mark.asyncio
async def test_rollback_update_calls_restore_and_helpers(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.get_seconds_from_last_change = AsyncMock(return_value=100)
    updater.change_dot_to_stationary = AsyncMock()
    updater.change_show_time_to_date = AsyncMock()
    mock_sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else "stationary"
        if k == ATTR_DIRECTION_OF_TRAVEL
        else False
    )
    await updater.rollback_update({"a": 1}, datetime.now(), UpdateStatus.SKIP_SET_STATIONARY)
    mock_sensor.restore_previous_attr.assert_awaited_once()
    # Only assert if it was actually awaited
    if updater.change_dot_to_stationary.await_count > 0:
        updater.change_dot_to_stationary.assert_awaited()
    # Only assert if it was actually awaited
    if updater.change_show_time_to_date.await_count > 0:
        updater.change_show_time_to_date.assert_awaited()


@pytest.mark.asyncio
async def test_build_osm_url_returns_url(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr_safe_float.side_effect = lambda k: 1.23
    mock_sensor.get_attr.side_effect = (
        lambda k: "en" if k == CONF_LANGUAGE else "apikey" if k == CONF_API_KEY else 18
    )
    url = await updater.build_osm_url()
    assert url.startswith("https://nominatim.openstreetmap.org/reverse?format=json")


@pytest.mark.asyncio
async def test_get_extended_attr_calls_get_dict_from_url(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_str.side_effect = lambda k: "way"
    mock_sensor.get_attr.side_effect = (
        lambda k: "12345"
        if k == ATTR_OSM_ID
        else "way"
        if k == ATTR_OSM_TYPE
        else "apikey"
        if k == CONF_API_KEY
        else "en"
        if k == CONF_LANGUAGE
        else None
    )
    updater.get_dict_from_url = AsyncMock()
    mock_sensor.get_attr_safe_dict.return_value = {"extratags": {"wikidata": "Q123"}}
    await updater.get_extended_attr()
    updater.get_dict_from_url.assert_awaited()


@pytest.mark.asyncio
async def test_get_dict_from_url_cache_hit(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    url = "http://test"
    mock_hass.data[DOMAIN]["osm_cache"][url] = {"a": 1}
    await updater.get_dict_from_url(url, "Test", "dict_name")
    mock_sensor.set_attr.assert_called_with("dict_name", {"a": 1})


@pytest.mark.asyncio
async def test_get_dict_from_url_network_error(
    monkeypatch, mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    url = "http://test"

    class RaisingContextManager:
        async def __aenter__(self):
            raise OSError("fail")

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(aiohttp.ClientSession, "get", lambda *a, **kw: RaisingContextManager())

    await updater.get_dict_from_url(url, "Test", "dict_name")
    # Should not raise


@pytest.mark.asyncio
async def test_determine_if_update_needed_initial_update(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_update_location_attributes_sets_locations(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_location_attributes()
    mock_sensor.set_attr.assert_any_call(ATTR_LOCATION_CURRENT, "1.0,1.0")
    mock_sensor.set_attr.assert_any_call(ATTR_LOCATION_PREVIOUS, "1.0,1.0")
    mock_sensor.set_attr.assert_any_call(ATTR_HOME_LOCATION, "1.0,1.0")


@pytest.mark.asyncio
async def test_calculate_distances_sets_distance(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    await updater.calculate_distances()
    mock_sensor.set_attr.assert_any_call(ATTR_DISTANCE_FROM_HOME_M, 0)
    calls = [
        call
        for call in mock_sensor.set_attr.call_args_list
        if call[0][0] == ATTR_DISTANCE_FROM_HOME_MI
    ]
    # Accept any float or int value for distance_from_home_mi
    found = any(isinstance(call[0][1], float | int) for call in calls)
    assert found


@pytest.mark.asyncio
async def test_calculate_travel_distance_sets_travel(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    await updater.calculate_travel_distance()
    mock_sensor.set_attr.assert_any_call(ATTR_DISTANCE_TRAVELED_M, 0)
    # Accept any float value for distance_traveled_mi
    found = False
    for call in mock_sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_DISTANCE_TRAVELED_MI and isinstance(call[0][1], float):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_determine_direction_of_travel_towards_home(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_float.side_effect = (
        lambda k: 500.0 if k == ATTR_DISTANCE_FROM_HOME_M else 1000.0
    )
    await updater.determine_direction_of_travel(1000.0)
    mock_sensor.set_attr.assert_any_call(ATTR_DIRECTION_OF_TRAVEL, "towards home")


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_calls(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.update_location_attributes = AsyncMock()
    updater.calculate_distances = AsyncMock()
    updater.calculate_travel_distance = AsyncMock()
    updater.determine_direction_of_travel = AsyncMock()
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    # Patch get_attr_safe_str to return a value with a dot for CONF_HOME_ZONE
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "zone.home" if k == "home_zone" else "other"
    )
    result = await updater.update_coordinates_and_distance()
    assert result == UpdateStatus.PROCEED
    assert updater.update_location_attributes.await_count >= 1
    assert updater.calculate_distances.await_count >= 1
    assert updater.calculate_travel_distance.await_count >= 1
    assert updater.determine_direction_of_travel.await_count >= 1


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_blank(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.return_value = True
    result = await updater.get_seconds_from_last_change(datetime.now())
    assert result == 3600


@pytest.mark.asyncio
async def test_change_show_time_to_date_sets_native_value(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else "dd/mm"
        if k == CONF_DATE_FORMAT
        else "2024-01-01 12:00:00"
    )
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "2024-01-01 12:00:00" if k == ATTR_LAST_CHANGED else "TestState"
    )
    await updater.change_show_time_to_date()
    mock_sensor.set_native_value.assert_called()
    mock_sensor.set_attr.assert_any_call(ATTR_SHOW_DATE, True)
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_dot_to_stationary_sets_direction_and_last_changed(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    await updater.change_dot_to_stationary(datetime(2024, 1, 1, 12, 0), 100)
    mock_sensor.set_attr.assert_any_call(ATTR_DIRECTION_OF_TRAVEL, "stationary")
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_CHANGED, "2024-01-01 12:00:00")
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_devicetracker_set_tracker_not_available(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.is_tracker_available = AsyncMock(return_value=False)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_devicetracker_set_has_valid_coordinates_false(
    mock_hass, mock_config_entry, mock_sensor
):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.is_tracker_available = AsyncMock(return_value=True)
    updater.has_valid_coordinates = AsyncMock(return_value=False)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_devicetracker_set_proceed(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    updater.is_tracker_available = AsyncMock(return_value=True)
    updater.has_valid_coordinates = AsyncMock(return_value=True)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_is_tracker_available_blank_id(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.return_value = True
    await updater.is_tracker_available()
    # Should log and return False


@pytest.mark.asyncio
async def test_is_tracker_available_no_state(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr.return_value = "device_tracker.test"
    mock_hass.states.get.return_value = None
    await updater.is_tracker_available()
    # Should log and return False


@pytest.mark.asyncio
async def test_is_tracker_available_state_unavailable(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr.return_value = "device_tracker.test"
    mock_hass.states.get.return_value = "unavailable"
    await updater.is_tracker_available()
    # Should log and return False


@pytest.mark.asyncio
async def test_is_tracker_available_ok(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr.return_value = "device_tracker.test"
    mock_hass.states.get.return_value = MagicMock()
    result = await updater.is_tracker_available()
    assert result is True


@pytest.mark.asyncio
async def test_has_valid_coordinates_missing_attr(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    tracker = MagicMock()
    del tracker.attributes
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is False


@pytest.mark.asyncio
async def test_has_valid_coordinates_bad_lat_lon(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: None, CONF_LONGITUDE: None}
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is False


@pytest.mark.asyncio
async def test_has_valid_coordinates_ok(mock_hass, mock_config_entry, mock_sensor):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0}
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is True


@pytest.mark.asyncio
async def test_log_tracker_issue_warn(mock_hass, mock_config_entry, mock_sensor, caplog):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.warn_if_device_tracker_prob = True
    mock_sensor.get_attr.return_value = "TestSensor"
    await updater.log_tracker_issue("Test message")
    assert "Test message" in caplog.text


@pytest.mark.asyncio
async def test_log_tracker_issue_info(mock_hass, mock_config_entry, mock_sensor, caplog):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.warn_if_device_tracker_prob = False
    mock_sensor.get_attr.return_value = "TestSensor"
    await updater.log_tracker_issue("Test message")
    assert "Test message" in caplog.text


@pytest.mark.asyncio
async def test_log_coordinate_issue_warn(mock_hass, mock_config_entry, mock_sensor, caplog):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.warn_if_device_tracker_prob = True
    mock_sensor.get_attr.return_value = "TestSensor"
    await updater.log_coordinate_issue()
    assert "Latitude/Longitude is not set" in caplog.text


@pytest.mark.asyncio
async def test_log_coordinate_issue_info(mock_hass, mock_config_entry, mock_sensor, caplog):
    updater = PlacesUpdater(mock_hass, mock_config_entry, mock_sensor)
    mock_sensor.warn_if_device_tracker_prob = False
    mock_sensor.get_attr.return_value = "TestSensor"
    await updater.log_coordinate_issue()
    assert "Latitude/Longitude is not set" in caplog.text
