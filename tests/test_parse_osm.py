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
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_REGION,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
)
from custom_components.places.parse_osm import OSMParser


@pytest.fixture
def mock_sensor():
    """Create a mocked sensor object with stubbed attribute methods for use in tests.

    Returns:
        sensor (MagicMock): A mock object simulating sensor attribute access and modification methods.

    """
    sensor = MagicMock()
    sensor.get_attr = MagicMock()
    sensor.set_attr = MagicMock()
    sensor.clear_attr = MagicMock()
    sensor.is_attr_blank = MagicMock(return_value=True)
    sensor.get_attr_safe_str = MagicMock(return_value="")
    sensor.get_attr_safe_dict = MagicMock(return_value={})
    sensor.get_internal_attr = MagicMock(return_value={})
    return sensor


@pytest.mark.asyncio
async def test_set_attribution_sets_attr(mock_sensor):
    osm_dict = {"licence": "OSM License"}
    parser = OSMParser(mock_sensor)
    await parser.set_attribution(osm_dict)
    mock_sensor.set_attr.assert_called_once_with(ATTR_ATTRIBUTION, "OSM License")


@pytest.mark.asyncio
async def test_set_attribution_no_licence(mock_sensor):
    osm_dict = {}
    parser = OSMParser(mock_sensor)
    await parser.set_attribution(osm_dict)
    mock_sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_parse_type_sets_type_and_name(mock_sensor):
    """Test that `parse_type` sets the place type and place name attributes based on the OSM dictionary's "type" and "address" fields."""
    osm_dict = {"type": "road", "address": {"road": "Main St"}}
    mock_sensor.get_attr.side_effect = lambda k: osm_dict["type"] if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(mock_sensor)
    await parser.parse_type(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_TYPE, "road")
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Main St")


@pytest.mark.asyncio
async def test_parse_type_yes_with_addresstype(mock_sensor):
    """Test that `parse_type` sets the place type attribute to the value of "addresstype" when the OSM type is "yes"."""
    osm_dict = {"type": "yes", "addresstype": "highway"}
    mock_sensor.get_attr.side_effect = lambda k: "yes" if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(mock_sensor)
    await parser.parse_type(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_TYPE, "highway")


@pytest.mark.asyncio
async def test_parse_type_yes_without_addresstype(mock_sensor):
    """Test that `parse_type` clears the place type attribute when the OSM type is "yes" and no address type is provided."""
    osm_dict = {"type": "yes"}
    mock_sensor.get_attr.side_effect = lambda k: "yes" if k == ATTR_PLACE_TYPE else None
    parser = OSMParser(mock_sensor)
    await parser.parse_type(osm_dict)
    mock_sensor.clear_attr.assert_called_once_with(ATTR_PLACE_TYPE)


@pytest.mark.asyncio
async def test_parse_category_sets_category_and_name(mock_sensor):
    """Test that `parse_category` sets the place category and place name attributes when the OSM dictionary contains a category and corresponding address entry."""
    osm_dict = {"category": "retail", "address": {"retail": "Shop"}}
    mock_sensor.get_attr.side_effect = lambda k: "retail" if k == ATTR_PLACE_CATEGORY else None
    parser = OSMParser(mock_sensor)
    await parser.parse_category(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_CATEGORY, "retail")
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Shop")


@pytest.mark.asyncio
async def test_parse_category_no_category(mock_sensor):
    """Test that parse_category does not set any attributes when the OSM dictionary lacks a 'category' key."""
    osm_dict = {}
    parser = OSMParser(mock_sensor)
    await parser.parse_category(osm_dict)
    mock_sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_parse_namedetails_sets_name(mock_sensor):
    """Test that `parse_namedetails` sets the place name attribute from the "name" key in the "namedetails" dictionary of the OSM data."""
    osm_dict = {"namedetails": {"name": "Park"}}
    parser = OSMParser(mock_sensor)
    await parser.parse_namedetails(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Park")


@pytest.mark.asyncio
async def test_parse_namedetails_language_specific(mock_sensor):
    """Test that `parse_namedetails` sets the place name attribute to the language-specific value when available and the current place name is not blank."""
    osm_dict = {"namedetails": {"name": "Park", "name:en": "English Park"}}
    mock_sensor.is_attr_blank.return_value = False
    mock_sensor.get_attr_safe_str.return_value = "en"
    parser = OSMParser(mock_sensor)
    await parser.parse_namedetails(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "English Park")


@pytest.mark.asyncio
async def test_parse_address_calls_submethods(mock_sensor):
    """Test that `parse_address` asynchronously calls the address, city, and region detail submethods with the address dictionary from the OSM data."""
    osm_dict = {"address": {"house_number": "123", "road": "Main"}}
    parser = OSMParser(mock_sensor)
    parser.set_address_details = AsyncMock()
    parser.set_city_details = AsyncMock()
    parser.set_region_details = AsyncMock()
    await parser.parse_address(osm_dict)
    parser.set_address_details.assert_awaited_once_with(osm_dict["address"])
    parser.set_city_details.assert_awaited_once_with(osm_dict["address"])
    parser.set_region_details.assert_awaited_once_with(osm_dict["address"])


@pytest.mark.asyncio
async def test_set_address_details_sets_attrs(mock_sensor):
    """Test that set_address_details sets the street number and street attributes on the sensor from the address dictionary."""
    address = {"house_number": "123", "road": "Main"}
    parser = OSMParser(mock_sensor)
    await parser.set_address_details(address)
    mock_sensor.set_attr.assert_any_call(ATTR_STREET_NUMBER, "123")
    mock_sensor.set_attr.assert_any_call(ATTR_STREET, "Main")


@pytest.mark.asyncio
async def test_set_address_details_retail_logic(mock_sensor):
    """Test that set_address_details sets the place name attribute to the retail value if present and the place name is blank."""
    address = {"retail": "Shop"}
    mock_sensor.is_attr_blank.side_effect = lambda k: k == ATTR_PLACE_NAME
    mock_sensor.get_attr_safe_dict.return_value = {"address": {"retail": "Shop"}}
    parser = OSMParser(mock_sensor)
    await parser.set_address_details(address)
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME, "Shop")


@pytest.mark.asyncio
async def test_set_city_details_sets_city_clean(mock_sensor):
    """Test that set_city_details sets the cleaned city name attribute based on the city value in the address dictionary."""
    address = {"city": "City of Springfield Township"}
    # Simulate city is not blank
    mock_sensor.is_attr_blank.side_effect = lambda k: k != ATTR_CITY
    mock_sensor.get_attr_safe_str.side_effect = lambda k: address["city"] if k == ATTR_CITY else ""
    parser = OSMParser(mock_sensor)
    await parser.set_city_details(address)
    # Accept any call that contains "Springfield" in the cleaned city name
    calls = [call for call in mock_sensor.set_attr.call_args_list if call[0][0] == ATTR_CITY_CLEAN]
    assert any("Springfield" in call[0][1] for call in calls)


@pytest.mark.asyncio
async def test_set_region_details_sets_attrs(mock_sensor):
    """Test that set_region_details sets region, state abbreviation, county, country, country code, and postal code attributes on the sensor using the provided address dictionary."""
    address = {
        "state": "CA",
        "ISO3166-2-lvl4": "US-CA",
        "county": "Orange",
        "country": "USA",
        "country_code": "us",
        "postcode": "90210",
    }
    mock_sensor.get_attr_safe_dict.return_value = {"address": {"postcode": "90210"}}
    parser = OSMParser(mock_sensor)
    await parser.set_region_details(address)
    mock_sensor.set_attr.assert_any_call(ATTR_REGION, "CA")
    mock_sensor.set_attr.assert_any_call(ATTR_STATE_ABBR, "CA")
    mock_sensor.set_attr.assert_any_call(ATTR_COUNTY, "Orange")
    mock_sensor.set_attr.assert_any_call(ATTR_COUNTRY, "USA")
    mock_sensor.set_attr.assert_any_call(ATTR_COUNTRY_CODE, "US")
    mock_sensor.set_attr.assert_any_call(ATTR_POSTAL_CODE, "90210")


@pytest.mark.asyncio
async def test_parse_miscellaneous_sets_attrs(mock_sensor):
    """Test that parse_miscellaneous sets formatted address, OSM ID, OSM type, and street reference attributes from the OSM dictionary."""
    osm_dict = {
        "display_name": "123 Main St",
        "osm_id": 123456,
        "osm_type": "way",
        "namedetails": {"ref": "A1;B2"},
        "category": "highway",
    }
    mock_sensor.is_attr_blank.side_effect = lambda k: k != ATTR_PLACE_CATEGORY
    mock_sensor.get_attr_safe_str.return_value = "highway"
    mock_sensor.get_attr_safe_dict.return_value = {"osm_id": 123456}
    parser = OSMParser(mock_sensor)
    await parser.parse_miscellaneous(osm_dict)
    mock_sensor.set_attr.assert_any_call(ATTR_FORMATTED_ADDRESS, "123 Main St")
    mock_sensor.set_attr.assert_any_call(ATTR_OSM_ID, "123456")
    mock_sensor.set_attr.assert_any_call(ATTR_OSM_TYPE, "way")
    mock_sensor.set_attr.assert_any_call(ATTR_STREET_REF, "A1")


@pytest.mark.asyncio
async def test_set_place_name_no_dupe_sets(mock_sensor):
    """Test that set_place_name_no_dupe sets the non-duplicate place name attribute when the current place name is unique."""
    mock_sensor.is_attr_blank.side_effect = lambda k: k != ATTR_PLACE_NAME
    mock_sensor.get_attr_safe_str.side_effect = (
        lambda k: "UniqueName" if k == ATTR_PLACE_NAME else ""
    )
    mock_sensor.get_attr.side_effect = lambda k: "UniqueName" if k == ATTR_PLACE_NAME else None
    parser = OSMParser(mock_sensor)
    await parser.set_place_name_no_dupe()
    mock_sensor.set_attr.assert_any_call(ATTR_PLACE_NAME_NO_DUPE, "UniqueName")


@pytest.mark.asyncio
async def test_set_place_name_no_dupe_duplicate(mock_sensor):
    # Place name is in dupe_attributes_check
    """Test that set_place_name_no_dupe does not set the attribute when the place name is considered a duplicate."""
    mock_sensor.is_attr_blank.side_effect = lambda k: False
    mock_sensor.get_attr_safe_str.side_effect = lambda k: "DupeName"
    mock_sensor.get_attr.side_effect = lambda k: "DupeName"
    parser = OSMParser(mock_sensor)
    await parser.set_place_name_no_dupe()
    mock_sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_last_place_name_initial_update(mock_sensor):
    mock_sensor.get_attr.side_effect = lambda k: True if k == ATTR_INITIAL_UPDATE else "prev"
    parser = OSMParser(mock_sensor)
    await parser.finalize_last_place_name("old_name")
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "old_name")


@pytest.mark.asyncio
async def test_finalize_last_place_name_same_as_new(mock_sensor):
    """Test that finalize_last_place_name sets the last place name attribute when the last place name, current place name, and device tracker zone name are all the same."""

    def get_attr_side_effect(k):
        if k in (ATTR_LAST_PLACE_NAME, ATTR_PLACE_NAME, ATTR_DEVICETRACKER_ZONE_NAME):
            return "same"
        return None

    mock_sensor.get_attr.side_effect = get_attr_side_effect
    parser = OSMParser(mock_sensor)
    await parser.finalize_last_place_name("old_name")
    mock_sensor.set_attr.assert_any_call(ATTR_LAST_PLACE_NAME, "old_name")


@pytest.mark.asyncio
async def test_finalize_last_place_name_else(mock_sensor):
    """Test that finalize_last_place_name does not set the last place name attribute when the current and previous names do not meet update conditions."""

    def get_attr_side_effect(k):
        if k == ATTR_LAST_PLACE_NAME:
            return "last"
        if k == ATTR_PLACE_NAME:
            return "new"
        if k == ATTR_DEVICETRACKER_ZONE_NAME:
            return "zone"
        return None

    mock_sensor.get_attr.side_effect = get_attr_side_effect
    parser = OSMParser(mock_sensor)
    await parser.finalize_last_place_name("old_name")
    # Should not set_attr in this case
    assert (ATTR_LAST_PLACE_NAME, "old_name") not in [
        (call[0][0], call[0][1]) for call in mock_sensor.set_attr.call_args_list
    ]


@pytest.mark.asyncio
async def test_parse_osm_dict_full_flow(mock_sensor):
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
    mock_sensor.get_attr.side_effect = lambda k: osm_dict if k == ATTR_OSM_DICT else None
    parser = OSMParser(mock_sensor)
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
