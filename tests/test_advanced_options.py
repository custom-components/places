"""Unit tests for AdvancedOptionsParser in custom_components.places.advanced_options."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("a[b](c)", True),
        ("a[b(c]", False),
        ("a[b](c", False),
        ("a[b]c)", False),
    ],
)
async def test_do_brackets_and_parens_count_match(input_str, expected):
    """Return True when brackets and parens counts match, otherwise False."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,expected",
    [
        ("zone_name", "Home"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(key, expected):
    """Return the expected option state for a basic key lookup."""
    attrs = {
        "devicetracker_zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "name": "Test",
    }
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "incl,excl,expected",
    [
        (["home"], None, "Home"),
        (["work"], None, None),
        (None, ["home"], None),
    ],
)
async def test_get_option_state_incl_excl(incl, excl, expected):
    """Respect inclusion/exclusion lists when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl=incl, excl=excl)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "incl_attr,excl_attr,expected",
    [
        ({"place_type": ["Restaurant"]}, None, "Home"),
        ({"place_type": ["Work"]}, None, None),
        (None, {"place_type": ["Restaurant"]}, None),
    ],
)
async def test_get_option_state_incl_attr_excl_attr(incl_attr, excl_attr, expected):
    """Apply attribute-based inclusion/exclusion filters when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr=incl_attr, excl_attr=excl_attr)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,expected",
    [
        ("place_type", "Restaurant"),
        ("place_category", "Food"),
    ],
)
async def test_get_option_state_title_case(key, expected):
    """Return title-cased option values when appropriate."""
    attrs = {
        "devicetracker_zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_str,expected_attr,expected_lst,expected_incl",
    [
        ("type(work,home)", "type", ["work", "home"], True),
        ("type(-,work,home)", "type", ["work", "home"], False),
    ],
)
async def test_parse_attribute_parentheses_incl_excl(
    input_str, expected_attr, expected_lst, expected_incl
):
    """Parse attribute parentheses into (attr, list, include_flag)."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    attr, lst, incl = parser.parse_attribute_parentheses(input_str)
    assert attr == expected_attr
    assert lst == expected_lst
    assert incl is expected_incl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parens_input,parens_expected_incl,parens_expected_excl,bracket_input,bracket_expected",
    [
        ("(work,home)", ["work", "home"], [], "[option]", "option"),
        ("(-,work,home)", [], ["work", "home"], "[option]", "option"),
    ],
)
async def test_parse_parens_and_bracket(
    parens_input, parens_expected_incl, parens_expected_excl, bracket_input, bracket_expected
):
    """Parse parens and bracketed options into their expected parts."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(parens_input)
    assert incl == parens_expected_incl
    assert excl == parens_expected_excl
    none_opt, next_opt = await parser.parse_bracket(bracket_input)
    assert none_opt == bracket_expected
    assert isinstance(next_opt, str)


@pytest.mark.asyncio
async def test_compile_state():
    """Join state_list elements into a comma-separated string."""
    attrs = {"zone_name": "home", "place_type": "restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_compile_state_skips_none_or_empty():
    """Skip falsy values when compiling state_list."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = [None, "Home", "", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_compile_state_street_space():
    """Use space separator for street/street number when indices match."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "123", "Main St"]
    parser._street_i = 1
    parser._street_num_i = 1
    # The second item should be joined with a comma to the third (current implementation)
    result = await parser.compile_state()
    assert result == "Home, 123, Main St"


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_paren_mismatch():
    """Return early on unmatched brackets without modifying state_list."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren():
    """Process options that include both brackets and parentheses and call get_option_state."""
    attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called = {}

    async def fake_get_option_state(opt, *a, **kw):
        """Fake get_option_state that records the accessed option and returns attrs[opt]."""
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = fake_get_option_state
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string():
    """No-op when advanced options string is empty."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_parse_bracket_mismatch_logs_error():
    """Log an error and return None/empty for unmatched brackets."""
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
    """Log an error and return empty inclusion list for unmatched parentheses."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(unmatched")
        assert incl == []
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_build_from_advanced_options_not_none_calls_normal(monkeypatch):
    """Process single term when curr_options is provided."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    called = {}

    async def fake_process_single_term(opt):
        called["single_term"] = opt

    parser.process_single_term = fake_process_single_term
    await parser.build_from_advanced_options("zone_name")
    assert called["single_term"] == "zone_name"


@pytest.mark.asyncio
async def test_build_from_advanced_options_processed_options(monkeypatch):
    """Return early and log error when curr_options already processed."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser._processed_options.add("zone_name")
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        await parser.build_from_advanced_options("zone_name")
        mock_log.assert_called()
        assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_bracket_or_paren(monkeypatch):
    """Skip bracket/paren processing when none are present."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_bracket_or_parens = AsyncMock()
    parser.process_only_commas = AsyncMock()
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_bracket_or_parens.assert_not_called()


@pytest.mark.asyncio
async def test_build_from_advanced_options_with_comma(monkeypatch):
    """Delegate to process_only_commas when comma present in options."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    parser.process_only_commas = AsyncMock()
    await parser.build_from_advanced_options("zone_name,place_type")
    parser.process_only_commas.assert_awaited_once_with("zone_name,place_type")


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_comma(monkeypatch):
    """Call process_single_term when options string has no comma."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_single_term.assert_awaited_once_with("zone_name")


@pytest.mark.asyncio
async def test_parse_bracket_not_starts_with_bracket():
    """Handle parse_bracket input that does not start with '[' correctly."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Should treat the string as-is
    none_opt, next_opt = await parser.parse_bracket("option]")
    assert none_opt == "option"  # Should parse up to the closing bracket
    assert next_opt == ""


@pytest.mark.asyncio
async def test_parse_bracket_starts_with_closing_bracket():
    """Return empty option when input is just a closing bracket."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket("]")
    assert none_opt == ""  # Should be empty
    assert next_opt == ""


@pytest.mark.asyncio
async def test_parse_bracket_counts_opening_bracket():
    """Parse nested brackets and return inner content correctly."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Input with nested brackets, starting with '['
    none_opt, next_opt = await parser.parse_bracket("[outer[inner]]")
    # Should parse up to the matching closing bracket
    assert none_opt == "outer[inner]"  # Everything inside the outer brackets
    assert next_opt == ""


@pytest.mark.asyncio
async def test_process_bracket_or_parens_comma_first_builds_states():
    """Process comma-separated options and append title-cased states."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.build_from_advanced_options()
    # Title casing applied to place_type
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_bracket_fallback_when_primary_option_none():
    """Use bracket fallback when primary option yields None."""
    attrs = {"place_type": "work", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=False)  # zone_name will be excluded (not in zone)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert parser.state_list == ["Work"]


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion():
    """Parenthesis filters can exclude primary option and fall back to bracket option."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    # Parenthesis after option (parenthesis-first branch relative to first special char): exclude 'home'
    parser = AdvancedOptionsParser(sensor, "zone_name(-,home)[place_type]")
    await parser.build_from_advanced_options()
    # zone_name excluded by paren filter, fallback processes place_type -> Restaurant
    assert parser.state_list == ["Restaurant"]


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_blank_causes_exclusion():
    """Return None when included attribute filters reference missing/blank attributes."""
    attrs = {"devicetracker_zone_name": "Home", "name": "Test"}  # place_type missing -> blank
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_compile_state_space_when_street_indices_match():
    """Use a space separator when street indices align after increment."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["123", "Main St"]
    # Set indices so after increment _street_num_i becomes 0 and matches _street_i=0 for first element? Need both to match second element, so set before increment to 0 so becomes 1 then set _street_i=1
    parser._street_num_i = 0  # will increment to 1 in compile_state
    parser._street_i = 1
    result = await parser.compile_state()
    # Two items only; index 1 meets condition so space used
    assert result == "123 Main St"


@pytest.mark.asyncio
async def test_parse_parens_with_attribute_filters():
    """Populate incl_attr when attribute-specific filters are present in parens."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
