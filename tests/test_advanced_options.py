"""Unit tests for AdvancedOptionsParser in custom_components.places.advanced_options."""

from collections.abc import Mapping, Sequence
import logging
from typing import Protocol
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor, mock_sensor

type Attrs = Mapping[str, object]
type FilterMap = Mapping[str, Sequence[str]]
type StateItem = str | None


class AdvancedParserFactory(Protocol):
    """Factory fixture for an advanced options parser and mock sensor."""

    def __call__(
        self, opts_str: str | None = None, attrs: Attrs | None = None, in_zone: bool = False
    ) -> tuple[AdvancedOptionsParser, MockSensor]:
        """Create the parser and sensor."""


@pytest.fixture
def sensor() -> MockSensor:
    """Shared sensor fixture returning a configured MockSensor instance."""
    return mock_sensor()


@pytest.fixture
def advanced_parser() -> AdvancedParserFactory:
    """Factory fixture to create an AdvancedOptionsParser and its sensor.

    Returns (parser, sensor).
    """

    def _create(
        opts_str: str | None = None, attrs: Attrs | None = None, in_zone: bool = False
    ) -> tuple[AdvancedOptionsParser, MockSensor]:
        """Create an advanced-options parser backed by a configured mock sensor.

        Args:
            opts_str: Advanced display options string to parse.
            attrs: Sensor attributes exposed to parser lookups.
            in_zone: Whether the mock sensor should report itself in a zone.

        Returns:
            Parser instance and the sensor backing it.
        """
        sensor = mock_sensor(attrs=attrs, in_zone=in_zone)
        parser = AdvancedOptionsParser(sensor, opts_str or "")
        return parser, sensor

    return _create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("a[b](c)", True),
        ("a[b(c]", False),
        ("a[b](c", False),
        ("a[b]c)", False),
    ],
)
async def test_do_brackets_and_parens_count_match(
    input_str: str, expected: bool, advanced_parser: AdvancedParserFactory
) -> None:
    """Return True when brackets and parens counts match, otherwise False."""
    parser, _sensor = advanced_parser()
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("zone_name", "Home"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(
    key: str, expected: str | None, advanced_parser: AdvancedParserFactory
) -> None:
    """Return the expected option state for a basic key lookup."""
    attrs = {
        "devicetracker_zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incl", "excl", "expected"),
    [
        (["home"], None, "Home"),
        (["work"], None, None),
        (None, ["home"], None),
    ],
)
async def test_get_option_state_incl_excl(
    incl: list[str] | None,
    excl: list[str] | None,
    expected: str | None,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Respect inclusion/exclusion lists when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl=incl, excl=excl)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incl_attr", "excl_attr", "expected"),
    [
        ({"place_type": ["Restaurant"]}, None, "Home"),
        ({"place_type": ["Work"]}, None, None),
        (None, {"place_type": ["Restaurant"]}, None),
    ],
)
async def test_get_option_state_incl_attr_excl_attr(
    incl_attr: FilterMap | None,
    excl_attr: FilterMap | None,
    expected: str | None,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Apply attribute-based inclusion/exclusion filters when resolving option state."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl_attr=incl_attr, excl_attr=excl_attr)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("place_type", "Restaurant"),
        ("place_category", "Food"),
    ],
)
async def test_get_option_state_title_case(
    key: str, expected: str, advanced_parser: AdvancedParserFactory
) -> None:
    """Return title-cased option values when appropriate."""
    attrs = {
        "devicetracker_zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs)
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected_attr", "expected_lst", "expected_incl"),
    [
        ("type(work,home)", "type", ["work", "home"], True),
        ("type(-,work,home)", "type", ["work", "home"], False),
    ],
)
async def test_parse_attribute_parentheses_incl_excl(
    input_str: str,
    expected_attr: str,
    expected_lst: list[str],
    expected_incl: bool,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Parse attribute parentheses into (attr, list, include_flag)."""
    parser, _sensor = advanced_parser()
    attr, lst, incl = parser.parse_attribute_parentheses(input_str)
    assert attr == expected_attr
    assert lst == expected_lst
    assert incl is expected_incl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "parens_input",
        "parens_expected_incl",
        "parens_expected_excl",
        "bracket_input",
        "bracket_expected",
    ),
    [
        ("(work,home)", ["work", "home"], [], "[option]", "option"),
        ("(-,work,home)", [], ["work", "home"], "[option]", "option"),
    ],
)
async def test_parse_parens_and_bracket(
    parens_input: str,
    parens_expected_incl: list[str],
    parens_expected_excl: list[str],
    bracket_input: str,
    bracket_expected: str,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Parse parens and bracketed options into their expected parts."""
    parser, _sensor = advanced_parser()
    incl, excl, _incl_attr, _excl_attr, next_opt = await parser.parse_parens(parens_input)
    assert incl == parens_expected_incl
    assert excl == parens_expected_excl
    none_opt, next_opt = await parser.parse_bracket(bracket_input)
    assert none_opt == bracket_expected
    assert isinstance(next_opt, str)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state_list", "street_i", "street_num_i", "expected"),
    [
        (["Home", "Restaurant"], None, None, "Home, Restaurant"),
        ([None, "Home", "", "Restaurant"], None, None, "Home, Restaurant"),
        (["Home", "123", "Main St"], 1, 1, "Home, 123, Main St"),
    ],
)
async def test_compile_state_variants(
    state_list: list[StateItem],
    street_i: int | None,
    street_num_i: int | None,
    expected: str,
    sensor: MockSensor,
) -> None:
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
async def test_build_from_advanced_options_bracket_paren_mismatch(sensor: MockSensor) -> None:
    """Return early on unmatched brackets without modifying state_list."""
    # Use shared sensor fixture
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren(sensor: MockSensor) -> None:
    """Process options that include both brackets and parentheses and call get_option_state."""
    attrs: dict[str, object] = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor.attrs = attrs
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called: dict[str, bool] = {}

    async def _side(opt: str, *args: object, **kwargs: object) -> object:
        """Record option lookups while returning values from the test attributes.

        Args:
            opt: Option name requested by the parser.
            *args: Additional lookup arguments ignored by this test stub.
            **kwargs: Additional lookup filters ignored by this test stub.

        Returns:
            Attribute value matching ``opt``, or ``None`` when absent.
        """
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = AsyncMock(side_effect=_side)
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string(sensor: MockSensor) -> None:
    """No-op when advanced options string is empty."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fn_name", "input_val"),
    [
        ("parse_bracket", "[unmatched"),
        ("parse_parens", "(unmatched"),
    ],
)
async def test_mismatched_special_chars_log_error(
    caplog: pytest.LogCaptureFixture,
    sensor: MockSensor,
    fn_name: str,
    input_val: str,
) -> None:
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
        none_opt, _next_opt = res
        assert none_opt is None or none_opt == ""
    else:
        incl, _excl, _incl_attr, _excl_attr, _next_opt = res
        assert incl == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_not_none_calls_normal(sensor: MockSensor) -> None:
    """Process single term when curr_options is provided."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    called: dict[str, str] = {}

    async def fake_process_single_term(opt: str) -> None:
        """Capture the single option term processed by the parser.

        Args:
            opt: Display option term passed to ``process_single_term``.
        """
        called["single_term"] = opt

    parser.process_single_term = fake_process_single_term  # type: ignore[assignment]
    await parser.build_from_advanced_options("zone_name")
    assert called["single_term"] == "zone_name"


@pytest.mark.asyncio
async def test_build_from_advanced_options_processed_options(
    sensor: MockSensor, monkeypatch: pytest.MonkeyPatch
) -> None:
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
async def test_build_from_advanced_options_no_bracket_or_paren(sensor: MockSensor) -> None:
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
async def test_build_from_advanced_options_with_comma(sensor: MockSensor) -> None:
    """Delegate to process_only_commas when comma present in options."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    parser.process_only_commas = AsyncMock()
    await parser.build_from_advanced_options("zone_name,place_type")
    parser.process_only_commas.assert_awaited_once_with("zone_name,place_type")


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_comma(sensor: MockSensor) -> None:
    """Call process_single_term when options string has no comma."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_single_term.assert_awaited_once_with("zone_name")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected_none_opt", "expected_next_opt"),
    [
        ("option]", "option", ""),
        ("]", "", ""),
        ("[outer[inner]]", "outer[inner]", ""),
    ],
)
async def test_parse_bracket_variants(
    input_str: str, expected_none_opt: object, expected_next_opt: object, sensor: MockSensor
) -> None:
    """Parse bracket inputs and return expected (none_opt, next_opt) pairs."""
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket(input_str)
    assert none_opt == expected_none_opt
    assert next_opt == expected_next_opt


@pytest.mark.asyncio
async def test_process_bracket_or_parens_comma_first_builds_states(sensor: MockSensor) -> None:
    """Process comma-separated options and append title-cased states."""
    attrs: dict[str, object] = {
        "devicetracker_zone_name": "Home",
        "place_type": "restaurant",
        "name": "Test",
    }
    sensor.attrs = attrs
    sensor._in_zone = True
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.build_from_advanced_options()
    # Title casing applied to place_type
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_bracket_fallback_when_primary_option_none(sensor: MockSensor) -> None:
    """Use bracket fallback when primary option yields None."""
    attrs: dict[str, object] = {"place_type": "work", "name": "Test"}
    sensor.attrs = attrs
    sensor._in_zone = False  # zone_name will be excluded (not in zone)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert parser.state_list == ["Work"]


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion(sensor: MockSensor) -> None:
    """Parenthesis filters can exclude primary option and fall back to bracket option."""
    attrs: dict[str, object] = {
        "devicetracker_zone_name": "Home",
        "place_type": "restaurant",
        "name": "Test",
    }
    sensor.attrs = attrs
    sensor._in_zone = True
    # Parenthesis after option (parenthesis-first branch relative to first special char): exclude 'home'
    parser = AdvancedOptionsParser(sensor, "zone_name(-,home)[place_type]")
    await parser.build_from_advanced_options()
    # zone_name excluded by paren filter, fallback processes place_type -> Restaurant
    assert parser.state_list == ["Restaurant"]


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_blank_causes_exclusion(sensor: MockSensor) -> None:
    """Return None when included attribute filters reference missing/blank attributes."""
    attrs: dict[str, object] = {
        "devicetracker_zone_name": "Home",
        "name": "Test",
    }  # place_type missing -> blank
    sensor.attrs = attrs
    sensor._in_zone = True
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_compile_state_space_when_street_indices_match(sensor: MockSensor) -> None:
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
async def test_parse_parens_with_attribute_filters(sensor: MockSensor) -> None:
    """Populate incl_attr when attribute-specific filters are present in parens."""
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, _next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
