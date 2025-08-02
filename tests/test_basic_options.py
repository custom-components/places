from unittest.mock import patch

import pytest

from custom_components.places.basic_options import BasicOptionsParser
from tests.conftest import MockSensor


@pytest.mark.asyncio
async def test_build_display_all_blank():
    sensor = MockSensor()
    parser = BasicOptionsParser(sensor, {}, ["driving", "zone_name", "zone", "place"])
    result = await parser.build_display()
    assert result == ""


@pytest.mark.asyncio
async def test_build_display_some_attrs():
    """Test that build_display() includes specified attributes in the output string when present.

    Verifies that the display string contains the values for driving status, zone name, place name, street, and city when these attributes are provided.
    """
    attrs = {
        "driving": "Driving",
        "devicetracker_zone_name": "Home",
        "place_name": "Park",
        "street": "Main St",
        "city": "Springfield",
    }
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["driving", "zone_name", "place", "street", "city"])
    result = await parser.build_display()
    # Should include driving, zone_name, place_name, street, city
    assert "Driving" in result
    assert "Home" in result
    assert "Park" in result
    assert "Main St" in result
    assert "Springfield" in result


@pytest.mark.asyncio
async def test_build_display_do_not_reorder():
    """Test that `build_display()` preserves attribute order and formatting when 'do_not_reorder' is specified in options.

    Verifies that only the city and region (as state) are included in the output, maintaining the specified order.
    """
    attrs = {"city": "Springfield", "region": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["do_not_reorder", "city", "state"])
    result = await parser.build_display()
    # Should reorder and only include city and region (for state)
    assert result == "Springfield, IL"


@pytest.mark.asyncio
async def test_build_display_in_zone_logic():
    """Test that `build_display()` includes the zone name when the sensor is in a zone.

    Verifies that when the sensor's `in_zone` flag is set and `devicetracker_zone_name` is provided, the resulting display string contains the zone name.
    """
    attrs = {"devicetracker_zone_name": "Work"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_display()
    assert "Work" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_place_name():
    """Test that `build_formatted_place()` returns the `place_name` when the sensor is not in a zone and `place_name` is non-blank and unique."""
    attrs = {"place_name": "Central Park"}
    sensor = MockSensor(attrs, display_options_list=["driving"])
    parser = BasicOptionsParser(sensor, attrs, ["place"])
    # should_use_place_name returns True if place_name not blank and not duplicate
    result = await parser.build_formatted_place()
    assert "Central Park" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_type_category_street():
    """Test that build_formatted_place() constructs a formatted place string using place_type, place_category, street, and city when not in a zone and place_name is blank."""
    attrs = {
        "place_type": "restaurant",
        "place_category": "food",
        "street": "Elm St",
        "city": "Metropolis",
    }
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["place"])
    # should_use_place_name returns False if place_name blank
    attrs["place_name"] = ""
    result = await parser.build_formatted_place()
    assert "Restaurant" in result or "Food" in result
    assert "Elm St" in result
    assert "Metropolis" in result


@pytest.mark.asyncio
async def test_build_formatted_place_in_zone():
    """Test that `build_formatted_place()` returns the zone name when the sensor is in a zone."""
    attrs = {"devicetracker_zone_name": "Home"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_formatted_place()
    assert result == "Home"


def test_should_use_place_name_true():
    """Test that `should_use_place_name` returns True when a non-blank place name is present and no duplicates are defined."""
    attrs = {"place_name": "Park"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    # PLACE_NAME_DUPLICATE_LIST not present, so should use place_name
    assert parser.should_use_place_name(attrs, sensor) is True


def test_should_use_place_name_false_blank():
    """Test that should_use_place_name() returns False when the place_name attribute is blank."""
    attrs = {"place_name": ""}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    assert parser.should_use_place_name(attrs, sensor) is False


def test_should_use_place_name_false_duplicate():
    """Test that should_use_place_name() returns False when place_name duplicates another attribute specified in the duplicate list."""
    attrs = {"place_name": "Dup", "city": "Dup"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    # Patch the duplicate list to include "city"
    with patch("custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST", ["city"]):
        assert parser.should_use_place_name(attrs, sensor) is False


def test_add_type_or_category_type():
    """Test that `add_type_or_category` adds the capitalized `place_type` to the list when it is not "unclassified"."""
    attrs = {"place_type": "restaurant", "place_category": "food"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert "Restaurant" in arr


def test_add_type_or_category_category():
    """Test that `add_type_or_category` adds the capitalized place category when the place type is 'unclassified'."""
    attrs = {"place_type": "unclassified", "place_category": "food"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert "Food" in arr


def test_add_street_info_street():
    """Test that `add_street_info` appends the street name to the list when the street number is empty."""
    attrs = {"street": "Main St", "street_number": ""}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert "Main St" in arr


def test_add_street_info_street_number():
    """Test that add_street_info appends the combined street number and street name to the list when both are present."""
    attrs = {"street": "Main St", "street_number": "123"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert "123 Main St" in arr


def test_add_neighbourhood_if_house():
    """Test that `add_neighbourhood_if_house` appends the neighborhood to the list when the place type is 'house'."""
    attrs = {"place_type": "house", "place_neighbourhood": "Downtown"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_neighbourhood_if_house(arr, attrs, sensor)
    assert "Downtown" in arr


def test_add_city_county_state_city_clean():
    """Test that `add_city_county_state` adds `city_clean` and `state_abbr` to the output list when present."""
    attrs = {"city_clean": "Springfield", "state_abbr": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Springfield" in arr
    assert "IL" in arr


def test_add_city_county_state_city():
    """Test that `add_city_county_state` appends city and state abbreviation to the output list when `city` is present."""
    attrs = {"city": "Springfield", "state_abbr": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Springfield" in arr
    assert "IL" in arr


def test_add_city_county_state_county():
    """Test that `add_city_county_state` appends county and state abbreviation to the list when city attributes are absent."""
    attrs = {"county": "Clark", "state_abbr": "OH"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Clark" in arr
    assert "OH" in arr
