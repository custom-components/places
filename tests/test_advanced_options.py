"""Unit tests for AdvancedOptionsParser in custom_components.places.advanced_options."""

from collections.abc import Mapping, Sequence
from typing import Protocol
from unittest.mock import AsyncMock

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor, mock_sensor

type Attrs = Mapping[str, object]
type FilterMap = Mapping[str, Sequence[str]]


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
    ("options", "attrs", "expected"),
    [
        (
            "zone_name,place_type",
            {"zone_name": "Home", "place_type": "Restaurant"},
            "Home, Restaurant",
        ),
        (
            "zone_name,missing,place_type",
            {"zone_name": "Home", "place_type": "Restaurant"},
            "Home, Restaurant",
        ),
        (
            "zone_name,street_number,street",
            {"zone_name": "Home", "street_number": "123", "street": "Main St"},
            "Home, 123 Main St",
        ),
        ("street_number,street", {"street_number": "123", "street": "Main St"}, "123 Main St"),
    ],
)
async def test_compile_state_variants(
    options: str,
    attrs: Attrs,
    expected: str,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Compile states produced from display expressions across variants.

    Args:
        options (str):
            Advanced display-options expression to parse.
        attrs (Attrs):
            Sensor attributes used to resolve the expression.
        expected (str):
            Expected compiled state.
        advanced_parser (AdvancedParserFactory):
            Factory fixture for an expression-driven parser and sensor.
    """
    parser, _sensor = advanced_parser(options, attrs, in_zone=True)
    await parser.build_from_advanced_options()
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
