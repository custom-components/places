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
        """Create the parser and sensor.

        Args:
            opts_str (str | None):
                Display-options expression parsed by the fixture.
            attrs (Attrs | None):
                Places attribute mapping used by the test.
            in_zone (bool):
                Whether the tracker is inside the selected zone.

        Returns:
            tuple[AdvancedOptionsParser, MockSensor]:
                Advanced options parser and the backing ``MockSensor``.
        """


@pytest.fixture
def advanced_parser() -> AdvancedParserFactory:
    """Factory fixture to create an AdvancedOptionsParser and its sensor.

    Returns (parser, sensor).

    Returns:
        AdvancedParserFactory:
            Factory that constructs advanced-option parsers for test inputs.
    """

    def _create(
        opts_str: str | None = None, attrs: Attrs | None = None, in_zone: bool = False
    ) -> tuple[AdvancedOptionsParser, MockSensor]:
        """Create an advanced-options parser backed by a configured mock sensor.

        Args:
            opts_str (str | None):
                Advanced display options string to parse.
            attrs (Attrs | None):
                Sensor attributes exposed to parser lookups.
            in_zone (bool):
                Whether the mock sensor should report itself in a zone.

        Returns:
            tuple[AdvancedOptionsParser, MockSensor]:
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
    """Assert bracket and parenthesis count matching for the supplied text.

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected (bool):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    parser, _sensor = advanced_parser()
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("osm_formatted_address", "123 Any Street"),
        ("zone_name", "Home"),
        ("province", "Virginia"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(
    key: str, expected: str | None, advanced_parser: AdvancedParserFactory
) -> None:
    """Return the expected option state for a basic key lookup.

    Args:
        key (str):
            Configuration or attribute key being accessed.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "formatted_address": "123 Any Street",
        "zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "state": "Virginia",
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
    """Respect inclusion/exclusion lists when resolving option state.

    Args:
        incl (list[str] | None):
            Option tokens included in the rendered state.
        excl (list[str] | None):
            Option tokens excluded from the rendered state.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {"zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
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
    """Apply attribute-based inclusion/exclusion filters when resolving option state.

    Args:
        incl_attr (FilterMap | None):
            Attributes included in the rendered state.
        excl_attr (FilterMap | None):
            Attributes excluded from the rendered state.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {"zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl_attr=incl_attr, excl_attr=excl_attr)
    assert out == expected


@pytest.mark.asyncio
async def test_get_option_state_numeric_values_are_stringified(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Handle numeric display values by normalizing them before string operations.

    Args:
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "latitude": 40.715,
        "longitude": -74.006,
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("latitude")
    assert out == "40.715"


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
    """Return title-cased option values when appropriate.

    Args:
        key (str):
            Configuration or attribute key being accessed.
        expected (str):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "zone_name": "home",
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
    """Parse attribute parentheses into (attr, list, include_flag).

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected_attr (str):
            Attribute name whose resulting content is asserted.
        expected_lst (list[str]):
            Parsed option list expected for this case.
        expected_incl (bool):
            Included option tokens expected after parsing.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
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
    """Parse parens and bracketed options into their expected parts.

    Args:
        parens_input (str):
            Parenthesized expression supplied to the parser.
        parens_expected_incl (list[str]):
            Tokens expected inside the parenthesized group.
        parens_expected_excl (list[str]):
            Tokens expected outside the parenthesized group.
        bracket_input (str):
            Bracketed expression supplied to the parser.
        bracket_expected (str):
            Tokens expected after bracket parsing.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
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
        (["123", "Main St"], 1, 0, "123 Main St"),
    ],
)
async def test_compile_state_variants(
    state_list: list[StateItem],
    street_i: int | None,
    street_num_i: int | None,
    expected: str,
    sensor: MockSensor,
) -> None:
    """Compile state_list into the expected string across variants.

    Args:
        state_list (list[StateItem]):
            Ordered state components to compile.
        street_i (int | None):
            Index of the street component in ``state_list``.
        street_num_i (int | None):
            Index of the street-number component in ``state_list``.
        expected (str):
            Expected result for this parametrized case.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
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
    """Return early on unmatched brackets without modifying state_list.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    # Use shared sensor fixture
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren(sensor: MockSensor) -> None:
    """Process options that include both brackets and parentheses and call get_option_state.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    attrs: dict[str, object] = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor.attrs = attrs
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called: dict[str, bool] = {}

    async def _side(opt: str, *args: object, **kwargs: object) -> object:
        """Record option lookups while returning values from the test attributes.

        Args:
            opt (str):
                Option name requested by the parser.
            args (object):
                Additional lookup arguments ignored by this test stub.
            kwargs (object):
                Additional lookup filters ignored by this test stub.

        Returns:
            object:
                Attribute value matching ``opt``, or ``None`` when absent.
        """
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = AsyncMock(side_effect=_side)
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_next_option_only_traverses_comma_prefixed_suffix(sensor: MockSensor) -> None:
    """Do not process malformed non-comma suffix text after a bracket option.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type]place_type")
    calls: list[str] = []

    async def _side(opt: str, *_args: object, **_kwargs: object) -> object:
        calls.append(opt)
        return "Home" if opt == "zone_name" else "Restaurant"

    parser.get_option_state = AsyncMock(side_effect=_side)
    await parser.build_from_advanced_options()
    assert calls == ["zone_name"]
    assert parser.state_list == ["Home"]


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string(sensor: MockSensor) -> None:
    """No-op when advanced options string is empty.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
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
    """Parametrized: unmatched bracket/paren inputs should log an error and return empty-ish results.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
        fn_name (str):
            Parser helper name included in the diagnostic message.
        input_val (str):
            Input consumed by the conversion helper.
    """
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
    """Process single term when curr_options is provided.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name")
    called: dict[str, str] = {}

    async def fake_process_single_term(opt: str) -> None:
        """Capture the single option term processed by the parser.

        Args:
            opt (str):
                Display option term passed to ``process_single_term``.
        """
        called["single_term"] = opt

    parser.process_single_term = fake_process_single_term  # type: ignore[assignment]
    await parser.build_from_advanced_options("zone_name")
    assert called["single_term"] == "zone_name"


@pytest.mark.asyncio
async def test_build_from_advanced_options_processed_options(
    sensor: MockSensor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return early and log error when curr_options already processed.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
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
    """Skip bracket/paren processing when none are present.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
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
    """Delegate to process_only_commas when comma present in options.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    parser.process_only_commas = AsyncMock()
    await parser.build_from_advanced_options("zone_name,place_type")
    parser.process_only_commas.assert_awaited_once_with("zone_name,place_type")


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_comma(sensor: MockSensor) -> None:
    """Call process_single_term when options string has no comma.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
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
    """Parse bracket inputs and return expected (none_opt, next_opt) pairs.

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected_none_opt (object):
            Option expected to produce no selection.
        expected_next_opt (object):
            Option expected after advancing the selection.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket(input_str)
    assert none_opt == expected_none_opt
    assert next_opt == expected_next_opt


@pytest.mark.asyncio
async def test_process_bracket_or_parens_comma_first_builds_states(sensor: MockSensor) -> None:
    """Process comma-separated options and append title-cased states.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    attrs: dict[str, object] = {
        "zone_name": "Home",
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
    """Use bracket fallback when primary option yields None.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    attrs: dict[str, object] = {"place_type": "work", "name": "Test"}
    sensor.attrs = attrs
    sensor._in_zone = False  # zone_name will be excluded (not in zone)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert parser.state_list == ["Work"]


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion(sensor: MockSensor) -> None:
    """Parenthesis filters can exclude primary option and fall back to bracket option.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    attrs: dict[str, object] = {
        "zone_name": "Home",
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
    """Return None when included attribute filters reference missing/blank attributes.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    attrs: dict[str, object] = {
        "zone_name": "Home",
        "name": "Test",
    }  # place_type missing -> blank
    sensor.attrs = attrs
    sensor._in_zone = True
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_parse_parens_with_attribute_filters(sensor: MockSensor) -> None:
    """Populate incl_attr when attribute-specific filters are present in parens.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, _next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
