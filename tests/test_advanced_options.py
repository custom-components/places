import logging
from unittest.mock import patch

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor


@pytest.mark.asyncio
async def test_do_brackets_and_parens_count_match():
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    assert await parser.do_brackets_and_parens_count_match("a[b](c)") is True
    assert await parser.do_brackets_and_parens_count_match("a[b(c]") is False
    assert await parser.do_brackets_and_parens_count_match("a[b](c") is False
    assert await parser.do_brackets_and_parens_count_match("a[b]c)") is False


@pytest.mark.asyncio
async def test_get_option_state_basic():
    # Use mapped keys from DISPLAY_OPTIONS_MAP
    """Test that `get_option_state` retrieves the correct sensor attribute value for a given key and returns None for missing keys."""
    attrs = {
        "devicetracker_zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "name": "Test",
    }
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name")
    assert out == "Home"
    out = await parser.get_option_state("missing")
    assert out is None


@pytest.mark.asyncio
async def test_get_option_state_incl_excl():
    """Test that get_option_state correctly applies inclusion and exclusion filters to sensor attributes.

    Verifies that the method returns the attribute value when it matches the inclusion list, returns None when excluded, and handles non-matching inclusion values appropriately.
    """
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl=["home"])
    assert out == "Home"
    out = await parser.get_option_state("zone_name", incl=["work"])
    assert out is None
    out = await parser.get_option_state("zone_name", excl=["home"])
    assert out is None


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_excl_attr():
    """Test that get_option_state correctly applies inclusion and exclusion filters based on sensor attribute values.

    Verifies that the method returns the expected value when the sensor's attributes match the inclusion filter, returns None when they do not match, and returns None when excluded by the exclusion filter.
    """
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["Restaurant"]})
    assert out == "Home"
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["Work"]})
    assert out is None
    out = await parser.get_option_state("zone_name", excl_attr={"place_type": ["Restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_get_option_state_title_case():
    """Test that get_option_state returns attribute values in title case for specific keys."""
    attrs = {
        "devicetracker_zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("place_type")
    assert out == "Restaurant"
    out = await parser.get_option_state("place_category")
    assert out == "Food"


@pytest.mark.asyncio
async def test_get_option_state_street_indices():
    """Test that retrieving 'street' and 'street_number' options sets the corresponding index attributes in the parser."""
    attrs = {"street": "Main St", "street_number": "123", "name": "Test"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    await parser.get_option_state("street")
    await parser.get_option_state("street_number")
    assert parser._street_i == 0
    assert parser._street_num_i == 1


@pytest.mark.asyncio
async def test_process_only_commas():
    """Test that `process_only_commas` correctly parses a comma-separated string of option keys and populates `state_list` with the corresponding sensor attribute values."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.process_only_commas("zone_name,place_type")
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_process_single_term():
    """Test that `process_single_term` correctly processes a single option term and updates the parser's state list with the expected sensor attribute value."""
    attrs = {"devicetracker_zone_name": "Home", "name": "Test"}
    sensor = MockSensor(attrs, blank_attrs=set(), in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name")
    await parser.process_single_term("zone_name")
    assert parser.state_list == ["Home"]


@pytest.mark.asyncio
async def test_parse_attribute_parentheses_incl_excl():
    """Test that parse_attribute_parentheses correctly parses attribute strings with parentheses, distinguishing between inclusion and exclusion lists.

    Asserts that the method returns the expected attribute name, list of values, and inclusion flag for both inclusion and exclusion cases.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    attr, lst, incl = parser.parse_attribute_parentheses("type(work,home)")
    assert attr == "type"
    assert lst == ["work", "home"]
    assert incl is True
    attr, lst, incl = parser.parse_attribute_parentheses("type(-,work,home)")
    assert attr == "type"
    assert lst == ["work", "home"]
    assert incl is False


@pytest.mark.asyncio
async def test_parse_parens_and_bracket():
    """Test that `parse_parens` correctly parses inclusion and exclusion lists from parentheses, and `parse_bracket` extracts options from brackets in the advanced options parser.

    Asserts that inclusion and exclusion lists are parsed as expected and that bracketed options are extracted as strings.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(work,home)")
    assert incl == ["work", "home"]
    assert excl == []
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(-,work,home)")
    assert incl == []
    assert excl == ["work", "home"]
    none_opt, next_opt = await parser.parse_bracket("[option]")
    assert none_opt == "option"
    assert isinstance(next_opt, str)


@pytest.mark.asyncio
async def test_compile_state():
    """Test that `compile_state` joins the `state_list` into a comma-separated string.

    Asserts that the resulting string correctly concatenates the elements of `state_list` with a comma and space.
    """
    attrs = {"zone_name": "home", "place_type": "restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_paren_mismatch(monkeypatch):
    """Test that build_from_advanced_options returns early without error when given unmatched brackets, leaving state_list unchanged."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren(monkeypatch):
    # Should process bracket and paren logic
    """Tests that `build_from_advanced_options` correctly processes option strings containing both brackets and parentheses, ensuring that `get_option_state` is called for each parsed option."""
    attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called = {}

    async def fake_get_option_state(opt, *a, **kw):
        """Simulates retrieval of an option state by recording the accessed option and returning its corresponding attribute value.

        Parameters:
            opt: The option key to retrieve.

        Returns:
            The value associated with the option key from the attrs dictionary, or None if not found.

        """
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = fake_get_option_state
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string():
    """Test that building from an empty advanced options string leaves the parser's state list empty."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_parse_bracket_mismatch_logs_error():
    """Test that parse_bracket logs an error when given an unmatched bracket input.

    Asserts that the logger's error method is called and the returned option is None or empty.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        none_opt, next_opt = await parser.parse_bracket("[unmatched")
        assert none_opt is None or none_opt == ""
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_parse_parens_mismatch_logs_error():
    """Test that parse_parens logs an error when given unmatched parentheses input.

    Asserts that the inclusion list is empty and that an error is logged.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(unmatched")
        assert incl == []
        mock_log.assert_called()
