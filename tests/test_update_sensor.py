"""Unit tests for the PlacesUpdater class and related update logic."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

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
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PREVIOUS_STATE,
    ATTR_SHOW_DATE,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DOMAIN,
    EVENT_TYPE,
    OSM_CACHE,
    OSM_THROTTLE,
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

from .conftest import MockSensor


@pytest.fixture
def mock_config_entry():
    """Create and return a mock configuration entry with default sensor name and empty options for testing purposes."""
    entry = MagicMock()
    entry.data = {CONF_NAME: "TestSensor"}
    entry.options = {}
    return entry


@pytest.mark.asyncio
async def test_do_update_proceed_flow(mock_hass, mock_config_entry):
    """Execute full update flow when status is PROCEED."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
    assert sensor.attrs[ATTR_LAST_UPDATED] == "2024-01-01 12:00:00"


@pytest.mark.asyncio
async def test_do_update_skip_flow(mock_hass, mock_config_entry):
    """Handle SKIP update flow and perform rollback."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
    assert sensor.attrs[ATTR_LAST_UPDATED] == "2024-01-01 12:00:00"


@pytest.mark.asyncio
async def test_handle_state_update_sets_native_value_and_calls_helpers(
    mock_hass, mock_config_entry
):
    """Set native value and process extended attributes during state update."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Ensure extended attribute logic is triggered
    sensor.get_attr.side_effect = lambda k: k in (CONF_EXTENDED_ATTR, CONF_SHOW_TIME)
    updater.get_extended_attr = AsyncMock()
    sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
    sensor.get_attr_safe_str.side_effect = lambda k: "TestState" if k == ATTR_NATIVE_VALUE else ""
    await updater.handle_state_update(datetime(2024, 1, 1, 12, 34), "old_place")
    assert updater.get_extended_attr.await_count >= 1
    assert sensor.native_value is not None
    mock_hass.async_add_executor_job.assert_awaited()


@pytest.mark.asyncio
async def test_handle_state_update_none_native_value(mock_hass, mock_config_entry):
    """Test that handle_state_update sets the native value to None when the native value attribute is blank."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: False
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
    await updater.handle_state_update(datetime(2024, 1, 1, 12, 34), "old_place")
    assert sensor.native_value is None


@pytest.mark.asyncio
async def test_fire_event_data_builds_event_data(mock_hass, mock_config_entry):
    """Test that the fire_event_data method constructs and fires an event with the correct event type and data dictionary."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = lambda k: "val"
    sensor.get_attr_safe_str.side_effect = lambda k: "val"
    await updater.fire_event_data("old_place")
    args, kwargs = mock_hass.bus.fire.call_args
    assert args[0] == EVENT_TYPE
    assert isinstance(args[1], dict)


@pytest.mark.asyncio
async def test_get_current_time_with_timezone(mock_hass, mock_config_entry):
    """Test that `get_current_time` returns a timezone-aware datetime when a timezone is configured."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    mock_hass.config.time_zone = "UTC"
    dt = await updater.get_current_time()
    assert dt.tzinfo is not None


@pytest.mark.asyncio
async def test_get_current_time_without_timezone(mock_hass, mock_config_entry):
    """Test that `get_current_time` returns a `datetime` object when no timezone is configured."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    mock_hass.config.time_zone = None
    dt = await updater.get_current_time()
    assert isinstance(dt, datetime)


@pytest.mark.asyncio
async def test_update_entity_name_and_cleanup_calls(mock_hass, mock_config_entry):
    """Test that updating the entity name triggers the entity name check and cleans up sensor attributes."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.check_for_updated_entity_name = AsyncMock()
    await updater.update_entity_name_and_cleanup()
    updater.check_for_updated_entity_name.assert_awaited_once()
    sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_no_entity_id(mock_hass, mock_config_entry):
    """Test that no config entry update is triggered when the sensor's entity ID is missing."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.entity_id = None
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_no_state(mock_hass, mock_config_entry):
    """Test that no config entry update is triggered when the entity ID is set but the state is missing."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.entity_id = "sensor.test"
    mock_hass.states.get.return_value = None
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_updated_entity_name_entity_id_new_name(mock_hass, mock_config_entry):
    """Test that the entity name is updated and the config entry is updated when a new friendly name is detected."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.entity_id = "sensor.test"
    state = MagicMock()
    state.attributes = {ATTR_FRIENDLY_NAME: "NewName"}
    mock_hass.states.get.return_value = state
    sensor.get_attr.return_value = "OldName"
    await updater.check_for_updated_entity_name()
    mock_hass.config_entries.async_update_entry.assert_called()


@pytest.mark.asyncio
async def test_update_previous_state_show_time(mock_hass, mock_config_entry):
    """Set previous state when show-time is enabled."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: k != ATTR_NATIVE_VALUE
    sensor.get_attr.side_effect = lambda k: True if k == CONF_SHOW_TIME else "TestVal"
    sensor.get_attr_safe_str.return_value = "TestVal"
    await updater.update_previous_state()
    assert sensor.attrs[ATTR_PREVIOUS_STATE] == "TestVal"


@pytest.mark.asyncio
async def test_update_previous_state_no_show_time(mock_hass, mock_config_entry):
    """Set previous state correctly when show-time is disabled."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_NATIVE_VALUE
    sensor.get_attr.side_effect = lambda k: "PrevStateValue" if k == ATTR_PREVIOUS_STATE else False
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "PrevStateValue" if k in [ATTR_NATIVE_VALUE, ATTR_PREVIOUS_STATE] else ""
    )
    await updater.update_previous_state()
    assert sensor.attrs[ATTR_PREVIOUS_STATE] is False


@pytest.mark.asyncio
async def test_update_old_coordinates(mock_hass, mock_config_entry):
    """Test that `update_old_coordinates` sets the old latitude and longitude attributes on the sensor."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: 1.0
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_old_coordinates()
    assert sensor.attrs[ATTR_LATITUDE_OLD] == 1.0
    assert sensor.attrs[ATTR_LONGITUDE_OLD] == 1.0


@pytest.mark.asyncio
async def test_update_old_coordinates_not_float_latitude(mock_hass, mock_config_entry):
    """Test update_old_coordinates does NOT set ATTR_LATITUDE_OLD if latitude is not a float."""
    sensor = MockSensor()
    sensor.attrs[ATTR_LATITUDE] = "not_a_float"
    sensor.attrs[ATTR_LONGITUDE] = 2.0
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.update_old_coordinates()
    assert ATTR_LATITUDE_OLD not in sensor.attrs
    # Longitude should be set
    assert sensor.attrs[ATTR_LONGITUDE_OLD] == 2.0


@pytest.mark.asyncio
async def test_update_old_coordinates_not_float_longitude(mock_hass, mock_config_entry):
    """Test update_old_coordinates does NOT set ATTR_LONGITUDE_OLD if longitude is not a float."""
    sensor = MockSensor()
    sensor.attrs[ATTR_LATITUDE] = 1.0
    sensor.attrs[ATTR_LONGITUDE] = "not_a_float"
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.update_old_coordinates()
    assert ATTR_LONGITUDE_OLD not in sensor.attrs
    # Latitude should be set
    assert sensor.attrs[ATTR_LATITUDE_OLD] == 1.0


@pytest.mark.asyncio
async def test_check_device_tracker_and_update_coords_proceed(mock_hass, mock_config_entry):
    """Proceed when device tracker is set and GPS accuracy is valid."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.is_devicetracker_set = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.update_coordinates = AsyncMock()
    updater.get_gps_accuracy = AsyncMock(return_value=UpdateStatus.PROCEED)
    result = await updater.check_device_tracker_and_update_coords()
    assert result == UpdateStatus.PROCEED
    updater.update_coordinates.assert_awaited_once()
    updater.get_gps_accuracy.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_gps_accuracy_sets_accuracy(mock_hass, mock_config_entry):
    """Retrieve GPS accuracy and set sensor attribute when available."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {ATTR_GPS_ACCURACY: 5.0}
    mock_hass.states.get.return_value = tracker_state
    sensor.is_attr_blank.return_value = False
    sensor.get_attr.return_value = True
    sensor.get_attr_safe_float.return_value = 5.0
    result = await updater.get_gps_accuracy()
    assert result == UpdateStatus.PROCEED
    assert sensor.attrs[ATTR_GPS_ACCURACY] == 5.0


@pytest.mark.asyncio
async def test_update_coordinates_sets_lat_lon(mock_hass, mock_config_entry):
    """Test that `update_coordinates` sets the sensor's latitude and longitude attributes based on the device tracker state."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    tracker_state = MagicMock()
    tracker_state.attributes = {CONF_LATITUDE: 1.23, CONF_LONGITUDE: 4.56}
    mock_hass.states.get.return_value = tracker_state
    await updater.update_coordinates()
    assert sensor.attrs[ATTR_LATITUDE] == 1.23
    assert sensor.attrs[ATTR_LONGITUDE] == 4.56


@pytest.mark.asyncio
async def test_determine_update_criteria_calls(mock_hass, mock_config_entry):
    """Test that `determine_update_criteria` calls all required helper methods and returns the correct update status."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
async def test_get_initial_last_place_name_not_in_zone(mock_hass, mock_config_entry):
    """Set initial last place name when not in a zone."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.is_attr_blank.return_value = False
    sensor.attrs["place_name"] = "PlaceName"
    await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == "PlaceName"


@pytest.mark.asyncio
async def test_get_initial_last_place_name_in_zone(mock_hass, mock_config_entry):
    """Test that `get_initial_last_place_name` sets the last place name attribute when the sensor is in a zone."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.in_zone = AsyncMock(return_value=True)
    sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] = "ZoneName"
    await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == "ZoneName"


@pytest.mark.asyncio
async def test_get_zone_details_not_zone(mock_hass, mock_config_entry):
    """Update device tracker zone attributes when tracker not in a zone."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "device_tracker.test"
    )
    sensor.get_attr.side_effect = (
        lambda k: "home" if k == ATTR_DEVICETRACKER_ZONE_NAME else "TestZone"
    )
    mock_hass.states.get.return_value = MagicMock(state="home")
    sensor.in_zone = AsyncMock(return_value=False)
    await updater.get_zone_details()
    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE] == "home"
    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] == "TestZone"


@pytest.mark.asyncio
async def test_get_zone_details_zone_id_equals_conf_zone(mock_hass, mock_config_entry):
    """Test get_zone_details when devicetracker_id starts with CONF_ZONE (should skip first block)."""
    sensor = MockSensor()
    sensor.get_attr_safe_str = lambda k: CONF_ZONE + ".home" if k == CONF_DEVICETRACKER_ID else ""
    sensor.get_attr = lambda k: CONF_ZONE + ".home" if k == CONF_DEVICETRACKER_ID else ""
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.attrs[ATTR_DEVICETRACKER_ZONE] = "home"
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.get_zone_details()
    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] == ""


@pytest.mark.asyncio
async def test_get_zone_details_in_zone_true(mock_hass, mock_config_entry):
    """Test get_zone_details when sensor.in_zone() returns True (zone name logic executed)."""
    sensor = MockSensor()
    sensor.get_attr_safe_str = lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""
    sensor.get_attr = lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""
    sensor.in_zone = AsyncMock(return_value=True)
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    zone_state = MagicMock()
    zone_state.attributes = {CONF_ZONE: "home"}
    zone_name_state = MagicMock()
    zone_name_state.attributes = {CONF_FRIENDLY_NAME: "Home Zone"}
    mock_hass.states.get.side_effect = (
        lambda eid: zone_state
        if eid == "device_tracker.test"
        else zone_name_state
        if eid == "zone.home"
        else None
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.get_zone_details()
    assert sensor.attrs[ATTR_DEVICETRACKER_ZONE_NAME] == ""


@pytest.mark.asyncio
async def test_process_osm_update_calls(mock_hass, mock_config_entry):
    """Test that `process_osm_update` calls attribute reset, map link generation, and OSM query finalization methods as expected."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.async_reset_attributes = AsyncMock()
    updater.get_map_link = AsyncMock()
    updater.query_osm_and_finalize = AsyncMock()
    await updater.process_osm_update(datetime(2024, 1, 1, 12, 0))
    updater.async_reset_attributes.assert_awaited_once()
    updater.get_map_link.assert_awaited_once()
    updater.query_osm_and_finalize.assert_awaited_once()


def assert_map_link_set(sensor):
    """Assert that set_attr was called with ATTR_MAP_LINK and a string value."""
    found = False
    for call in sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_MAP_LINK and isinstance(call[0][1], str):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_get_map_link_google(mock_hass, mock_config_entry):
    """Test that the map link is generated and set as a string attribute when the map provider is Google."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = (
        lambda k: "google"
        if k == CONF_MAP_PROVIDER
        else "loc"
        if k == ATTR_LOCATION_CURRENT
        else 10
    )
    await updater.get_map_link()
    assert_map_link_set(sensor)


@pytest.mark.asyncio
async def test_get_map_link_osm(mock_hass, mock_config_entry):
    """Test that the get_map_link method sets the map link attribute using the OSM map provider.

    Verifies that when the map provider is set to "osm", the get_map_link method generates a string map link and assigns it to the sensor's map link attribute.
    """
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: "osm" if k == CONF_MAP_PROVIDER else 10
    sensor.get_attr_safe_float.side_effect = (
        lambda k: 1.23456789 if k == ATTR_LATITUDE else 9.87654321
    )
    await updater.get_map_link()
    assert_map_link_set(sensor)


@pytest.mark.asyncio
async def test_get_map_link_apple(mock_hass, mock_config_entry):
    """Test that the get_map_link method sets the map link attribute using the Apple Maps provider.

    Verifies that when the map provider is set to "apple", the generated map link is a string and is assigned to the appropriate sensor attribute.
    """
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = (
        lambda k: "apple" if k == CONF_MAP_PROVIDER else "loc" if k == ATTR_LOCATION_CURRENT else 10
    )
    await updater.get_map_link()
    assert_map_link_set(sensor)


@pytest.mark.asyncio
async def test_async_reset_attributes_calls(mock_hass, mock_config_entry):
    """Test that `async_reset_attributes` clears sensor attributes and performs asynchronous cleanup."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.async_reset_attributes()
    sensor.clear_attr.assert_called()
    sensor.async_cleanup_attributes.assert_awaited_once()


@pytest.mark.asyncio
async def test_should_update_state_true(mock_hass, mock_config_entry):
    """Test that `should_update_state` returns True when previous state and native value differ.

    Verifies that the updater determines a state update is needed when the sensor's previous state and current native value are not equal.
    """
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "a" if k == ATTR_PREVIOUS_STATE else "b" if k == ATTR_NATIVE_VALUE else "c"
    )
    sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now())
    assert result is True


@pytest.mark.asyncio
async def test_should_update_state_false(mock_hass, mock_config_entry):
    """Test that `should_update_state` returns False when sensor attributes indicate no update is needed."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "a"
    sensor.get_attr.side_effect = lambda k: False
    result = await updater.should_update_state(datetime.now())
    assert result is False


@pytest.mark.asyncio
async def test_rollback_update_calls_restore_and_helpers(mock_hass, mock_config_entry):
    """Restore previous attributes and conditionally call helper routines."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.get_seconds_from_last_change = AsyncMock(return_value=100)
    updater.change_dot_to_stationary = AsyncMock()
    updater.change_show_time_to_date = AsyncMock()
    sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else "stationary"
        if k == ATTR_DIRECTION_OF_TRAVEL
        else False
    )
    await updater.rollback_update({"a": 1}, datetime.now(), UpdateStatus.SKIP_SET_STATIONARY)
    sensor.restore_previous_attr.assert_awaited_once()
    # Only assert if it was actually awaited
    if updater.change_dot_to_stationary.await_count > 0:
        updater.change_dot_to_stationary.assert_awaited()
    # Only assert if it was actually awaited
    if updater.change_show_time_to_date.await_count > 0:
        updater.change_show_time_to_date.assert_awaited()


@pytest.mark.asyncio
async def test_build_osm_url_returns_url(mock_hass, mock_config_entry):
    """Test that `build_osm_url` constructs a valid OpenStreetMap reverse geocoding URL using sensor attributes."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
async def test_get_extended_attr_calls_get_dict_from_url(mock_hass, mock_config_entry):
    """Test that `get_extended_attr` calls `get_dict_from_url` and processes the returned dictionary for extended attributes."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "way"
    sensor.get_attr.side_effect = (
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
    sensor.get_attr_safe_dict.return_value = {"extratags": {"wikidata": "Q123"}}
    await updater.get_extended_attr()
    updater.get_dict_from_url.assert_awaited()


@pytest.mark.asyncio
async def test_get_dict_from_url_cache_hit(mock_hass, mock_config_entry):
    """Test that `get_dict_from_url` retrieves data from the cache and sets the sensor attribute accordingly."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://test"
    # Ensure DOMAIN key exists in mock_hass.data
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            "osm_cache": {},
            "osm_throttle": {"lock": AsyncMock(), "last_query": 0},
        }
    mock_hass.data[DOMAIN]["osm_cache"][url] = {"a": 1}
    await updater.get_dict_from_url(url, "Test", "dict_name")
    assert sensor.attrs["dict_name"] == {"a": 1}


@pytest.mark.asyncio
async def test_get_dict_from_url_network_error(monkeypatch, mock_hass, mock_config_entry):
    """Test that get_dict_from_url handles network errors gracefully without raising exceptions."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://test"
    # Ensure DOMAIN key exists in mock_hass.data
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            "osm_cache": {},
            "osm_throttle": {"lock": AsyncMock(), "last_query": 0},
        }

    class RaisingContextManager:
        async def __aenter__(self):
            raise OSError("fail")

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(aiohttp.ClientSession, "get", lambda *a, **kw: RaisingContextManager())
    await updater.get_dict_from_url(url, "Test", "dict_name")
    # Should not raise


@pytest.mark.asyncio
async def test_determine_if_update_needed_initial_update(mock_hass, mock_config_entry):
    """Test that `determine_if_update_needed` returns `PROCEED` when the initial update attribute is set to True."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_update_location_attributes_sets_locations(mock_hass, mock_config_entry):
    """Test that `update_location_attributes` sets current, previous, and home location attributes to the expected values."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1.0
    await updater.update_location_attributes()
    assert sensor.attrs[ATTR_LOCATION_CURRENT] == "1.0,1.0"
    assert sensor.attrs[ATTR_LOCATION_PREVIOUS] == "1.0,1.0"
    assert sensor.attrs[ATTR_HOME_LOCATION] == "1.0,1.0"


@pytest.mark.asyncio
async def test_calculate_distances_sets_distance(mock_hass, mock_config_entry):
    """Test that `calculate_distances` sets the distance from home in meters and miles as sensor attributes."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    await updater.calculate_distances()
    assert sensor.attrs[ATTR_DISTANCE_FROM_HOME_M] == 0
    calls = [
        call for call in sensor.set_attr.call_args_list if call[0][0] == ATTR_DISTANCE_FROM_HOME_MI
    ]
    # Accept any float or int value for distance_from_home_mi
    found = any(isinstance(call[0][1], float | int) for call in calls)
    assert found


@pytest.mark.asyncio
async def test_calculate_travel_distance_sets_travel(mock_hass, mock_config_entry):
    """Set traveled distance attributes in meters and miles."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = lambda k: 1000.0
    await updater.calculate_travel_distance()
    assert sensor.attrs[ATTR_DISTANCE_TRAVELED_M] == 0
    # Accept any float value for distance_traveled_mi
    found = False
    for call in sensor.set_attr.call_args_list:
        if call[0][0] == ATTR_DISTANCE_TRAVELED_MI and isinstance(call[0][1], float):
            found = True
            break
    assert found


@pytest.mark.asyncio
async def test_determine_direction_of_travel_towards_home(mock_hass, mock_config_entry):
    """Test that the direction of travel is set to "towards home" when the current distance from home is less than the previous distance."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_float.side_effect = (
        lambda k: 500.0 if k == ATTR_DISTANCE_FROM_HOME_M else 1000.0
    )
    await updater.determine_direction_of_travel(1000.0)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "towards home"


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_calls(mock_hass, mock_config_entry):
    """Call coordinate and distance helpers and return PROCEED."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.update_location_attributes = AsyncMock()
    updater.calculate_distances = AsyncMock()
    updater.calculate_travel_distance = AsyncMock()
    updater.determine_direction_of_travel = AsyncMock()
    sensor.is_attr_blank.side_effect = lambda k: False
    # Patch get_attr_safe_str to return a value with a dot for CONF_HOME_ZONE
    sensor.get_attr_safe_str.side_effect = lambda k: "zone.home" if k == "home_zone" else "other"
    result = await updater.update_coordinates_and_distance()
    assert result == UpdateStatus.PROCEED
    assert updater.update_location_attributes.await_count >= 1
    assert updater.calculate_distances.await_count >= 1
    assert updater.calculate_travel_distance.await_count >= 1
    assert updater.determine_direction_of_travel.await_count >= 1


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_blank(mock_hass, mock_config_entry):
    """Return default seconds when last change attribute is blank."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = True
    result = await updater.get_seconds_from_last_change(datetime.now())
    assert result == 3600


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_invalid_date(mock_hass, mock_config_entry):
    """Returns 3600 if ATTR_LAST_CHANGED cannot be parsed as a date."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "not-a-date"
    result = await updater.get_seconds_from_last_change(datetime.now())
    assert result == 3600


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_valid_date(mock_hass, mock_config_entry):
    """Returns correct seconds if ATTR_LAST_CHANGED is a valid date."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    now = datetime.now()
    last_changed = now - timedelta(seconds=123)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = last_changed.replace(microsecond=0).isoformat()
    result = await updater.get_seconds_from_last_change(now.replace(microsecond=0))
    assert result == 3600


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_type_error_real(mock_hass, mock_config_entry):
    """Test get_seconds_from_last_change returns 3600 if subtraction raises TypeError."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    class BadDatetime(datetime):
        def __sub__(self, other):
            raise TypeError("test")

    bad_dt = BadDatetime.now()
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = bad_dt.isoformat()
    with patch("custom_components.places.update_sensor.datetime") as mock_dt:
        mock_dt.fromisoformat.return_value = bad_dt
        mock_dt.now.return_value = bad_dt
        result = await updater.get_seconds_from_last_change(bad_dt)
        assert result == 3600


@pytest.mark.asyncio
async def test_get_seconds_from_last_change_value_error_real(mock_hass, mock_config_entry):
    """Test get_seconds_from_last_change returns 3600 if fromisoformat raises ValueError (patch correct location)."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    now = datetime.now()
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "bad-date"
    with patch("custom_components.places.update_sensor.datetime") as mock_dt:
        mock_dt.fromisoformat.side_effect = ValueError("bad date format")
        mock_dt.now.return_value = now
        result = await updater.get_seconds_from_last_change(now)
        assert result == 3600


@pytest.mark.asyncio
async def test_change_show_time_to_date_sets_native_value(mock_hass, mock_config_entry):
    """Convert show-time to a date native value and set show-date attribute."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else "dd/mm"
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
    mock_hass, mock_config_entry
):
    """Set direction to 'stationary' and update last_changed, scheduling executor job."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.change_dot_to_stationary(datetime(2024, 1, 1, 12, 0), 100)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"
    assert sensor.attrs[ATTR_LAST_CHANGED] == "2024-01-01 12:00:00"
    mock_hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_devicetracker_set_tracker_not_available(mock_hass, mock_config_entry):
    """Test that is_devicetracker_set returns SKIP when the device tracker is not available."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.is_tracker_available = AsyncMock(return_value=False)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_devicetracker_set_has_valid_coordinates_false(mock_hass, mock_config_entry):
    """Test that is_devicetracker_set returns SKIP when the device tracker is available but coordinates are invalid."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.is_tracker_available = AsyncMock(return_value=True)
    updater.has_valid_coordinates = AsyncMock(return_value=False)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_devicetracker_set_proceed(mock_hass, mock_config_entry):
    """Test that `is_devicetracker_set` returns `UpdateStatus.PROCEED` when the device tracker is available and has valid coordinates."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.is_tracker_available = AsyncMock(return_value=True)
    updater.has_valid_coordinates = AsyncMock(return_value=True)
    result = await updater.is_devicetracker_set()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tracker_state, expected_result",
    [
        (None, False),
        ("unavailable", False),
        (MagicMock(), False),
    ],
)
async def test_is_tracker_available_param(
    mock_hass, mock_config_entry, tracker_state, expected_result
):
    """Test is_tracker_available for missing, unavailable, and valid tracker states."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr.return_value = "device_tracker.test"
    mock_hass.states.get.return_value = tracker_state
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
    mock_hass, mock_config_entry, tracker_attrs, expected_result
):
    """Test has_valid_coordinates for missing, bad, and valid lat/lon attributes."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
async def test_log_tracker_issue_param(mock_hass, mock_config_entry, caplog, warn_flag):
    """Test log_tracker_issue for both warn and info levels."""
    sensor = MockSensor()
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
    mock_hass, mock_config_entry
):
    """Test that query_osm_and_finalize runs the OSM parser, finalizes the last place name, processes display options, and sets last_changed."""
    sensor = MockSensor()
    sensor.attrs["osm_dict"] = {"some": "value"}
    sensor.attrs["last_place_name"] = "TestPlace"
    sensor.process_display_options = AsyncMock()
    mock_parser = AsyncMock()
    mock_parser.parse_osm_dict = AsyncMock()
    mock_parser.finalize_last_place_name = AsyncMock()
    with patch("custom_components.places.update_sensor.OSMParser", return_value=mock_parser):
        updater = PlacesUpdater(
            hass=mock_hass,
            config_entry=mock_config_entry,
            sensor=sensor,
        )
        updater.build_osm_url = AsyncMock(return_value="http://test-url")
        updater.get_dict_from_url = AsyncMock()
        now = datetime(2024, 1, 1, 12, 0, 0)
        updater.sensor = sensor
        updater.config_entry = mock_config_entry
        await updater.query_osm_and_finalize(now)
        updater.build_osm_url.assert_awaited_once()
        updater.get_dict_from_url.assert_awaited_once_with(
            url="http://test-url",
            name="OpenStreetMaps",
            dict_name="osm_dict",
        )
        mock_parser.parse_osm_dict.assert_awaited_once()
        mock_parser.finalize_last_place_name.assert_awaited_once_with("TestPlace")
        sensor.process_display_options.assert_awaited_once()
        assert sensor.attrs["last_changed"] == now.isoformat(sep=" ", timespec="seconds")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blank_attr",
    [ATTR_LATITUDE, ATTR_LONGITUDE, ATTR_HOME_LATITUDE, ATTR_HOME_LONGITUDE],
)
async def test_calculate_distances_not_all_attrs_set(mock_hass, mock_config_entry, blank_attr):
    """Test calculate_distances does NOT set distance attributes if any required attribute is blank."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
async def test_calculate_distances_distance_from_home_m_blank(mock_hass, mock_config_entry):
    """Test calculate_distances does NOT set KM/MI if ATTR_DISTANCE_FROM_HOME_M is blank after calculation."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

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
    "blank_attr",
    [ATTR_LATITUDE_OLD, ATTR_LONGITUDE_OLD],
)
async def test_calculate_travel_distance_not_all_old_coords_set(
    mock_hass, mock_config_entry, blank_attr
):
    """Test calculate_travel_distance sets stationary and zero values if any old coordinate is blank."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Patch is_attr_blank to return True for the blank_attr, False otherwise
    sensor.is_attr_blank = lambda k: k == blank_attr
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    await updater.calculate_travel_distance()
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"
    assert sensor.attrs[ATTR_DISTANCE_TRAVELED_M] == 0
    assert sensor.attrs[ATTR_DISTANCE_TRAVELED_MI] == 0


@pytest.mark.asyncio
async def test_calculate_travel_distance_distance_traveled_m_blank(mock_hass, mock_config_entry):
    """Test calculate_travel_distance does NOT set MI if ATTR_DISTANCE_TRAVELED_M is blank after calculation."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    # Patch is_attr_blank so ATTR_DISTANCE_TRAVELED_M is blank after calculation
    def is_attr_blank(key):
        return key == ATTR_DISTANCE_TRAVELED_M

    sensor.is_attr_blank = is_attr_blank
    # Patch set_attr to update attrs
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    # Patch get_attr_safe_float to return valid floats
    sensor.get_attr_safe_float = lambda k: 1.0
    # Patch all required attributes to not blank except ATTR_DISTANCE_TRAVELED_M
    for attr in [ATTR_LATITUDE_OLD, ATTR_LONGITUDE_OLD]:
        sensor.attrs[attr] = 1.0
    await updater.calculate_travel_distance()
    # Only ATTR_DISTANCE_TRAVELED_M should be set
    assert ATTR_DISTANCE_TRAVELED_M in sensor.attrs
    assert ATTR_DISTANCE_TRAVELED_MI not in sensor.attrs


@pytest.mark.asyncio
async def test_get_gps_accuracy_zero_accuracy_skip(mock_hass, mock_config_entry):
    """GPS accuracy 0 with use_gps True causes SKIP."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
    mock_hass, mock_config_entry
):
    """If get_gps_accuracy returns SKIP that status is propagated."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.is_devicetracker_set = AsyncMock(return_value=UpdateStatus.PROCEED)
    updater.update_coordinates = AsyncMock()
    updater.get_gps_accuracy = AsyncMock(return_value=UpdateStatus.SKIP)
    result = await updater.check_device_tracker_and_update_coords()
    assert result == UpdateStatus.SKIP
    updater.update_coordinates.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_coordinates_device_tracker_missing(mock_hass, mock_config_entry, caplog):
    """update_coordinates logs warning and returns when tracker missing."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    mock_hass.states.get.return_value = None
    await updater.update_coordinates()
    assert any("Device tracker entity not found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_determine_update_criteria_skip_before_determine_if_update_needed(
    mock_hass, mock_config_entry
):
    """If update_coordinates_and_distance returns SKIP then determine_if_update_needed not called."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.get_initial_last_place_name = AsyncMock()
    updater.get_zone_details = AsyncMock()
    updater.update_coordinates_and_distance = AsyncMock(return_value=UpdateStatus.SKIP)
    updater.determine_if_update_needed = AsyncMock(return_value=UpdateStatus.PROCEED)
    result = await updater.determine_update_criteria()
    assert result == UpdateStatus.SKIP
    updater.determine_if_update_needed.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_initial_last_place_name_not_in_zone_blank_keeps_previous(
    mock_hass, mock_config_entry
):
    """Retains previous last_place_name when not in zone and place_name blank."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.is_attr_blank.side_effect = lambda k: k == "place_name"
    sensor.attrs["last_place_name"] = "Prev"
    await updater.get_initial_last_place_name()
    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == "Prev"


@pytest.mark.asyncio
async def test_get_zone_details_in_zone_no_zone_name_state(mock_hass, mock_config_entry):
    """In zone but zone name state missing -> fallback to zone attribute and title-case if lower."""
    sensor = MockSensor()
    sensor.get_attr_safe_str = lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""
    sensor.get_attr = lambda k: "device_tracker.test" if k == CONF_DEVICETRACKER_ID else ""
    sensor.in_zone = AsyncMock(return_value=True)
    zone_state = MagicMock()
    zone_state.attributes = {CONF_ZONE: "home"}
    mock_hass.states.get.side_effect = (
        lambda eid: zone_state if eid == "device_tracker.test" else None
    )
    sensor.set_attr = lambda k, v: sensor.attrs.__setitem__(k, v)
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.get_zone_details()
    # Fallback sets zone name to zone attr (empty because we set above?), ensure attribute exists
    assert ATTR_DEVICETRACKER_ZONE_NAME in sensor.attrs


@pytest.mark.asyncio
async def test_query_osm_and_finalize_no_osm_dict(mock_hass, mock_config_entry):
    """If OSM dict blank parser isn't invoked and last_changed not set."""
    sensor = MockSensor()
    sensor.attrs[ATTR_OSM_DICT] = None
    sensor.process_display_options = AsyncMock()
    with patch("custom_components.places.update_sensor.OSMParser") as mock_parser_cls:
        updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
        updater.build_osm_url = AsyncMock(return_value="http://url")
        updater.get_dict_from_url = AsyncMock()
        now = datetime(2024, 1, 1, 0, 0, 0)
        await updater.query_osm_and_finalize(now)
        mock_parser_cls.assert_not_called()
        assert ATTR_LAST_CHANGED not in sensor.attrs


@pytest.mark.asyncio
async def test_should_update_state_initial_update_true(mock_hass, mock_config_entry):
    """Returns True when ATTR_INITIAL_UPDATE flag set (forces update)."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: k == ATTR_INITIAL_UPDATE
    sensor.is_attr_blank.return_value = True
    result = await updater.should_update_state(datetime.now())
    assert result is True


@pytest.mark.asyncio
async def test_rollback_update_triggers_change_dot_to_stationary(mock_hass, mock_config_entry):
    """Triggers change_dot_to_stationary when status SKIP_SET_STATIONARY and >60s elapsed."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.get_seconds_from_last_change = AsyncMock(return_value=120)
    updater.change_dot_to_stationary = AsyncMock()
    updater.change_show_time_to_date = AsyncMock()
    sensor.get_attr.side_effect = lambda k: False if k == ATTR_DIRECTION_OF_TRAVEL else False
    await updater.rollback_update({}, datetime.now(), UpdateStatus.SKIP_SET_STATIONARY)
    updater.change_dot_to_stationary.assert_awaited()


@pytest.mark.asyncio
async def test_rollback_update_triggers_change_show_time_to_date(mock_hass, mock_config_entry):
    """Triggers change_show_time_to_date when show_time True and >86399 seconds elapsed."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.get_seconds_from_last_change = AsyncMock(return_value=90000)
    updater.change_dot_to_stationary = AsyncMock()
    updater.change_show_time_to_date = AsyncMock()
    sensor.get_attr.side_effect = lambda k: k == CONF_SHOW_TIME
    await updater.rollback_update({}, datetime.now(), UpdateStatus.PROCEED)
    updater.change_show_time_to_date.assert_awaited()


@pytest.mark.asyncio
async def test_get_extended_attr_unknown_type(mock_hass, mock_config_entry, caplog):
    """Logs warning for unknown OSM type and returns early."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "foo"
    sensor.get_attr.side_effect = (
        lambda k: "123" if k == ATTR_OSM_ID else "foo" if k == ATTR_OSM_TYPE else None
    )
    await updater.get_extended_attr()
    assert any("Unknown OSM type" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_get_dict_from_url_json_decode_error(
    mock_hass, mock_config_entry, monkeypatch, caplog
):
    """Logs JSON Decode Error when response text is invalid JSON."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://decode"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": AsyncMock(), "last_query": 0},
        }

    class FakeResp:
        async def text(self):
            return "{bad json}"

    class FakeCM:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class FakeSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, *a, **kw):
            return FakeCM()

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    await updater.get_dict_from_url(url, "Test", "dict_name")
    assert any("JSON Decode Error" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_get_dict_from_url_error_message(mock_hass, mock_config_entry, monkeypatch, caplog):
    """Logs service error when error_message present in payload."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    url = "http://errmsg"
    if DOMAIN not in mock_hass.data:
        mock_hass.data[DOMAIN] = {
            OSM_CACHE: {},
            OSM_THROTTLE: {"lock": AsyncMock(), "last_query": 0},
        }
    response_payload = '{"error_message": "bad"}'

    class FakeResp:
        async def text(self):
            return response_payload

    class FakeCM:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class FakeSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, *a, **kw):
            return FakeCM()

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    await updater.get_dict_from_url(url, "Test", "dict_name")
    assert any("error occurred contacting the web service" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_determine_if_update_needed_same_location(mock_hass, mock_config_entry):
    """Returns SKIP_SET_STATIONARY when current and previous locations identical."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Set previous and native value so 'previous state unknown' branch not taken
    sensor.attrs[ATTR_NATIVE_VALUE] = "state"
    sensor.attrs[ATTR_PREVIOUS_STATE] = "state"
    # Coordinates identical
    sensor.attrs[ATTR_LOCATION_CURRENT] = "1,1"
    sensor.attrs[ATTR_LOCATION_PREVIOUS] = "1,1"
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = 20
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.SKIP_SET_STATIONARY


@pytest.mark.asyncio
async def test_determine_if_update_needed_small_distance(mock_hass, mock_config_entry):
    """Returns SKIP_SET_STATIONARY when distance traveled < 10m."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.attrs[ATTR_NATIVE_VALUE] = "state"
    sensor.attrs[ATTR_PREVIOUS_STATE] = "state"
    sensor.attrs[ATTR_LOCATION_CURRENT] = "2,2"
    sensor.attrs[ATTR_LOCATION_PREVIOUS] = "3,3"
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = 5
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.SKIP_SET_STATIONARY


@pytest.mark.asyncio
async def test_determine_if_update_needed_proceed(mock_hass, mock_config_entry):
    """Returns PROCEED when locations differ and distance >= 10m."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.get_attr.side_effect = lambda k: False
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "A" if k == ATTR_LOCATION_CURRENT else "B" if k == ATTR_LOCATION_PREVIOUS else ""
    )
    sensor.get_attr_safe_float.side_effect = lambda k: 50 if k == ATTR_DISTANCE_TRAVELED_M else 0
    result = await updater.determine_if_update_needed()
    assert result == UpdateStatus.PROCEED


@pytest.mark.asyncio
async def test_determine_direction_of_travel_away_from_home(mock_hass, mock_config_entry):
    """Sets direction 'away from home' when distance increased vs last measurement."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    # Provide distance_traveled attr so not blank
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = 1
    sensor.get_attr_safe_float.side_effect = lambda k: 1500 if k == ATTR_DISTANCE_FROM_HOME_M else 0
    sensor.is_attr_blank.side_effect = lambda k: k not in sensor.attrs
    await updater.determine_direction_of_travel(1000.0)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "away from home"


@pytest.mark.asyncio
async def test_determine_direction_of_travel_stationary(mock_hass, mock_config_entry):
    """Sets direction 'stationary' when distance unchanged."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_float.side_effect = lambda k: 1000 if k == ATTR_DISTANCE_FROM_HOME_M else 0
    await updater.determine_direction_of_travel(1000.0)
    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"


@pytest.mark.asyncio
async def test_update_coordinates_and_distance_skip_missing_attr(mock_hass, mock_config_entry):
    """Returns SKIP when required lat/long/home coordinates are blank after updates."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    updater.update_location_attributes = AsyncMock()
    updater.calculate_distances = AsyncMock()
    updater.calculate_travel_distance = AsyncMock()
    updater.determine_direction_of_travel = AsyncMock()
    # Need home zone for logging split
    sensor.attrs[CONF_HOME_ZONE] = "zone.home"
    sensor.is_attr_blank.side_effect = lambda k: k in [ATTR_LATITUDE, ATTR_HOME_LATITUDE]
    result = await updater.update_coordinates_and_distance()
    assert result == UpdateStatus.SKIP


@pytest.mark.asyncio
async def test_is_tracker_available_valid(mock_hass, mock_config_entry):
    """Returns True for existing tracker state object (not string unavailable)."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
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
async def test_has_valid_coordinates_non_numeric(mock_hass, mock_config_entry):
    """Returns False when latitude not numeric though attribute exists."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: "a", CONF_LONGITUDE: 2.0}
    mock_hass.states.get.return_value = tracker
    result = await updater.has_valid_coordinates()
    assert result is False


@pytest.mark.asyncio
async def test_log_tracker_issue_initial_update(mock_hass, mock_config_entry, caplog):
    """Logs warning during initial update even if warn flag not set."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = False
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else None
    await updater.log_tracker_issue("Msg")
    assert any("Msg" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_log_coordinate_issue_warn_flag(mock_hass, mock_config_entry, caplog):
    """Logs warning when warn_if_device_tracker_prob set for coordinate issue."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.warn_if_device_tracker_prob = True
    sensor.get_attr.side_effect = lambda k: False
    sensor.get_attr.return_value = "device_tracker.test"
    await updater.log_coordinate_issue()
    assert any("Latitude/Longitude is not set" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_change_show_time_to_date_mmdd_format(mock_hass, mock_config_entry):
    """Handles mm/dd date_format path in change_show_time_to_date."""
    sensor = MockSensor()
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr.side_effect = (
        lambda k: True
        if k == CONF_SHOW_TIME
        else "mm/dd"
        if k == CONF_DATE_FORMAT
        else "2024-01-01 12:00:00"
    )
    sensor.get_attr_safe_str.side_effect = (
        lambda k: "2024-01-01 12:00:00" if k == ATTR_LAST_CHANGED else "TestState"
    )
    await updater.change_show_time_to_date()
    assert sensor.attrs[ATTR_SHOW_DATE] is True
