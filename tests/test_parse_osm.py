"""Unit tests for the OSMParser class in custom_components.places.parse_osm."""

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
    CONF_LANGUAGE,
    PLACE_NAME_DUPLICATE_LIST,
)
from custom_components.places.parse_osm import OSMParser

from .conftest import mock_sensor, stubbed_parser


@pytest.fixture
def sensor():
    """Shared sensor fixture returning a configured MockSensor instance."""
    return mock_sensor()


@pytest.fixture
def osm_parser():
    """Factory fixture to create an OSMParser and its sensor.

    Returns (parser, sensor).
    """

    def _create(attrs=None):
        sensor = mock_sensor(attrs=attrs)
        parser = OSMParser(sensor)
        return parser, sensor

    return _create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "osm_dict,expected_attr,expected_value,should_call",
    [
        ({"licence": "OSM License"}, ATTR_ATTRIBUTION, "OSM License", True),
        ({}, ATTR_ATTRIBUTION, None, False),
    ],
)
async def test_set_attribution(osm_parser, osm_dict, expected_attr, expected_value, should_call):
    """Ensure set_attribution sets ATTR_ATTRIBUTION only when the OSM 'licence' key exists."""
    parser, sensor = osm_parser()
    await parser.set_attribution(osm_dict)
    if should_call:
        assert sensor.attrs[expected_attr] == expected_value
    else:
        # No set_attr calls should have been recorded
        sensor._set_attr_mock.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "osm_dict,get_attr_value,expect_clear,expected_set_calls",
    [
        (
            {"type": "road", "address": {"road": "Main St"}},
            "road",
            False,
            [(ATTR_PLACE_TYPE, "road"), (ATTR_PLACE_NAME, "Main St")],
        ),
        (
            {"type": "yes", "addresstype": "highway"},
            "yes",
            False,
            [(ATTR_PLACE_TYPE, "highway")],
        ),
        (
            {"type": "yes"},
            "yes",
            True,
            [],
        ),
    ],
)
async def test_parse_type_variants(
    osm_parser, osm_dict, get_attr_value, expect_clear, expected_set_calls
):
    """Parametrized variants for parse_type covering normal types and 'yes' addresstype behavior."""
    # Create sensor pre-populated with any existing place_type value
    parser, sensor = osm_parser(
        attrs={ATTR_PLACE_TYPE: get_attr_value} if get_attr_value is not None else None
    )
    await parser.parse_type(osm_dict)
    if expect_clear:
        sensor._clear_attr_mock.assert_called_once_with(ATTR_PLACE_TYPE)
    else:
        for attr, val in expected_set_calls:
            sensor._set_attr_mock.assert_any_call(attr, val)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,address,expect_calls",
    [
        ("retail", {"retail": "Shop"}, True),
        (None, None, False),
    ],
)
async def test_parse_category_variants(osm_parser, category, address, expect_calls):
    """Parametrized: parse_category should set category and place name when present; otherwise do nothing."""
    osm_dict = {}
    if category is not None:
        osm_dict["category"] = category
        if address is not None:
            osm_dict["address"] = address
    parser, sensor = osm_parser()
    await parser.parse_category(osm_dict)
    if expect_calls:
        assert sensor.attrs[ATTR_PLACE_CATEGORY] == category
        # The place name is taken from the address mapping value
        # Use next(iter(address.values())) to get the sample value used in tests
        assert sensor.attrs[ATTR_PLACE_NAME] == next(iter(address.values()))
    else:
        sensor._set_attr_mock.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "namedetails, language_pref, is_lang_blank, expected_calls",
    [
        ({"name": "Park"}, None, False, ["Park"]),
        ({"name": "Park", "name:en": "English Park"}, "en", False, ["Park", "English Park"]),
        ({}, None, False, []),
        ({"name": "MainName"}, None, True, ["MainName"]),
        (
            {"name": "MainName", "name:en": "EnglishName"},
            "en",
            False,
            ["MainName", "EnglishName"],
        ),
        (
            {"name": "MainName", "name:en": "EnglishName", "name:fr": "FrenchName"},
            "fr,en",
            False,
            ["MainName", "FrenchName"],
        ),
        ({"name": "MainName", "name:en": "EnglishName"}, "de", False, ["MainName"]),
    ],
)
async def test_parse_namedetails_variants(
    osm_parser,
    namedetails,
    language_pref,
    is_lang_blank,
    expected_calls,
):
    """Parametrized tests for parse_namedetails covering language preferences and fallbacks.

    Verifies that the base name is always set when present and that language-specific names are applied
    when the configured language preference matches a namedetails key.
    """

    # Create a sensor with language preference or blankness configured via attrs/blank_attrs
    if is_lang_blank:
        # Make the CONF_LANGUAGE attribute considered blank
        sensor = mock_sensor(
            attrs={CONF_LANGUAGE: language_pref} if language_pref is not None else None,
            blank_attrs={CONF_LANGUAGE},
        )
        parser = OSMParser(sensor)
    else:
        parser, sensor = osm_parser(
            attrs={CONF_LANGUAGE: language_pref} if language_pref is not None else None
        )

    osm_dict = {"namedetails": namedetails} if namedetails else {}
    await parser.parse_namedetails(osm_dict)

    # Collect all ATTR_PLACE_NAME calls recorded via the internal mock
    calls = [c for c in sensor._set_attr_mock.call_args_list if c[0][0] == ATTR_PLACE_NAME]
    values = [c[0][1] for c in calls]

    if not expected_calls:
        assert values == []
    else:
        # The base name should be the first call when present
        if "name" in namedetails:
            assert values[0] == namedetails.get("name")
        # If a language-specific override is expected, it should appear later in the calls
        for expected in expected_calls[1:]:
            assert expected in values


@pytest.mark.asyncio
async def test_parse_address_calls_submethods(osm_parser):
    """parse_address should delegate to set_address_details, set_city_details and set_region_details when an address exists."""
    osm_dict = {"address": {"house_number": "123", "road": "Main"}}
    parser, sensor = osm_parser()
    with stubbed_parser(
        parser, [("set_address_details", {}), ("set_city_details", {}), ("set_region_details", {})]
    ) as mocks:
        await parser.parse_address(osm_dict)
    mocks["set_address_details"].assert_awaited_once_with(osm_dict["address"])
    mocks["set_city_details"].assert_awaited_once_with(osm_dict["address"])
    mocks["set_region_details"].assert_awaited_once_with(osm_dict["address"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,expected_attr,expected_value",
    [
        ({"house_number": "123", "road": "Main"}, ATTR_STREET_NUMBER, "123"),
        ({"house_number": "123", "road": "Main"}, ATTR_STREET, "Main"),
    ],
)
async def test_set_address_details_sets_attrs(osm_parser, address, expected_attr, expected_value):
    """Parametrized: set_address_details should set expected street attributes from address dict."""
    parser, sensor = osm_parser()
    await parser.set_address_details(address)
    assert sensor.attrs[expected_attr] == expected_value


@pytest.mark.asyncio
async def test_set_address_details_retail_logic(osm_parser):
    """If place_name is blank and address contains retail, set place_name to the retail value."""
    address = {"retail": "Shop"}
    # Use a sensor that reports ATTR_PLACE_NAME as blank and has the OSM dict populated
    sensor = mock_sensor(
        attrs={ATTR_OSM_DICT: {"address": {"retail": "Shop"}}}, blank_attrs={ATTR_PLACE_NAME}
    )
    parser = OSMParser(sensor)
    await parser.set_address_details(address)
    assert sensor.attrs[ATTR_PLACE_NAME] == "Shop"


@pytest.mark.asyncio
async def test_set_city_details_sets_city_clean(osm_parser):
    """set_city_details should compute a cleaned city value and set ATTR_CITY_CLEAN accordingly."""
    address = {"city": "City of Springfield"}
    parser, sensor = osm_parser()
    await parser.set_city_details(address)
    assert ATTR_CITY_CLEAN in sensor.attrs
    assert "Springfield" in sensor.attrs[ATTR_CITY_CLEAN]


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
async def test_set_city_details_variants(osm_parser, address, expected_city, expected_city_clean):
    """Test that set_city_details sets the correct city and cleaned city attributes for various address formats.

    Args:
        address: The address dictionary containing city, town, village, or hamlet information.
        expected_city: The expected value for the city attribute.
        expected_city_clean: The expected value for the cleaned city attribute.

    """
    parser, sensor = osm_parser()
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
async def test_set_city_details_postal_town(osm_parser, address, expected_attr, expected_value):
    """Test that set_city_details sets the correct city attribute for postal towns and villages.

    Args:
        address: The address dictionary containing town or village information.
        expected_attr: The expected attribute to be set (e.g., ATTR_CITY).
        expected_value: The expected value to be set for the attribute.

    """

    parser, sensor = osm_parser()
    await parser.set_city_details(address)
    assert sensor.attrs[expected_attr] == expected_value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address,expected_attr,expected_value",
    [
        ({"neighbourhood": "Downtown"}, ATTR_PLACE_NEIGHBOURHOOD, "Downtown"),
        ({"suburb": "Westside"}, ATTR_POSTAL_TOWN, "Westside"),
        ({"quarter": "East End"}, ATTR_PLACE_NEIGHBOURHOOD, "East End"),
    ],
)
async def test_set_city_details_neighbourhood(osm_parser, address, expected_attr, expected_value):
    """Test that set_city_details sets the correct neighbourhood or postal town attributes for various address formats.

    Args:
        address: The address dictionary containing neighbourhood, suburb, or quarter information.
        expected_attr: The expected attribute to be set (e.g., ATTR_PLACE_NEIGHBOURHOOD, ATTR_POSTAL_TOWN).
        expected_value: The expected value to be set for the attribute.

    """

    parser, sensor = osm_parser()
    await parser.set_city_details(address)
    assert sensor.attrs[expected_attr] == expected_value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_attr,expected_value",
    [
        (ATTR_REGION, "CA"),
        (ATTR_STATE_ABBR, "CA"),
        (ATTR_COUNTY, "Orange"),
        (ATTR_COUNTRY, "USA"),
        (ATTR_COUNTRY_CODE, "US"),
        (ATTR_POSTAL_CODE, "90210"),
    ],
)
async def test_set_region_details_sets_attrs(osm_parser, expected_attr, expected_value):
    """Parametrized check that set_region_details sets expected regional attributes."""
    address = {
        "state": "CA",
        "ISO3166-2-lvl4": "US-CA",
        "county": "Orange",
        "country": "USA",
        "country_code": "us",
        "postcode": "90210",
    }
    parser, sensor = osm_parser(attrs={ATTR_OSM_DICT: {"address": {"postcode": "90210"}}})
    await parser.set_region_details(address)
    assert sensor.attrs[expected_attr] == expected_value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_attr,expected_value",
    [
        (ATTR_FORMATTED_ADDRESS, "123 Main St"),
        (ATTR_OSM_ID, "123456"),
        (ATTR_OSM_TYPE, "way"),
        (ATTR_STREET_REF, "A1"),
    ],
)
async def test_parse_miscellaneous_sets_attrs(osm_parser, expected_attr, expected_value):
    """Parametrized check that parse_miscellaneous sets expected attributes from OSM data."""
    osm_dict = {
        "display_name": "123 Main St",
        "osm_id": 123456,
        "osm_type": "way",
        "namedetails": {"ref": "A1;B2"},
        "category": "highway",
    }
    parser, sensor = osm_parser(
        attrs={
            ATTR_PLACE_CATEGORY: "highway",
            ATTR_OSM_DICT: {"osm_id": 123456},
        }
    )
    await parser.parse_miscellaneous(osm_dict)
    # verify attribute was set in internal attrs or recorded via internal mock
    assert sensor.attrs.get(
        expected_attr
    ) == expected_value or sensor._set_attr_mock.assert_any_call(expected_attr, expected_value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,current_name,is_blank,existing_get_attr,should_set",
    [
        (
            "unique",
            "UniqueName",
            lambda k: k != ATTR_PLACE_NAME,
            lambda k: "UniqueName" if k == ATTR_PLACE_NAME else None,
            True,
        ),
        ("duplicate", "DupeName", lambda k: False, lambda k: "DupeName", False),
    ],
)
async def test_set_place_name_no_dupe_param(
    osm_parser, case, current_name, is_blank, existing_get_attr, should_set
):
    """Parametrized test for set_place_name_no_dupe covering unique and duplicate name cases."""
    # Build sensor state rather than stubbing methods
    if case == "unique":
        # Ensure duplicate-check attributes are considered blank so no dupes are detected
        sensor = mock_sensor(
            attrs={ATTR_PLACE_NAME: current_name}, blank_attrs=set(PLACE_NAME_DUPLICATE_LIST)
        )
    else:
        # Place the duplicate value into one of the duplicate attributes so it will be detected
        sensor = mock_sensor(attrs={ATTR_PLACE_NAME: current_name, ATTR_STREET: current_name})
    parser = OSMParser(sensor)
    await parser.set_place_name_no_dupe()
    if should_set:
        sensor._set_attr_mock.assert_any_call(ATTR_PLACE_NAME_NO_DUPE, current_name)
    else:
        sensor._set_attr_mock.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,existing_attrs,should_set",
    [
        ("initial_update", {ATTR_INITIAL_UPDATE: True}, True),
        (
            "same_names",
            {
                ATTR_LAST_PLACE_NAME: "same",
                ATTR_PLACE_NAME: "same",
                ATTR_DEVICETRACKER_ZONE_NAME: "same",
            },
            True,
        ),
        (
            "else",
            {
                ATTR_LAST_PLACE_NAME: "last",
                ATTR_PLACE_NAME: "new",
                ATTR_DEVICETRACKER_ZONE_NAME: "zone",
            },
            False,
        ),
    ],
)
async def test_finalize_last_place_name_variants(osm_parser, case, existing_attrs, should_set):
    """Parametrized finalize_last_place_name covering initial update, identical names, and else-case where it should not set."""

    def get_attr_side_effect(k):
        return existing_attrs.get(k)

    parser, sensor = osm_parser(attrs=existing_attrs)
    await parser.finalize_last_place_name("old_name")
    if should_set:
        sensor._set_attr_mock.assert_any_call(ATTR_LAST_PLACE_NAME, "old_name")
    else:
        # ensure no matching set_attr call was recorded
        assert not any(
            (c[0][0] == ATTR_LAST_PLACE_NAME and c[0][1] == "old_name")
            for c in sensor._set_attr_mock.call_args_list
        )


@pytest.mark.asyncio
async def test_parse_osm_dict_full_flow(osm_parser):
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
    parser, sensor = osm_parser(attrs={ATTR_OSM_DICT: osm_dict})
    with stubbed_parser(
        parser,
        [
            ("set_attribution", {}),
            ("parse_type", {}),
            ("parse_category", {}),
            ("parse_namedetails", {}),
            ("parse_address", {}),
            ("parse_miscellaneous", {}),
            ("set_place_name_no_dupe", {}),
        ],
    ) as mocks:
        await parser.parse_osm_dict()
    mocks["set_attribution"].assert_awaited_once_with(osm_dict)
    mocks["parse_type"].assert_awaited_once_with(osm_dict)
    mocks["parse_category"].assert_awaited_once_with(osm_dict)
    mocks["parse_namedetails"].assert_awaited_once_with(osm_dict)
    mocks["parse_address"].assert_awaited_once_with(osm_dict)
    mocks["parse_miscellaneous"].assert_awaited_once_with(osm_dict)
    mocks["set_place_name_no_dupe"].assert_awaited_once()
