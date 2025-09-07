"""Unit tests for AdvancedOptionsParser in custom_components.places.advanced_options."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import mock_sensor


@pytest.fixture
def sensor():
    """Shared sensor fixture returning a configured MockSensor instance."""
    return mock_sensor()


@pytest.fixture
def advanced_parser():
    """Factory fixture to create an AdvancedOptionsParser and its sensor.

    Returns (parser, sensor).
    """

    def _create(opts_str=None, attrs=None, in_zone=False):
        sensor = mock_sensor(attrs=attrs, in_zone=in_zone)
        parser = AdvancedOptionsParser(sensor, opts_str or "")
        return parser, sensor

    return _create


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
async def test_do_brackets_and_parens_count_match(input_str, expected, advanced_parser):
    """Return True when brackets and parens counts match, otherwise False."""
    parser, sensor = advanced_parser()
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,expected",
    [
        ("zone_name", "Home"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(key, expected, advanced_parser):
    """Return the expected option state for a basic key lookup."""
    attrs = {
        "devicetracker_zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "name": "Test",
    }
    parser, sensor = advanced_parser(attrs=attrs, in_zone=True)
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
async def test_get_option_state_incl_excl(incl, excl, expected, advanced_parser):
    """Respect inclusion/exclusion lists when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, sensor = advanced_parser(attrs=attrs, in_zone=True)
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
async def test_get_option_state_incl_attr_excl_attr(
    incl_attr, excl_attr, expected, advanced_parser
):
    """Apply attribute-based inclusion/exclusion filters when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, sensor = advanced_parser(attrs=attrs, in_zone=True)
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
async def test_get_option_state_title_case(key, expected, advanced_parser):
    """Return title-cased option values when appropriate."""
    attrs = {
        "devicetracker_zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    parser, sensor = advanced_parser(attrs=attrs)
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
    input_str, expected_attr, expected_lst, expected_incl, advanced_parser
):
    """Parse attribute parentheses into (attr, list, include_flag)."""
    parser, sensor = advanced_parser()
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
    parens_input,
    parens_expected_incl,
    parens_expected_excl,
    bracket_input,
    bracket_expected,
    advanced_parser,
):
    """Parse parens and bracketed options into their expected parts."""
    parser, sensor = advanced_parser()
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(parens_input)
    assert incl == parens_expected_incl
    assert excl == parens_expected_excl
    none_opt, next_opt = await parser.parse_bracket(bracket_input)
    assert none_opt == bracket_expected
    assert isinstance(next_opt, str)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_list,street_i,street_num_i,expected",
    [
        (["Home", "Restaurant"], None, None, "Home, Restaurant"),
        ([None, "Home", "", "Restaurant"], None, None, "Home, Restaurant"),
        (["Home", "123", "Main St"], 1, 1, "Home, 123, Main St"),
    ],
)
async def test_compile_state_variants(state_list, street_i, street_num_i, expected, sensor):
    """Compile state_list into the expected string across variants."""
    # Use shared sensor fixture and adjust state for this scenario
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = state_list
    if street_i is not None:
        parser._street_i = street_i
    if street_num_i is not None:
        parser._street_num_i = street_num_i
    result = await parser.compile_state()
    assert result == expected


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_paren_mismatch(sensor):
    """Return early on unmatched brackets without modifying state_list."""
    # Use shared sensor fixture
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren(sensor):
    """Process options that include both brackets and parentheses and call get_option_state."""
    attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor.attrs = attrs
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called = {}

    async def _side(opt, *a, **kw):
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = AsyncMock(side_effect=_side)
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string(sensor):
    """No-op when advanced options string is empty."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fn_name,input_val,expected_empty",
    [
        ("parse_bracket", "[unmatched", True),
        ("parse_parens", "(unmatched", True),
    ],
)
async def test_mismatched_special_chars_log_error(
    caplog, sensor, fn_name, input_val, expected_empty
):
    """Parametrized: unmatched bracket/paren inputs should log an error and return empty-ish results."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    caplog.set_level(logging.ERROR, logger="custom_components.places.advanced_options")
    fn = getattr(parser, fn_name)
    res = await fn(input_val)
    # Expect an error record was emitted
    assert any(r.levelname == "ERROR" for r in caplog.records)
    # Both functions return an 'empty' style result on mismatch; assert using simple checks
    if fn_name == "parse_bracket":
        none_opt, next_opt = res
        assert none_opt is None or none_opt == ""
    else:
        incl, excl, incl_attr, excl_attr, next_opt = res
        assert incl == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_not_none_calls_normal(sensor):
    """Process single term when curr_options is provided."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    called = {}

    async def fake_process_single_term(opt):
        called["single_term"] = opt

    parser.process_single_term = fake_process_single_term
    await parser.build_from_advanced_options("zone_name")
    assert called["single_term"] == "zone_name"


@pytest.mark.asyncio
async def test_build_from_advanced_options_processed_options(sensor, monkeypatch):
    """Return early and log error when curr_options already processed."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser._processed_options.add("zone_name")
    mock_log = MagicMock()
    monkeypatch.setattr(
        logging.getLogger("custom_components.places.advanced_options"),
        "error",
        mock_log,
        raising=False,
    )
    await parser.build_from_advanced_options("zone_name")
    mock_log.assert_called()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_bracket_or_paren(sensor):
    """Skip bracket/paren processing when none are present."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    # Assign AsyncMock stubs directly so they remain on parser for assertions
    parser.process_bracket_or_parens = AsyncMock()
    parser.process_only_commas = AsyncMock()
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_bracket_or_parens.assert_not_called()


@pytest.mark.asyncio
async def test_build_from_advanced_options_with_comma(sensor):
    """Delegate to process_only_commas when comma present in options."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    parser.process_only_commas = AsyncMock()
    await parser.build_from_advanced_options("zone_name,place_type")
    parser.process_only_commas.assert_awaited_once_with("zone_name,place_type")


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_comma(sensor):
    """Call process_single_term when options string has no comma."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_single_term.assert_awaited_once_with("zone_name")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_str,expected_none_opt,expected_next_opt",
    [
        ("option]", "option", ""),
        ("]", "", ""),
        ("[outer[inner]]", "outer[inner]", ""),
    ],
)
async def test_parse_bracket_variants(input_str, expected_none_opt, expected_next_opt, sensor):
    """Parse bracket inputs and return expected (none_opt, next_opt) pairs."""
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket(input_str)
    assert none_opt == expected_none_opt
    assert next_opt == expected_next_opt


@pytest.mark.asyncio
async def test_process_bracket_or_parens_comma_first_builds_states(sensor):
    """Process comma-separated options and append title-cased states."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor.attrs = attrs
    sensor._in_zone = True
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.build_from_advanced_options()
    # Title casing applied to place_type
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_bracket_fallback_when_primary_option_none(sensor):
    """Use bracket fallback when primary option yields None."""
    attrs = {"place_type": "work", "name": "Test"}
    sensor.attrs = attrs
    sensor._in_zone = False  # zone_name will be excluded (not in zone)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert parser.state_list == ["Work"]


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion(sensor):
    """Parenthesis filters can exclude primary option and fall back to bracket option."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor.attrs = attrs
    sensor._in_zone = True
    # Parenthesis after option (parenthesis-first branch relative to first special char): exclude 'home'
    parser = AdvancedOptionsParser(sensor, "zone_name(-,home)[place_type]")
    await parser.build_from_advanced_options()
    # zone_name excluded by paren filter, fallback processes place_type -> Restaurant
    assert parser.state_list == ["Restaurant"]


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_blank_causes_exclusion(sensor):
    """Return None when included attribute filters reference missing/blank attributes."""
    attrs = {"devicetracker_zone_name": "Home", "name": "Test"}  # place_type missing -> blank
    sensor.attrs = attrs
    sensor._in_zone = True
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_compile_state_space_when_street_indices_match(sensor):
    """Use a space separator when street indices align after increment."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["123", "Main St"]
    # Set indices so after increment _street_num_i becomes 0 and matches _street_i=0 for first element? Need both to match second element, so set before increment to 0 so becomes 1 then set _street_i=1
    parser._street_num_i = 0  # will increment to 1 in compile_state
    parser._street_i = 1
    result = await parser.compile_state()
    # Two items only; index 1 meets condition so space used
    assert result == "123 Main St"


@pytest.mark.asyncio
async def test_parse_parens_with_attribute_filters(sensor):
    """Populate incl_attr when attribute-specific filters are present in parens."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
