"""Integration tests for display options rendering in the Places sensor."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_NAME,
)
from custom_components.places.sensor import Places

# Snapshot of internal attributes after parse_osm_dict
BASE_INTERNAL_ATTR = {
    "initial_update": False,
    "name": "Test Place",
    "unique_id": "5a00ead04bce9bbd7ab4a40c8ed70e3c",
    "icon": "mdi:map-search-outline",
    "api_key": "abcdefg@test.com",
    "options": "formatted_place",
    "devicetracker_id": "device_tracker.test_iphone",
    "devicetracker_entityid": "device_tracker.test_iphone",
    "home_zone": "zone.home",
    "map_provider": "apple",
    "map_zoom": 18,
    "extended_attr": False,
    "show_time": False,
    "date_format": "mm/dd",
    "use_gps_accuracy": True,
    "json_filename": "places-5a00ead04bce9bbd7ab4a40c8ed70e3c.json",
    "json_folder": "/config/custom_components/places/json_sensors",
    "display_options": "formatted_place",
    "home_latitude": 40.824763,
    "home_longitude": -73.973675,
    "show_date": False,
    "devicetracker_zone_name": "not_home",
    "devicetracker_zone": "not_home",
    "direction_of_travel": "towards home",
    "distance_from_home_km": 23.899,
    "distance_from_home_m": 23898.658,
    "distance_from_home_mi": 14.85,
    "distance_traveled_m": 2378.348,
    "distance_traveled_mi": 1.478,
    "gps_accuracy": 4.0,
    "last_changed": "2025-07-30 16:52:35-04:00",
    "last_place_name": "Riverside Drive",
    "last_updated": "2025-07-30 16:52:35-04:00",
    "previous_latitude": 40.83871498707779,
    "current_latitude": 40.854733600095464,
    "previous_longitude": -73.94654779701861,
    "current_longitude": -73.96526768799811,
    "native_value": "Secondary, Riverside Drive, New York, NY",  # Pre-existing state before re-render
    "attribution": "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
    "display_options_list": ["formatted_place"],
    "previous_state": "Secondary, Riverside Drive, New York, NY",
    "current_location": "40.854733600095464,-73.96526768799811",
    "previous_location": "40.83871498707779,-73.94654779701861",
    "home_location": "40.824763, -73.973675",
    "map_link": "https://maps.apple.com/?q=40.854733600095464%2C-73.96526768799811&z=18",
    "osm_dict": {
        "place_id": 333305883,
        "licence": "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
        "osm_type": "node",
        "osm_id": 2563205146,
        "lat": "40.8553978",
        "lon": "-73.9647140",
        "class": "place",
        "type": "house",
        "place_rank": 30,
        "importance": 5.726176852059232e-05,
        "addresstype": "place",
        "name": "Roy Spiegel MSW",
        "display_name": "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, New Jersey, 07024, United States",
        "address": {
            "place": "Roy Spiegel MSW",
            "house_number": "1",
            "road": "Bridge Plaza North",
            "neighbourhood": "Koreatown",
            "town": "Fort Lee",
            "county": "Bergen County",
            "state": "New Jersey",
            "ISO3166-2-lvl4": "US-NJ",
            "postcode": "07024",
            "country": "United States",
            "country_code": "us",
        },
        "namedetails": {
            "name": "Roy Spiegel MSW",
            "name:en": "Roy Spiegel MSW",
            "addr:housename": "Roy Spiegel MSW",
        },
        "boundingbox": ["40.8553478", "40.8554478", "-73.9647640", "-73.9646640"],
    },
    "place_type": "house",
    "place_name": "Roy Spiegel MSW",
    "street_number": "1",
    "street": "Bridge Plaza North",
    "city": "Fort Lee",
    "neighbourhood": "Koreatown",
    "city_clean": "Fort Lee",
    "state_province": "New Jersey",
    "state_abbr": "NJ",
    "county": "Bergen County",
    "country": "United States",
    "country_code": "US",
    "postal_code": "07024",
    "formatted_address": "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, New Jersey, 07024, United States",
    "osm_id": "2563205146",
    "osm_type": "node",
    "place_name_no_dupe": "Roy Spiegel MSW",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "display_option,expected_state",
    [
        ("zone_name", "not_home"),
        ("zone, place", "not_home, Roy Spiegel MSW, house, 1, Bridge Plaza North"),
        ("zone_name, place", "not_home, Roy Spiegel MSW, house, 1, Bridge Plaza North"),
        ("formatted_place", "Roy Spiegel MSW, Fort Lee, NJ"),
        (
            "name_no_dupe, category(-, place), type(-, yes), neighborhood, house_number, street",
            "Roy Spiegel MSW, House, Koreatown, 1 Bridge Plaza North",
        ),
        (
            "zone_name[driving, name_no_dupe[type(-, unclassified, category(-, highway))[category(-, highway)], house_number, route_number(type(+, motorway, trunk))[street[route_number]], neighborhood(type(house))], city_clean[county], state_abbr]",
            "Roy Spiegel MSW, Fort Lee, NJ",
        ),
    ],
)
async def test_display_options_state_render(
    display_option: str, expected_state: str, mock_hass, patch_entity_registry
):
    """Assert that a CONF_DISPLAY_OPTIONS value renders the expected state."""

    # Minimal config / objects required for Places init
    # Use shared mock_hass fixture for consistency
    # Ensure entity registry lookups are skipped for this mocked hass
    # Use the shared `patch_entity_registry` fixture to avoid inline registry patching.
    config_entry = MockConfigEntry(domain="places", data={CONF_NAME: "Test Place"})
    config = {CONF_DEVICETRACKER_ID: "device_tracker.test_iphone"}

    hass = mock_hass

    sensor = Places(hass, config, config_entry, "Test Place", "unique-id-123", {})

    # Inject snapshot of attributes (simulate post-parse_osm_dict state)
    sensor._internal_attr = copy.deepcopy(BASE_INTERNAL_ATTR)

    # Ensure we start fresh wrt previously computed native value
    sensor.clear_attr(ATTR_NATIVE_VALUE)
    sensor._attr_native_value = None

    # Apply parameterized display option
    sensor.set_attr(CONF_DISPLAY_OPTIONS, display_option)
    sensor.set_attr(ATTR_DISPLAY_OPTIONS, display_option)
    # Clear any stale list so process_display_options rebuilds it
    sensor.set_attr(ATTR_DISPLAY_OPTIONS_LIST, [])

    # Force out-of-zone behavior (devicetracker_zone_name is 'not_home')
    # Temporarily patch the instance methods so they are restored after the block.
    # Also patch get_driving_status to avoid I/O or time-dependent work during the test.
    with (
        patch.object(sensor, "in_zone", AsyncMock(return_value=False)),
        patch.object(sensor, "get_driving_status", AsyncMock(return_value=None)),
    ):
        await sensor.process_display_options()

    assert sensor.get_attr(ATTR_NATIVE_VALUE) == expected_state, (
        f"Display option '{display_option}' produced '{sensor.get_attr(ATTR_NATIVE_VALUE)}', "
        f"expected '{expected_state}'."
    )
