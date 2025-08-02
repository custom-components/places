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
    attrs = {"city": "Springfield", "region": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["do_not_reorder", "city", "state"])
    result = await parser.build_display()
    # Should reorder and only include city and region (for state)
    assert result == "Springfield, IL"


@pytest.mark.asyncio
async def test_build_display_in_zone_logic():
    attrs = {"devicetracker_zone_name": "Work"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_display()
    assert "Work" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_place_name():
    attrs = {"place_name": "Central Park"}
    sensor = MockSensor(attrs, display_options_list=["driving"])
    parser = BasicOptionsParser(sensor, attrs, ["place"])
    # should_use_place_name returns True if place_name not blank and not duplicate
    result = await parser.build_formatted_place()
    assert "Central Park" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_type_category_street():
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
    attrs = {"devicetracker_zone_name": "Home"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_formatted_place()
    assert result == "Home"


def test_should_use_place_name_true():
    attrs = {"place_name": "Park"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    # PLACE_NAME_DUPLICATE_LIST not present, so should use place_name
    assert parser.should_use_place_name(attrs, sensor) is True


def test_should_use_place_name_false_blank():
    attrs = {"place_name": ""}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    assert parser.should_use_place_name(attrs, sensor) is False


def test_should_use_place_name_false_duplicate():
    attrs = {"place_name": "Dup", "city": "Dup"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    # Patch the duplicate list to include "city"
    with patch("custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST", ["city"]):
        assert parser.should_use_place_name(attrs, sensor) is False


def test_add_type_or_category_type():
    attrs = {"place_type": "restaurant", "place_category": "food"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert "Restaurant" in arr


def test_add_type_or_category_category():
    attrs = {"place_type": "unclassified", "place_category": "food"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert "Food" in arr


def test_add_street_info_street():
    attrs = {"street": "Main St", "street_number": ""}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert "Main St" in arr


def test_add_street_info_street_number():
    attrs = {"street": "Main St", "street_number": "123"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert "123 Main St" in arr


def test_add_neighbourhood_if_house():
    attrs = {"place_type": "house", "place_neighbourhood": "Downtown"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_neighbourhood_if_house(arr, attrs, sensor)
    assert "Downtown" in arr


def test_add_city_county_state_city_clean():
    attrs = {"city_clean": "Springfield", "state_abbr": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Springfield" in arr
    assert "IL" in arr


def test_add_city_county_state_city():
    attrs = {"city": "Springfield", "state_abbr": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Springfield" in arr
    assert "IL" in arr


def test_add_city_county_state_county():
    attrs = {"county": "Clark", "state_abbr": "OH"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert "Clark" in arr
    assert "OH" in arr
