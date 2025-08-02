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
    attrs = {"street": "Main St", "street_number": "123", "name": "Test"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    await parser.get_option_state("street")
    await parser.get_option_state("street_number")
    assert parser._street_i == 0
    assert parser._street_num_i == 1


@pytest.mark.asyncio
async def test_process_only_commas():
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.process_only_commas("zone_name,place_type")
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_process_single_term():
    attrs = {"devicetracker_zone_name": "Home", "name": "Test"}
    sensor = MockSensor(attrs, blank_attrs=set(), in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name")
    await parser.process_single_term("zone_name")
    assert parser.state_list == ["Home"]


@pytest.mark.asyncio
async def test_parse_attribute_parentheses_incl_excl():
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
    attrs = {"zone_name": "home", "place_type": "restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_paren_mismatch(monkeypatch):
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren(monkeypatch):
    # Should process bracket and paren logic
    attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called = {}

    async def fake_get_option_state(opt, *a, **kw):
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = fake_get_option_state
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string():
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_parse_bracket_mismatch_logs_error():
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
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(unmatched")
        assert incl == []
        mock_log.assert_called()
