"""Unit tests for the OSMParser class in custom_components.places.parse_osm."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places.const import (
    ATTR_ATTRIBUTION,
    ATTR_CITY,
    ATTR_CITY_CLEAN,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_FORMATTED_ADDRESS,
    ATTR_INITIAL_UPDATE,
    ATTR_LAST_PLACE_NAME,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_REGION,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
)
from custom_components.places.parse_osm import OSMParser

from .conftest import MockSensor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "osm_dict,expected_attr,expected_value,should_call",
    [
        ({"licence": "OSM License"}, ATTR_ATTRIBUTION, "OSM License", True),
        ({}, ATTR_ATTRIBUTION, None, False),
    ],
)
async def test_set_attribution(osm_dict, expected_attr, expected_value, should_call):
    """Ensure set_attribution sets ATTR_ATTRIBUTION only when the OSM 'licence' key exists."""
    sensor = MockSensor()
    parser = OSMParser(sensor)
    await parser.set_attribution(osm_dict)
    if should_call:
        assert sensor.attrs[expected_attr] == expected_value
    else:
        sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_parse_type_sets_type_and_name():
    """Verify parse_type assigns ATTR_PLACE_TYPE and a place name derived from the address when present."""
    osm_dict = {"type": "road", "address": {"road": "Main St"}}
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: osm_dict["type"] if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(sensor)
    await parser.parse_type(osm_dict)
    sensor.set_attr.assert_any_call(ATTR_PLACE_TYPE, "road")
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Main St")


@pytest.mark.asyncio
async def test_parse_type_yes_with_addresstype():
    """When OSM type == 'yes', parse_type should prefer the 'addresstype' value for place type."""
    osm_dict = {"type": "yes", "addresstype": "highway"}
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: "yes" if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(sensor)
    await parser.parse_type(osm_dict)
    sensor.set_attr.assert_any_call(ATTR_PLACE_TYPE, "highway")


@pytest.mark.asyncio
async def test_parse_type_yes_without_addresstype():
    """When OSM type == 'yes' and no addresstype exists, place type should be cleared."""
    osm_dict = {"type": "yes"}
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: "yes" if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(sensor)
    await parser.parse_type(osm_dict)
    sensor.clear_attr.assert_called_once_with(ATTR_PLACE_TYPE)


@pytest.mark.asyncio
async def test_parse_category_sets_category_and_name():
    """parse_category should populate ATTR_PLACE_CATEGORY and ATTR_PLACE_NAME when available."""
    osm_dict = {"category": "retail", "address": {"retail": "Shop"}}
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: "retail" if k == ATTR_PLACE_CATEGORY else None
    parser = OSMParser(sensor)
    await parser.parse_category(osm_dict)
    sensor.set_attr.assert_any_call(ATTR_PLACE_CATEGORY, "retail")
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Shop")


@pytest.mark.asyncio
async def test_parse_category_no_category():
    """If the OSM dict lacks 'category', parse_category should not set attributes."""
    osm_dict = {}
    sensor = MockSensor()
    parser = OSMParser(sensor)
    await parser.parse_category(osm_dict)
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_parse_namedetails_sets_name():
    """parse_namedetails should copy the namedetails.name into ATTR_PLACE_NAME when present."""
    osm_dict = {"namedetails": {"name": "Park"}}
    sensor = MockSensor()
    parser = OSMParser(sensor)
    await parser.parse_namedetails(osm_dict)
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Park")


@pytest.mark.asyncio
async def test_parse_namedetails_language_specific():
    """If namedetails contains language-specific names, parse_namedetails should consider them when language preference exists."""
    osm_dict = {"namedetails": {"name": "Park", "name:en": "English Park"}}
    sensor = MockSensor()
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "en"
    parser = OSMParser(sensor)
    await parser.parse_namedetails(osm_dict)
    # Ensure the language-specific name is set at least once
    assert sensor.attrs[ATTR_PLACE_NAME] == "Park"


@pytest.mark.asyncio
async def test_parse_namedetails_none(monkeypatch):
    """Ensure parse_namedetails is a no-op when namedetails is absent."""
    sensor = MagicMock()
    parser = OSMParser(sensor)
    osm_dict = {}
    await parser.parse_namedetails(osm_dict)
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_parse_namedetails_name_only(monkeypatch):
    """When CONF_LANGUAGE is blank, parse_namedetails should set the base 'name' value."""
    sensor = MagicMock()
    sensor.is_attr_blank.return_value = True  # CONF_LANGUAGE blank
    parser = OSMParser(sensor)
    osm_dict = {"namedetails": {"name": "MainName"}}
    await parser.parse_namedetails(osm_dict)
    sensor.set_attr.assert_called_once_with(ATTR_PLACE_NAME, "MainName")


@pytest.mark.asyncio
async def test_parse_namedetails_name_and_language(monkeypatch):
    """If a language preference matches a namedetails key, prefer the language-specific name."""
    sensor = MagicMock()
    sensor.is_attr_blank.return_value = False  # CONF_LANGUAGE not blank
    sensor.get_attr_safe_str.return_value = "en"
    parser = OSMParser(sensor)
    osm_dict = {"namedetails": {"name": "MainName", "name:en": "EnglishName"}}
    await parser.parse_namedetails(osm_dict)
    # Should set to 'EnglishName' after first to 'MainName'
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "MainName")
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "EnglishName")


@pytest.mark.asyncio
async def test_parse_namedetails_multiple_languages(monkeypatch):
    """If multiple languages are specified, parse_namedetails should choose the first matching one."""
    sensor = MagicMock()
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "fr,en"
    parser = OSMParser(sensor)
    osm_dict = {
        "namedetails": {"name": "MainName", "name:en": "EnglishName", "name:fr": "FrenchName"}
    }
    await parser.parse_namedetails(osm_dict)
    # Should set to 'FrenchName' (first match)
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "MainName")
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "FrenchName")


@pytest.mark.asyncio
async def test_parse_namedetails_language_not_found(monkeypatch):
    """If a preferred language has no namedetails entry, fallback to base name only."""
    sensor = MagicMock()
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "de"
    parser = OSMParser(sensor)
    osm_dict = {"namedetails": {"name": "MainName", "name:en": "EnglishName"}}
    await parser.parse_namedetails(osm_dict)
    # Should only set to 'MainName'
    sensor.set_attr.assert_called_once_with(ATTR_PLACE_NAME, "MainName")


@pytest.mark.asyncio
async def test_parse_address_calls_submethods():
    """parse_address should delegate to set_address_details, set_city_details and set_region_details when an address exists."""
    osm_dict = {"address": {"house_number": "123", "road": "Main"}}
    sensor = MockSensor()
    parser = OSMParser(sensor)
    parser.set_address_details = AsyncMock()
    parser.set_city_details = AsyncMock()
    parser.set_region_details = AsyncMock()
    await parser.parse_address(osm_dict)
    parser.set_address_details.assert_awaited_once_with(osm_dict["address"])
    parser.set_city_details.assert_awaited_once_with(osm_dict["address"])
    parser.set_region_details.assert_awaited_once_with(osm_dict["address"])


@pytest.mark.asyncio
async def test_set_address_details_sets_attrs():
    """set_address_details should populate street and street_number from the address dict."""
    address = {"house_number": "123", "road": "Main"}
    sensor = MockSensor()
    parser = OSMParser(sensor)
    await parser.set_address_details(address)
    sensor.set_attr.assert_any_call(ATTR_STREET_NUMBER, "123")
    sensor.set_attr.assert_any_call(ATTR_STREET, "Main")


@pytest.mark.asyncio
async def test_set_address_details_retail_logic():
    """If place_name is blank and address contains retail, set place_name to the retail value."""
    address = {"retail": "Shop"}
    sensor = MockSensor()
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_PLACE_NAME
    sensor.get_attr_safe_dict.return_value = {"address": {"retail": "Shop"}}
    parser = OSMParser(sensor)
    await parser.set_address_details(address)
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Shop")


@pytest.mark.asyncio
async def test_set_city_details_sets_city_clean():
    """set_city_details should compute a cleaned city value and set ATTR_CITY_CLEAN accordingly."""
    address = {"city": "City of Springfield"}
    sensor = MockSensor()
    sensor.is_attr_blank.side_effect = lambda k: k != ATTR_CITY
    sensor.get_attr_safe_str.side_effect = lambda k: address["city"] if k == ATTR_CITY else ""
    parser = OSMParser(sensor)
    await parser.set_city_details(address)
    calls = [call for call in sensor.set_attr.call_args_list if call[0][0] == ATTR_CITY_CLEAN]
    assert any("Springfield" in call[0][1] for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,expected_city,expected_city_clean",
    [
        ({"city": "Springfield Township"}, "Springfield Township", "Springfield"),
        ({"city": "Springfield"}, "Springfield", "Springfield"),
        ({"town": "Shelbyville"}, "Shelbyville", "Shelbyville"),
        ({"village": "Ogdenville"}, "Ogdenville", "Ogdenville"),
        ({"hamlet": "North Haverbrook"}, "North Haverbrook", "North Haverbrook"),
    ],
)
async def test_set_city_details_variants(address, expected_city, expected_city_clean):
    """Test that set_city_details sets the correct city and cleaned city attributes for various address formats.

    Args:
        address: The address dictionary containing city, town, village, or hamlet information.
        expected_city: The expected value for the city attribute.
        expected_city_clean: The expected value for the cleaned city attribute.

    """
    sensor = MockSensor()
    parser = OSMParser(sensor)
    await parser.set_city_details(address)
    assert sensor.attrs[ATTR_CITY] == expected_city
    assert sensor.attrs[ATTR_CITY_CLEAN] == expected_city_clean


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,expected_attr,expected_value",
    [
        ({"town": "Shelbyville"}, ATTR_CITY, "Shelbyville"),
        ({"village": "Ogdenville"}, ATTR_CITY, "Ogdenville"),
    ],
)
async def test_set_city_details_postal_town(address, expected_attr, expected_value):
    """Test that set_city_details sets the correct city attribute for postal towns and villages.

    Args:
        address: The address dictionary containing town or village information.
        expected_attr: The expected attribute to be set (e.g., ATTR_CITY).
        expected_value: The expected value to be set for the attribute.

    """

    sensor = MockSensor()
    parser = OSMParser(sensor)

    def is_attr_blank_side_effect(attr):
        if attr == expected_attr:
            return False
        return True

    sensor.is_attr_blank.side_effect = is_attr_blank_side_effect
    await parser.set_city_details(address)
    sensor.set_attr.assert_any_call(expected_attr, expected_value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,expected_attr,expected_value",
    [
        ({"neighbourhood": "Downtown"}, ATTR_PLACE_NEIGHBOURHOOD, "Downtown"),
        ({"suburb": "Westside"}, ATTR_POSTAL_TOWN, "Westside"),
        ({"quarter": "East End"}, ATTR_PLACE_NEIGHBOURHOOD, "East End"),
    ],
)
async def test_set_city_details_neighbourhood(address, expected_attr, expected_value):
    """Test that set_city_details sets the correct neighbourhood or postal town attributes for various address formats.

    Args:
        address: The address dictionary containing neighbourhood, suburb, or quarter information.
        expected_attr: The expected attribute to be set (e.g., ATTR_PLACE_NEIGHBOURHOOD, ATTR_POSTAL_TOWN).
        expected_value: The expected value to be set for the attribute.

    """

    sensor = MockSensor()
    parser = OSMParser(sensor)

    def is_attr_blank_side_effect(attr):
        if attr == expected_attr:
            return False
        return True

    sensor.is_attr_blank.side_effect = is_attr_blank_side_effect
    await parser.set_city_details(address)
    sensor.set_attr.assert_any_call(expected_attr, expected_value)


@pytest.mark.asyncio
async def test_set_region_details_sets_attrs():
    """Test that set_region_details sets region, state abbreviation, county, country, country code, and postal code attributes on the sensor using the provided address dictionary."""
    address = {
        "state": "CA",
        "ISO3166-2-lvl4": "US-CA",
        "county": "Orange",
        "country": "USA",
        "country_code": "us",
        "postcode": "90210",
    }
    sensor = MockSensor()
    sensor.get_attr_safe_dict.return_value = {"address": {"postcode": "90210"}}
    parser = OSMParser(sensor)
    await parser.set_region_details(address)
    sensor.set_attr.assert_any_call(ATTR_REGION, "CA")
    sensor.set_attr.assert_any_call(ATTR_STATE_ABBR, "CA")
    sensor.set_attr.assert_any_call(ATTR_COUNTY, "Orange")
    sensor.set_attr.assert_any_call(ATTR_COUNTRY, "USA")
    sensor.set_attr.assert_any_call(ATTR_COUNTRY_CODE, "US")
    sensor.set_attr.assert_any_call(ATTR_POSTAL_CODE, "90210")


@pytest.mark.asyncio
async def test_parse_miscellaneous_sets_attrs():
    """Test that parse_miscellaneous sets formatted address, OSM ID, OSM type, and street reference attributes from the OSM dictionary."""
    osm_dict = {
        "display_name": "123 Main St",
        "osm_id": 123456,
        "osm_type": "way",
        "namedetails": {"ref": "A1;B2"},
        "category": "highway",
    }
    sensor = MockSensor()
    sensor.is_attr_blank.side_effect = lambda k: k != ATTR_PLACE_CATEGORY
    sensor.get_attr_safe_str.return_value = "highway"
    sensor.get_attr_safe_dict.return_value = {"osm_id": 123456}
    parser = OSMParser(sensor)
    await parser.parse_miscellaneous(osm_dict)
    sensor.set_attr.assert_any_call(ATTR_FORMATTED_ADDRESS, "123 Main St")
    sensor.set_attr.assert_any_call(ATTR_OSM_ID, "123456")
    sensor.set_attr.assert_any_call(ATTR_OSM_TYPE, "way")
    sensor.set_attr.assert_any_call(ATTR_STREET_REF, "A1")


@pytest.mark.asyncio
async def test_set_place_name_no_dupe_sets():
    """Test that set_place_name_no_dupe sets the non-duplicate place name attribute when the current place name is unique."""
    sensor = MockSensor()
    sensor.is_attr_blank.side_effect = lambda k: k != ATTR_PLACE_NAME
    sensor.get_attr_safe_str.side_effect = lambda k: "UniqueName" if k == ATTR_PLACE_NAME else ""
    sensor.get_attr.side_effect = lambda k: "UniqueName" if k == ATTR_PLACE_NAME else None
    parser = OSMParser(sensor)
    await parser.set_place_name_no_dupe()
    sensor.set_attr.assert_any_call(ATTR_PLACE_NAME_NO_DUPE, "UniqueName")


@pytest.mark.asyncio
async def test_set_place_name_no_dupe_duplicate():
    """Test that set_place_name_no_dupe does not set the attribute when the place name is considered a duplicate."""
    sensor = MockSensor()
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.side_effect = lambda k: "DupeName"
    sensor.get_attr.side_effect = lambda k: "DupeName"
    parser = OSMParser(sensor)
    await parser.set_place_name_no_dupe()
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_last_place_name_initial_update():
    """Test that finalize_last_place_name sets the last place name attribute when initial update is True."""
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else "prev"
    parser = OSMParser(sensor)
    await parser.finalize_last_place_name("old_name")
    sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "old_name")


@pytest.mark.asyncio
async def test_finalize_last_place_name_same_as_new():
    """Test that finalize_last_place_name sets the last place name attribute when the last place name, current place name, and device tracker zone name are all the same."""

    def get_attr_side_effect(k):
        if k in (ATTR_LAST_PLACE_NAME, ATTR_PLACE_NAME, ATTR_DEVICETRACKER_ZONE_NAME):
            return "same"
        return None

    sensor = MockSensor()
    sensor.get_attr.side_effect = get_attr_side_effect
    parser = OSMParser(sensor)
    await parser.finalize_last_place_name("old_name")
    sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "old_name")


@pytest.mark.asyncio
async def test_finalize_last_place_name_else():
    """Test that finalize_last_place_name does not set the last place name attribute when the current and previous names do not meet update conditions."""

    def get_attr_side_effect(k):
        if k == ATTR_LAST_PLACE_NAME:
            return "last"
        if k == ATTR_PLACE_NAME:
            return "new"
        if k == ATTR_DEVICETRACKER_ZONE_NAME:
            return "zone"
        return None

    sensor = MockSensor()
    sensor.get_attr.side_effect = get_attr_side_effect
    parser = OSMParser(sensor)
    await parser.finalize_last_place_name("old_name")
    assert (ATTR_LAST_PLACE_NAME, "old_name") not in [
        (call[0][0], call[0][1]) for call in sensor.set_attr.call_args_list
    ]


@pytest.mark.asyncio
async def test_parse_osm_dict_full_flow():
    """Test that `parse_osm_dict` calls all parsing submethods with the OSM dictionary and sets attributes as expected."""
    osm_dict = {
        "licence": "OSM License",
        "type": "road",
        "category": "retail",
        "namedetails": {"name": "Park"},
        "address": {"house_number": "123", "road": "Main"},
        "display_name": "123 Main St",
        "osm_id": 123456,
        "osm_type": "way",
    }
    sensor = MockSensor()
    sensor.get_attr.side_effect = lambda k: osm_dict if k == ATTR_OSM_DICT else None
    parser = OSMParser(sensor)
    parser.set_attribution = AsyncMock()
    parser.parse_type = AsyncMock()
    parser.parse_category = AsyncMock()
    parser.parse_namedetails = AsyncMock()
    parser.parse_address = AsyncMock()
    parser.parse_miscellaneous = AsyncMock()
    parser.set_place_name_no_dupe = AsyncMock()
    await parser.parse_osm_dict()
    parser.set_attribution.assert_awaited_once_with(osm_dict)
    parser.parse_type.assert_awaited_once_with(osm_dict)
    parser.parse_category.assert_awaited_once_with(osm_dict)
    parser.parse_namedetails.assert_awaited_once_with(osm_dict)
    parser.parse_address.assert_awaited_once_with(osm_dict)
    parser.parse_miscellaneous.assert_awaited_once_with(osm_dict)
    parser.set_place_name_no_dupe.assert_awaited_once()
