"""Unit tests for the BasicOptionsParser class in the places custom component."""

from collections.abc import Mapping, Sequence
from typing import Protocol

import pytest

from custom_components.places.basic_options import BasicOptionsParser
from custom_components.places.const import ATTR_PLACE_NAME
from tests.conftest import MockSensor, mock_sensor

type Attrs = Mapping[str, object]


class BasicParserFactory(Protocol):
    """Factory fixture for a parser and backing mock sensor."""

    def __call__(
        self,
        attrs: Attrs | None = None,
        options: Sequence[str] | None = None,
        display_options_list: Sequence[str] | None = None,
        in_zone: bool = False,
    ) -> tuple[BasicOptionsParser, MockSensor]:
        """Create the parser and sensor."""


@pytest.fixture
def basic_parser() -> BasicParserFactory:
    """Factory fixture to create a BasicOptionsParser and its backing sensor.

    Returns (parser, sensor).
    """

    def _create(
        attrs: Attrs | None = None,
        options: Sequence[str] | None = None,
        display_options_list: Sequence[str] | None = None,
        in_zone: bool = False,
    ) -> tuple[BasicOptionsParser, MockSensor]:
        """Create a basic-options parser backed by a configured mock sensor.

        Args:
            attrs: Sensor attributes exposed to parser lookups.
            options: Basic display options to pass into the parser.
            display_options_list: Raw display-options list exposed by the mock
                sensor.
            in_zone: Whether the mock sensor should report itself in a zone.

        Returns:
            Parser instance and the sensor backing it.
        """
        sensor = mock_sensor(
            attrs=attrs, display_options_list=display_options_list, in_zone=in_zone
        )
        parser = BasicOptionsParser(sensor, attrs or {}, options or [])
        return parser, sensor

    return _create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attrs", "in_zone", "options", "expected_contains", "expected_eq"),
    [
        (
            {},
            False,
            ["driving", "zone_name", "zone", "place"],
            [],
            None,
        ),
        (
            {
                "driving": "Driving",
                "zone_name": "Home",
                "place_name": "Park",
                "neighborhood": "Downtown",
                "street": "Main St",
                "city": "Springfield",
            },
            False,
            ["driving", "zone_name", "place", "street", "city"],
            ["Driving", "Home", "Park", "Downtown", "Main St", "Springfield"],
            None,
        ),
        (
            {"zone_name": "Work"},
            True,
            ["zone_name"],
            ["Work"],
            None,
        ),
    ],
)
async def test_build_display_scenarios(
    attrs: Attrs,
    in_zone: bool,
    options: Sequence[str],
    expected_contains: Sequence[str],
    expected_eq: str | None,
    sensor: MockSensor,
) -> None:
    """Parametrized scenarios for BasicOptionsParser.build_display covering blank, populated, reorder, and in-zone cases."""
    # Mutate shared sensor fixture for this scenario
    sensor.attrs = dict(attrs or {})
    sensor._in_zone = in_zone
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_display()
    if expected_eq is not None:
        assert result == expected_eq
    else:
        for substr in expected_contains:
            assert substr in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "attrs", "in_zone", "options", "display_list", "expected_contains", "expected_eq"),
    [
        (
            "place_name",
            {ATTR_PLACE_NAME: "Central Park"},
            False,
            ["place"],
            ["driving"],
            ["Central Park"],
            None,
        ),
        (
            "type_category",
            {
                "place_type": "restaurant",
                "place_category": "food",
                "street": "Elm St",
                "city": "Metropolis",
                "place_name": "",
            },
            False,
            ["place"],
            None,
            ["Elm St", "Metropolis"],
            None,
        ),
        (
            "in_zone",
            {"zone_name": "Home"},
            True,
            ["zone_name"],
            None,
            [],
            "Home",
        ),
    ],
)
async def test_build_formatted_place_variants(
    scenario: str,
    attrs: Attrs,
    in_zone: bool,
    options: Sequence[str],
    display_list: Sequence[str] | None,
    expected_contains: Sequence[str],
    expected_eq: str | None,
    sensor: MockSensor,
) -> None:
    """Parametrized scenarios for BasicOptionsParser.build_formatted_place."""
    sensor.attrs = dict(attrs or {})
    sensor._in_zone = in_zone
    sensor.display_options_list = display_list or []
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_formatted_place()
    if expected_eq is not None:
        assert result == expected_eq
        return
    # Special-case: type_category accepts either Type or Category wording
    if scenario == "type_category":
        assert ("Restaurant" in result) or ("Food" in result)
    for substr in expected_contains:
        assert substr in result


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"place_type": "restaurant", "place_category": "food"}, "Restaurant"),
        ({"place_type": "unclassified", "place_category": "food"}, "Food"),
    ],
)
def test_add_type_or_category(
    attrs: Attrs, expected: str, basic_parser: BasicParserFactory
) -> None:
    """Test that `add_type_or_category` adds the correct capitalized type or category to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr: list[str] = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"street": "Main St", "street_number": ""}, "Main St"),
        ({"street": "Main St", "street_number": "123"}, "123 Main St"),
    ],
)
def test_add_street_info(attrs: Attrs, expected: str, basic_parser: BasicParserFactory) -> None:
    """Test that `add_street_info` appends the correct street info to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr: list[str] = []
    parser.add_street_info(arr, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        (
            {
                "place_category": "highway",
                "place_type": "motorway",
                "street": "",
                "route_number": "I-80",
            },
            "I-80",
        ),
        (
            {
                "place_category": "highway",
                "place_type": "trunk",
                "street": "",
                "route_number": "US-101",
            },
            "US-101",
        ),
    ],
)
def test_add_street_info_highway(
    attrs: Attrs, expected: str, basic_parser: BasicParserFactory
) -> None:
    """Prefer route_number for highways and motorways when street is empty."""
    parser, sensor = basic_parser(attrs=attrs)
    arr: list[str] = []
    parser.add_street_info(arr, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    ("attrs", "expected_city", "expected_state"),
    [
        ({"city_clean": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"city": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"county": "Clark", "state_abbr": "OH"}, "Clark", "OH"),
    ],
)
def test_add_city_county_state(
    attrs: Attrs, expected_city: str, expected_state: str, basic_parser: BasicParserFactory
) -> None:
    """Test that `add_city_county_state` appends the correct city/county and state abbreviation to the list."""
    parser, sensor = basic_parser(attrs=attrs)
    arr: list[str] = []
    parser.add_city_county_state(arr, sensor)
    assert expected_city in arr
    assert expected_state in arr


@pytest.mark.parametrize(
    ("attrs", "duplicate_list", "expected"),
    [
        ({"place_name": "Park"}, [], True),
        ({"place_name": ""}, [], False),
        ({"place_name": "Dup", "city": "Dup"}, ["city"], False),
    ],
)
def test_should_use_place_name(
    attrs: Attrs,
    duplicate_list: list[str],
    expected: bool,
    basic_parser: BasicParserFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that `should_use_place_name` returns the correct boolean based on place_name and duplicates."""
    parser, sensor = basic_parser(attrs=attrs)
    if duplicate_list:
        monkeypatch.setattr(
            "custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST",
            duplicate_list,
            raising=False,
        )
    assert parser.should_use_place_name(attrs, sensor) is expected
