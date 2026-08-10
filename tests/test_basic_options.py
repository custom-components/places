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
        """Create the parser and sensor.

        Args:
            attrs (Attrs | None):
                Places attribute mapping used by the test.
            options (Sequence[str] | None):
                Configuration options applied by the flow or parser.
            display_options_list (Sequence[str] | None):
                Display-option tokens available to the parser.
            in_zone (bool):
                Whether the tracker is inside the selected zone.

        Returns:
            tuple[BasicOptionsParser, MockSensor]:
                Basic options parser and the backing ``MockSensor``.
        """


@pytest.fixture
def basic_parser() -> BasicParserFactory:
    """Factory fixture to create a BasicOptionsParser and its backing sensor.

    Returns (parser, sensor).

    Returns:
        BasicParserFactory:
            Factory that constructs basic-option parsers for test inputs.
    """

    def _create(
        attrs: Attrs | None = None,
        options: Sequence[str] | None = None,
        display_options_list: Sequence[str] | None = None,
        in_zone: bool = False,
    ) -> tuple[BasicOptionsParser, MockSensor]:
        """Create a basic-options parser backed by a configured mock sensor.

        Args:
            attrs (Attrs | None):
                Sensor attributes exposed to parser lookups.
            options (Sequence[str] | None):
                Basic display options to pass into the parser.
            display_options_list (Sequence[str] | None):
                Raw display-options list exposed by the mock
                sensor.
            in_zone (bool):
                Whether the mock sensor should report itself in a zone.

        Returns:
            tuple[BasicOptionsParser, MockSensor]:
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
    ("attrs", "in_zone", "options", "expected"),
    [
        (
            {},
            False,
            ["driving", "zone_name", "zone", "place"],
            "",
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
            "Driving, Home, Park, Downtown, Main St, Springfield",
        ),
        (
            {"zone_name": "Work"},
            True,
            ["zone_name"],
            "Work",
        ),
    ],
)
async def test_build_display_scenarios(
    attrs: Attrs,
    in_zone: bool,
    options: Sequence[str],
    expected: str,
    sensor: MockSensor,
) -> None:
    """Parametrized scenarios for BasicOptionsParser.build_display output.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        in_zone (bool):
            Whether the tracker is inside the selected zone.
        options (Sequence[str]):
            Configuration options applied by the flow or parser.
        expected (str):
            Expected result for this parametrized case.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    # Mutate shared sensor fixture for this scenario
    sensor.attrs = dict(attrs or {})
    sensor._in_zone = in_zone
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_display()
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attrs", "in_zone", "options", "display_list", "expected"),
    [
        (
            {ATTR_PLACE_NAME: "Central Park"},
            False,
            ["place"],
            ["driving"],
            "Central Park",
        ),
        (
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
            "Restaurant, Elm St, Metropolis",
        ),
        (
            {"zone_name": "Home"},
            True,
            ["zone_name"],
            None,
            "Home",
        ),
    ],
)
async def test_build_formatted_place_variants(
    attrs: Attrs,
    in_zone: bool,
    options: Sequence[str],
    display_list: Sequence[str] | None,
    expected: str,
    sensor: MockSensor,
) -> None:
    """Parametrized exact outputs for BasicOptionsParser.build_formatted_place.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        in_zone (bool):
            Whether the tracker is inside the selected zone.
        options (Sequence[str]):
            Configuration options applied by the flow or parser.
        display_list (Sequence[str] | None):
            Display-option tokens used to render the state.
        expected (str):
            Expected result for this parametrized case.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = dict(attrs or {})
    sensor._in_zone = in_zone
    sensor.display_options_list = display_list or []
    parser = BasicOptionsParser(sensor, attrs, options)
    result = await parser.build_formatted_place()
    assert result == expected


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
    """Test that `add_type_or_category` adds the correct capitalized type or category to the list.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        expected (str):
            Expected result for this parametrized case.
        basic_parser (BasicParserFactory):
            Basic display-options parser fixture.
    """
    parser, sensor = basic_parser(attrs=attrs)
    arr: list[str] = []
    parser.add_type_or_category(arr, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"street": "Main St", "street_number": ""}, "Main St"),
        ({"street": "Main St", "street_number": "123"}, "123 Main St"),
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
def test_add_street_info(attrs: Attrs, expected: str, basic_parser: BasicParserFactory) -> None:
    """Append normal, numbered, or highway route street info to the list.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        expected (str):
            Expected result for this parametrized case.
        basic_parser (BasicParserFactory):
            Basic display-options parser fixture.
    """
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
    """Test that `add_city_county_state` appends the correct city/county and state abbreviation to the list.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        expected_city (str):
            City name expected after address parsing.
        expected_state (str):
            Entity state expected for this parametrized case.
        basic_parser (BasicParserFactory):
            Basic display-options parser fixture.
    """
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
        ({"place_name": 123, "city": 123}, ["city"], False),
    ],
)
def test_should_use_place_name(
    attrs: Attrs,
    duplicate_list: list[str],
    expected: bool,
    basic_parser: BasicParserFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that `should_use_place_name` returns the correct boolean based on place_name and duplicates.

    Args:
        attrs (Attrs):
            Places attribute mapping used by the test.
        duplicate_list (list[str]):
            Configured attribute names checked for duplicate place names.
        expected (bool):
            Expected result for this parametrized case.
        basic_parser (BasicParserFactory):
            Basic display-options parser fixture.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
    parser, sensor = basic_parser(attrs=attrs)
    if duplicate_list:
        monkeypatch.setattr(
            "custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST",
            duplicate_list,
            raising=False,
        )
    assert parser.should_use_place_name(attrs, sensor) is expected
