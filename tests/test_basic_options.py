"""Unit tests for the BasicOptionsParser class in the places custom component."""

import pytest

from custom_components.places.basic_options import BasicOptionsParser
from custom_components.places.const import ATTR_PLACE_NAME
from tests.conftest import mock_sensor


@pytest.fixture
def sensor():
    """Shared sensor fixture returning a configured MockSensor instance."""
    return mock_sensor()


@pytest.fixture
def basic_parser():
    """Factory fixture to create a BasicOptionsParser and its backing sensor.

    Returns (parser, sensor).
    """

    def _create(attrs=None, options=None, display_options_list=None, in_zone=False):
        sensor = mock_sensor(
            attrs=attrs, display_options_list=display_options_list, in_zone=in_zone
        )
        parser = BasicOptionsParser(sensor, attrs or {}, options or [])
        return parser, sensor

    return _create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,attrs,in_zone,options,expected_contains,expected_eq",
    [
        (
            "all_blank",
            {},
            False,
            ["driving", "zone_name", "zone", "place"],
            [],
            None,
        ),
        (
            "some_attrs",
            {
                "driving": "Driving",
                "devicetracker_zone_name": "Home",
                "place_name": "Park",
                "street": "Main St",
                "city": "Springfield",
            },
            False,
            ["driving", "zone_name", "place", "street", "city"],
            ["Driving", "Home", "Park", "Main St", "Springfield"],
            None,
        ),
        (
            "do_not_reorder",
            {"city": "Springfield", "region": "IL"},
            False,
            ["do_not_reorder", "city", "state"],
            [],
            "Springfield, IL",
        ),
        (
            "in_zone",
            {"devicetracker_zone_name": "Work"},
            True,
            ["zone_name"],
            ["Work"],
            None,
        ),
    ],
)
async def test_build_display_scenarios(
    scenario, attrs, in_zone, options, expected_contains, expected_eq, mock_hass, sensor
):
    """Parametrized scenarios for BasicOptionsParser.build_display covering blank, populated, reorder, and in-zone cases."""
    mock_hass.states.async_set("sensor._pp_demo", "on")
    # Mutate shared sensor fixture for this scenario
    sensor.attrs = attrs or {}
    sensor._in_zone = in_zone
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_display()
    if expected_eq is not None:
        assert result == expected_eq
    else:
        for substr in expected_contains:
            assert substr in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,attrs,in_zone,options,display_list,expected_contains,expected_eq",
    [
        (
            "place_name",
            {ATTR_PLACE_NAME: "Central Park"},
            False,
            ["place"],
            ["driving"],
            ["Central Park"],
            None,
        ),
        (
            "type_category",
            {
                "place_type": "restaurant",
                "place_category": "food",
                "street": "Elm St",
                "city": "Metropolis",
                "place_name": "",
            },
            False,
            ["place"],
            None,
            ["Elm St", "Metropolis"],
            None,
        ),
        (
            "in_zone",
            {"devicetracker_zone_name": "Home"},
            True,
            ["zone_name"],
            None,
            [],
            "Home",
        ),
    ],
)
async def test_build_formatted_place_variants(
    scenario, attrs, in_zone, options, display_list, expected_contains, expected_eq, sensor
):
    """Parametrized scenarios for BasicOptionsParser.build_formatted_place."""
    sensor.attrs = attrs or {}
    sensor._in_zone = in_zone
    sensor.display_options_list = display_list or []
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_formatted_place()
    if expected_eq is not None:
        assert result == expected_eq
        return
    # Special-case: type_category accepts either Type or Category wording
    if scenario == "type_category":
        assert ("Restaurant" in result) or ("Food" in result)
    for substr in expected_contains:
        assert substr in result


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"place_type": "restaurant", "place_category": "food"}, "Restaurant"),
        ({"place_type": "unclassified", "place_category": "food"}, "Food"),
    ],
)
def test_add_type_or_category(attrs, expected, basic_parser):
    """Test that `add_type_or_category` adds the correct capitalized type or category to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"street": "Main St", "street_number": ""}, "Main St"),
        ({"street": "Main St", "street_number": "123"}, "123 Main St"),
    ],
)
def test_add_street_info(attrs, expected, basic_parser):
    """Test that `add_street_info` appends the correct street info to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    "attrs,expected_city,expected_state",
    [
        ({"city_clean": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"city": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"county": "Clark", "state_abbr": "OH"}, "Clark", "OH"),
    ],
)
def test_add_city_county_state(attrs, expected_city, expected_state, basic_parser):
    """Test that `add_city_county_state` appends the correct city/county and state abbreviation to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert expected_city in arr
    assert expected_state in arr


@pytest.mark.parametrize(
    "attrs,duplicate_list,expected",
    [
        ({"place_name": "Park"}, [], True),
        ({"place_name": ""}, [], False),
        ({"place_name": "Dup", "city": "Dup"}, ["city"], False),
    ],
)
def test_should_use_place_name(attrs, duplicate_list, expected, basic_parser, monkeypatch):
    """Test that `should_use_place_name` returns the correct boolean based on place_name and duplicates."""
    parser, sensor = basic_parser(attrs=attrs)
    if duplicate_list:
        monkeypatch.setattr(
            "custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST",
            duplicate_list,
            raising=False,
        )
    assert parser.should_use_place_name(attrs, sensor) is expected
