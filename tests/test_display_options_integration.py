"""Integration tests for display options rendering in the Places sensor."""

from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
from custom_components.places.coordinator import PlacesUpdateCoordinator

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
    "display_options": "formatted_place",
    "home_latitude": 40.824763,
    "home_longitude": -73.973675,
    "show_date": False,
    "zone_name": "not_home",
    "zone": "not_home",
    "direction_of_travel": "towards home",
    "distance_from_home": 23898.658,
    "distance_traveled": 2378.348,
    "gps_accuracy": 4.0,
    "last_changed": "2025-07-30 16:52:35-04:00",
    "last_place_name": "Riverside Drive",
    "last_updated": "2025-07-30 16:52:35-04:00",
    "previous_latitude": 40.83871498707779,
    "latitude": 40.854733600095464,
    "previous_longitude": -73.94654779701861,
    "longitude": -73.96526768799811,
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
    "neighborhood": "Koreatown",
    "city_clean": "Fort Lee",
    "state": "New Jersey",
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

README_PLACE_ADVANCED = (
    "name_no_dupe, category(-, place), type(-, yes), neighborhood, house_number, street"
)

README_FORMATTED_PLACE_ADVANCED = (
    "zone_name[driving, name_no_dupe[type(-, unclassified, category(-, highway))"
    "[category(-, highway)], house_number, route_number(type(+, motorway, trunk))"
    "[street[route_number]], neighborhood(type(house))], city_clean[county], state_abbr]"
)


async def render_display_option(
    mock_hass: MagicMock, monkeypatch: pytest.MonkeyPatch, display_option: str
) -> str | None:
    """Render one display option using the coordinator attribute snapshot."""
    mock_hass.states.get.return_value = None
    config_entry = MockConfigEntry(
        domain="places",
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test_iphone",
        },
    )
    persistence = MagicMock()
    persistence.async_save = AsyncMock()
    persistence.async_remove = AsyncMock()
    coordinator = PlacesUpdateCoordinator(
        mock_hass,
        config_entry,
        copy.deepcopy(BASE_INTERNAL_ATTR),
        persistence,
    )
    coordinator.clear_attr(ATTR_NATIVE_VALUE)
    coordinator.set_attr(CONF_DISPLAY_OPTIONS, display_option)
    coordinator.set_attr(ATTR_DISPLAY_OPTIONS, display_option)
    coordinator.set_attr(ATTR_DISPLAY_OPTIONS_LIST, [])
    monkeypatch.setattr(coordinator, "in_zone", AsyncMock(return_value=False), raising=False)
    monkeypatch.setattr(
        coordinator,
        "get_driving_status",
        AsyncMock(return_value=None),
        raising=False,
    )

    await coordinator.process_display_options()

    return coordinator.get_attr(ATTR_NATIVE_VALUE)


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_entity_registry")
@pytest.mark.parametrize(
    ("display_option", "expected_state"),
    [
        ("zone_name", "not_home"),
        (
            "zone, place",
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        (
            "zone_name, place",
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        ("formatted_place", "Roy Spiegel MSW, Fort Lee, NJ"),
        (
            "osm_formatted_address",
            "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, "
            "New Jersey, 07024, United States",
        ),
        (
            README_PLACE_ADVANCED,
            "Roy Spiegel MSW, House, Koreatown, 1 Bridge Plaza North",
        ),
        (
            README_FORMATTED_PLACE_ADVANCED,
            "Roy Spiegel MSW, Fort Lee, NJ",
        ),
    ],
)
async def test_display_options_state_render(
    display_option: str,
    expected_state: str,
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert that a CONF_DISPLAY_OPTIONS value renders the expected state."""
    state = await render_display_option(mock_hass, monkeypatch, display_option)

    assert state == expected_state


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_entity_registry")
async def test_basic_place_option_includes_neighborhood(
    mock_hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Basic place options should retain neighborhood context."""
    basic_state = await render_display_option(mock_hass, monkeypatch, "place")

    assert basic_state
    assert "Koreatown" in basic_state


def test_readme_display_examples_are_documented() -> None:
    """Assert that README still contains the two example advanced display strings."""
    readme = Path(__file__).resolve().parent.parent / "README.md"
    readme_contents = readme.read_text(encoding="utf-8")

    assert README_PLACE_ADVANCED in readme_contents
    assert README_FORMATTED_PLACE_ADVANCED in readme_contents
