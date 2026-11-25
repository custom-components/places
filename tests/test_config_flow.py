"""Tests for the Places integration config and options flows."""

from collections.abc import Callable, Sequence
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    MAX_LENGTH_STATE_STATE,
)
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.places.config_flow import (
    HOME_LOCATION_DOMAINS,
    PlacesConfigFlow,
    PlacesOptionsFlowHandler,
    get_devicetracker_id_entities,
    get_home_zone_entities,
    validate_display_options,
)
from custom_components.places.config_schema import user_schema
from custom_components.places.const import (
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_GEOCODING_MODE,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_GEOCODING_MODE,
    DEFAULT_HOME_ZONE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    GEOCODING_MODE_FORWARD,
    GEOCODING_MODE_REVERSE,
)

type ConfigData = dict[str, object]
type LabelCheck = Callable[[dict[str, str]], bool]


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Create a mock configuration entry for the 'places' integration with predefined test data.

    Returns:
        MockConfigEntry:
            MockConfigEntry: A mock config entry populated with typical 'places' integration fields
            for testing.
    """
    return MockConfigEntry(
        domain="places",
        data={
            "name": "Test Place",
            "devicetracker_id": "device.test",
            CONF_DISPLAY_OPTIONS: "zone, place",
            "home_zone": "zone.home",
            "map_provider": "osm",
            "map_zoom": 10,
            "use_gps": True,
            "extended_attr": False,
            "show_time": True,
            "date_format": "mm/dd",
            "language": "en",
        },
        options={},
        entry_id="12345",
    )


@pytest.mark.asyncio
async def test_config_flow_user_step(mock_hass: MagicMock) -> None:
    """Verify the config flow user step creates an entry when given valid input.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    user_input = {
        "name": "Test Place",
        "devicetracker_id": "device.test",
        CONF_DISPLAY_OPTIONS: "zone, place",
        "home_zone": "zone.home",
        "map_provider": "osm",
        "map_zoom": 10,
        "use_gps": True,
        "extended_attr": False,
        "show_time": True,
        "date_format": "mm/dd",
        "language": "en",
    }
    result = await flow.async_step_user(user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Place"
    assert result["data"] == user_input


def test_user_schema_sets_expected_defaults() -> None:
    """Ensure the extracted user schema injects the documented defaults."""
    schema = user_schema(
        [{"value": "device.test", "label": "Device Test"}],
        [{"value": "zone.home", "label": "Home Zone"}],
    )

    validated = schema(
        {
            "name": "Test Place",
            "devicetracker_id": "device.test",
        }
    )

    assert validated["name"] == "Test Place"
    assert validated["devicetracker_id"] == "device.test"
    assert validated[CONF_DISPLAY_OPTIONS] == DEFAULT_DISPLAY_OPTIONS
    assert validated["home_zone"] == DEFAULT_HOME_ZONE
    assert validated["map_provider"] == DEFAULT_MAP_PROVIDER
    assert validated["map_zoom"] == int(DEFAULT_MAP_ZOOM)
    assert validated[CONF_USE_GPS] == DEFAULT_USE_GPS
    assert validated[CONF_EXTENDED_ATTR] == DEFAULT_EXTENDED_ATTR
    assert validated[CONF_SHOW_TIME] == DEFAULT_SHOW_TIME
    assert validated["date_format"] == DEFAULT_DATE_FORMAT
    assert validated[CONF_GEOCODING_MODE] == DEFAULT_GEOCODING_MODE == GEOCODING_MODE_REVERSE


@pytest.mark.asyncio
async def test_options_flow_init(mock_hass: MagicMock, config_entry: MockConfigEntry) -> None:
    """Ensure the options flow init returns a form schema for editing options.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        config_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    config_entry.add_to_hass(mock_hass)
    result = await mock_hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "user_input"),
    [
        (
            "updates_and_reload",
            {
                "devicetracker_id": "device.test",
                "name": "Test Place",
                CONF_DISPLAY_OPTIONS: "zone, place",
                "home_zone": "zone.home",
                "map_provider": "osm",
                "map_zoom": 10,
                "use_gps": True,
                "extended_attr": False,
                "show_time": True,
                "date_format": "mm/dd",
                "language": "en",
                "api_key": "",
            },
        ),
        (
            "removes_blank_keys",
            {
                "devicetracker_id": "device.test",
                "name": "",
                CONF_DISPLAY_OPTIONS: "zone, place",
                "home_zone": "",
                "map_provider": "osm",
                "map_zoom": 10,
                "use_gps": True,
                "extended_attr": False,
                "show_time": True,
                "date_format": "mm/dd",
                "language": "",
                "api_key": "",
            },
        ),
        (
            "merges_config_entry",
            {CONF_DISPLAY_OPTIONS: "zone, place", "devicetracker_id": "device.test"},
        ),
    ],
)
async def test_options_flow_handler_variants(
    mock_hass: MagicMock,
    config_entry: MockConfigEntry,
    case: str,
    user_input: ConfigData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parametrized: ensure options flow handler behaves correctly for different input variants.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        config_entry (MockConfigEntry):
            Places configuration entry used by the test.
        case (str):
            Named parameter set for the current case.
        user_input (ConfigData):
            Options-flow submission for the parametrized case.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    # use monkeypatch to provide the config_entry property on the handler type
    monkeypatch.setattr(
        type(handler), "config_entry", property(lambda self: config_entry), raising=False
    )
    mock_hass.config_entries.async_update_entry = MagicMock()
    mock_hass.config_entries.async_reload = AsyncMock()
    result = await handler.async_step_init(user_input)
    # Basic return contract
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # Case-specific assertions
    if case == "updates_and_reload":
        mock_hass.config_entries.async_update_entry.assert_called_once_with(
            config_entry, data=user_input, options=config_entry.options
        )
        mock_hass.config_entries.async_reload.assert_awaited_once_with(config_entry.entry_id)
        assert result["data"] == {}
    elif case == "removes_blank_keys":
        updated_data = mock_hass.config_entries.async_update_entry.call_args[1]["data"]
        assert "name" not in updated_data
        assert "home_zone" not in updated_data
        assert "language" not in updated_data
        assert "api_key" not in updated_data
    elif case == "merges_config_entry":
        updated_data = mock_hass.config_entries.async_update_entry.call_args[1]["data"]
        expected_data = dict(config_entry.data)
        expected_data.update(user_input)
        for k, v in expected_data.items():
            assert updated_data[k] == v


@pytest.mark.parametrize(
    ("async_all_states", "states_get_state", "expected_label_check", "expected_count"),
    [
        # current not present, has friendly name -> label contains friendly name, appears once
        (
            [],
            State("device_tracker.extra", "", {ATTR_FRIENDLY_NAME: "Extra"}),
            lambda e: e["label"] == "Extra (device_tracker.extra)",
            1,
        ),
        # current not present, no friendly name -> label equals entity_id, appears once
        (
            [],
            State("device_tracker.extra", "", {}),
            lambda e: e["label"] == "device_tracker.extra",
            1,
        ),
        # current already present in async_all -> ensure no duplicate entries
        (
            [State("device_tracker.extra", "", {ATTR_FRIENDLY_NAME: "Already"})],
            State("device_tracker.extra", "", {ATTR_FRIENDLY_NAME: "Already"}),
            lambda e: "Already" in e["label"],
            1,
        ),
    ],
)
def test_get_devicetracker_id_entities_current_entity_variants(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    patch_entity_registry: object,
    async_all_states: Sequence[State],
    states_get_state: State,
    expected_label_check: LabelCheck,
    expected_count: int,
) -> None:
    """Parametrized tests for current_entity handling in get_devicetracker_id_entities.

    Covers: friendly name present, no friendly name, and already-present cases.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        patch_entity_registry (object):
            Isolated entity-registry fixture.
        async_all_states (Sequence[State]):
            Tracker states returned by the mocked state machine.
        states_get_state (State):
            Current tracker state returned by direct lookup.
        expected_label_check (LabelCheck):
            Predicate callable that validates a matching entity label.
        expected_count (int):
            Number of matching entities expected by the assertion.
    """
    _ = patch_entity_registry
    # Limit TRACKING_DOMAINS to a single domain for deterministic results
    domain = "device_tracker"
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", [domain])
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS_FORWARD_ONLY", [])

    mock_hass.states.async_all = MagicMock(return_value=async_all_states)
    mock_hass.states.get = MagicMock(return_value=states_get_state)

    entities = get_devicetracker_id_entities(mock_hass, current_entity="device_tracker.extra")
    matches = [e for e in entities if e["value"] == "device_tracker.extra"]
    assert len(matches) == expected_count
    if expected_count:
        assert any(expected_label_check(e) for e in matches)


def test_get_devicetracker_id_entities_excludes_places_sensors(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Places sensors should not be offered as their own tracked entities.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    places_state = State(
        "sensor.my_places",
        "Home",
        {ATTR_FRIENDLY_NAME: "My Places", CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0},
    )
    tracker_state = State(
        "sensor.gps_tracker",
        "Home",
        {ATTR_FRIENDLY_NAME: "GPS Tracker", CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0},
    )
    states = {state.entity_id: state for state in (places_state, tracker_state)}
    registry = MagicMock()
    registry.async_get.side_effect = lambda entity_id: MagicMock(
        platform="places" if entity_id == places_state.entity_id else "template"
    )
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", ["sensor"])
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS_FORWARD_ONLY", [])
    monkeypatch.setattr(
        "custom_components.places.config_flow.TRACKING_DOMAINS_NEED_LATLONG", ["sensor"]
    )
    registry_module = MagicMock()
    registry_module.async_get.return_value = registry
    monkeypatch.setattr("custom_components.places.config_flow.er", registry_module, raising=False)
    mock_hass.states.async_all.return_value = [places_state, tracker_state]
    mock_hass.states.get.side_effect = states.get

    entities = get_devicetracker_id_entities(mock_hass)

    assert [entity["value"] for entity in entities] == [tracker_state.entity_id]

    mock_hass.states.async_all.return_value = []
    assert get_devicetracker_id_entities(mock_hass, places_state.entity_id) == []


def test_get_devicetracker_id_entities_uses_scanned_state_when_lookup_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Trackers returned by the domain scan remain selectable if a later lookup misses.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing config-flow dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    tracker_state = State(
        "sensor.gps_tracker",
        "Home",
        {ATTR_FRIENDLY_NAME: "GPS Tracker", CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0},
    )
    registry = MagicMock()
    registry.async_get.return_value = None
    registry_module = MagicMock()
    registry_module.async_get.return_value = registry
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", ["sensor"])
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS_FORWARD_ONLY", [])
    monkeypatch.setattr(
        "custom_components.places.config_flow.TRACKING_DOMAINS_NEED_LATLONG", ["sensor"]
    )
    monkeypatch.setattr("custom_components.places.config_flow.er", registry_module, raising=False)
    mock_hass.states.async_all.return_value = [tracker_state]
    mock_hass.states.get.return_value = None

    entities = get_devicetracker_id_entities(mock_hass)

    assert entities == [
        {"value": tracker_state.entity_id, "label": "GPS Tracker (sensor.gps_tracker)"}
    ]


def test_get_home_zone_entities_builds_zone_list(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock
) -> None:
    """get_home_zone_entities should return zone entities labeled by their friendly names and sorted by label.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    # use mock_hass fixture to provide a consistent hass object
    hass = mock_hass
    # Only one domain for simplicity
    domain = HOME_LOCATION_DOMAINS[0]
    hass.states.async_all = MagicMock(
        return_value=[
            State("zone.home", "", {ATTR_FRIENDLY_NAME: "Home Zone"}),
            State("zone.work", "", {ATTR_FRIENDLY_NAME: "Work Zone"}),
        ]
    )

    # Patch HOME_LOCATION_DOMAINS to only include our test domain
    monkeypatch.setattr("custom_components.places.config_flow.HOME_LOCATION_DOMAINS", [domain])

    zones = get_home_zone_entities(hass)
    # Should include both zones with correct labels
    assert any(z["value"] == "zone.home" and "Home Zone" in z["label"] for z in zones)
    assert any(z["value"] == "zone.work" and "Work Zone" in z["label"] for z in zones)
    # Should sort by label
    labels = [z["label"] for z in zones]
    assert labels == sorted(labels, key=str.casefold)


def test_async_get_options_flow_returns_handler() -> None:
    """Ensure PlacesConfigFlow.async_get_options_flow returns a handler instance for a config entry."""
    config_entry = MockConfigEntry(domain="places", data={})
    handler = PlacesConfigFlow.async_get_options_flow(config_entry)
    assert isinstance(handler, PlacesOptionsFlowHandler)


@pytest.mark.asyncio
async def test_options_flow_handler_shows_form_when_no_user_input(
    mock_hass: MagicMock, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that the options flow handler displays a form with the correct schema and description placeholders when no user input is provided (None).

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        config_entry (MockConfigEntry):
            Places configuration entry used by the test.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    # attach config_entry property and stub helper functions via monkeypatch
    monkeypatch.setattr(
        type(handler), "config_entry", property(lambda self: config_entry), raising=False
    )
    monkeypatch.setattr(
        "custom_components.places.config_flow.get_devicetracker_id_entities",
        lambda hass, current_entity=None: [{"value": "device.test", "label": "Device Test"}],
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.places.config_flow.get_home_zone_entities",
        lambda hass: [{"value": "zone.home", "label": "Home Zone"}],
        raising=False,
    )

    result = await handler.async_step_init(None)
    assert result["type"] == "form"
    assert "data_schema" in result
    assert result["step_id"] == "init"
    assert "description_placeholders" in result
    assert result["description_placeholders"]["sensor_name"] == config_entry.data["name"]
    assert result["description_placeholders"]["component_config_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("display_options", "expected_errors"),
    [
        pytest.param("zone,place", {}, id="basic-options-no-space"),
        pytest.param("zone, place", {}, id="basic-options-skip-advanced-validation"),
        pytest.param("zone,unknown", {}, id="basic-unknown-option-skips-advanced-validation"),
        pytest.param("unknown", {}, id="single-unknown-option-skips-advanced-validation"),
        pytest.param("name_no_dupe[type(-, unclassified)]", {}, id="simple-exclude-values"),
        pytest.param(
            "type(house, category(highway))",
            {},
            id="implicit-include-literal-with-attribute-filter",
        ),
        pytest.param(
            "route_number(type(+, motorway, trunk))",
            {},
            id="simple-include-values",
        ),
        pytest.param("city_clean[county]", {}, id="single-fallback-option"),
        pytest.param("street[route_number]", {}, id="simple-nested-option"),
        pytest.param(
            "name_no_dupe[type(house, category(highway))]",
            {},
            id="fallback-filter-implicit-include-literal-with-attribute-filter",
        ),
        pytest.param(
            "driving, name_no_dupe[type(-, unclassified, category(-, highway))"
            "[category(-, highway)], house_number, route_number(type(+, motorway, trunk))"
            "[street[route_number]], neighborhood(type(house))], city_clean[county], "
            "state_abbr",
            {},
            id="complex-nested-advanced-options",
        ),
        pytest.param(
            "zone,[place](zone)",
            {"base": "invalid_syntax"},
            id="bracket-group-followed-by-paren-group",
        ),
        pytest.param(
            "zone,[place,unknown]",
            {"base": "invalid_syntax"},
            id="comma-before-bracket-with-unknown-option",
        ),
        pytest.param(
            "zone,[place],unknown",
            {"base": "invalid_syntax"},
            id="comma-before-bracket-then-trailing-unknown-option",
        ),
        pytest.param(
            "zone,[place,(zone)]",
            {"base": "invalid_syntax"},
            id="mismatched-nested-paren-and-bracket",
        ),
        pytest.param(
            "zone,[place,(zone]",
            {"base": "invalid_syntax"},
            id="unclosed-nested-paren",
        ),
        pytest.param(
            "name_no_dupe[type(-, unclassified)",
            {"base": "bracket_mismatch"},
            id="unmatched-bracket",
        ),
        pytest.param(
            "city]",
            {"base": "bracket_mismatch"},
            id="unmatched-closing-bracket-only",
        ),
        pytest.param(
            "route_number(type(+, motorway, trunk,))",
            {"base": "invalid_syntax"},
            id="trailing-comma-in-parens",
        ),
        pytest.param(
            "city_clean[county,,state]",
            {"base": "invalid_syntax"},
            id="empty-bracketed-option",
        ),
        pytest.param(
            "city clean[county]",
            {"base": "invalid_syntax"},
            id="space-in-option-name",
        ),
        pytest.param(
            "city_clean[unknown_option]",
            {"base": "invalid_option"},
            id="unknown-bracketed-option",
        ),
        pytest.param(
            "+foo[place]",
            {"base": "invalid_option"},
            id="prefixed-plus-token-is-invalid",
        ),
        pytest.param(
            "-bar[place]",
            {"base": "invalid_option"},
            id="prefixed-minus-token-is-invalid",
        ),
        pytest.param(
            "zone_name[county],unknown",
            {"base": "invalid_option"},
            id="unknown-option-after-valid-advanced-option",
        ),
    ],
)
async def test_validate_display_options_accepts_advanced_options(
    display_options: str, expected_errors: dict[str, str]
) -> None:
    """Validate advanced display option strings across simple and complex permutations.

    Args:
        display_options (str):
            Display options applied to state rendering.
        expected_errors (dict[str, str]):
            Validation errors expected from the options flow.
    """
    errors: dict[str, str] = {}

    result = await validate_display_options(display_options, errors)

    assert result == expected_errors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "display_options",
    ["x" * MAX_LENGTH_STATE_STATE, "x" * (MAX_LENGTH_STATE_STATE + 1)],
)
async def test_validate_display_options_allows_legacy_long_rules(display_options: str) -> None:
    """Config flows allow legacy rules longer than the text entity state limit.

    Args:
        display_options (str):
            Display options applied to state rendering.
    """
    errors: dict[str, str] = {}

    result = await validate_display_options(display_options, errors)

    assert result == {}


@pytest.mark.parametrize(
    ("display_options", "expected_errors"),
    [
        ("", {"base": "invalid_syntax"}),
        ("   ", {"base": "invalid_syntax"}),
        ("\n\t", {"base": "invalid_syntax"}),
    ],
)
async def test_validate_display_options_rejects_blank_values(
    display_options: str, expected_errors: dict[str, str]
) -> None:
    """Blank or whitespace-only display options are rejected to match coordinator validation.

    Args:
        display_options (str):
            Display options applied to state rendering.
        expected_errors (dict[str, str]):
            Validation errors expected from the options flow.
    """
    errors: dict[str, str] = {}

    result = await validate_display_options(display_options, errors)

    assert result == expected_errors


@pytest.mark.asyncio
async def test_config_flow_user_step_no_input_shows_form(mock_hass: MagicMock) -> None:
    """User step with no input returns a form and includes description placeholders.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    result = await flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "data_schema" in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule", "error"),
    [
        (" ", "invalid_syntax"),
        ("unknown[,city", "bracket_mismatch"),
        ("city]", "bracket_mismatch"),
        ("unknown[,city]", "invalid_syntax"),
        ("zone,[place,(zone]", "invalid_syntax"),
        ("name(city_missing(building))[city[county]]", "invalid_option"),
    ],
)
async def test_config_flow_user_step_invalid_display_options(
    mock_hass: MagicMock, rule: str, error: str
) -> None:
    """Invalid display options should return form with errors populated.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        rule (str):
            Display options submitted to the config flow.
        error (str):
            Feedback expected before config entry creation.
    """
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    bad_input = {
        "name": "Bad Sensor",
        "devicetracker_id": "device.test",
        CONF_DISPLAY_OPTIONS: rule,
        "home_zone": "zone.home",
        "map_provider": "osm",
        "map_zoom": 10,
        "use_gps": True,
        "extended_attr": False,
        "show_time": True,
        "date_format": "mm/dd",
        "language": "en",
    }
    result = await flow.async_step_user(bad_input)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_options_flow_invalid_display_options_shows_form(
    mock_hass: MagicMock,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    patch_entity_registry: object,
) -> None:
    """Options flow with invalid display options string returns form (errors path).

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        config_entry (MockConfigEntry):
            Places configuration entry used by the test.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        patch_entity_registry (object):
            Isolated entity-registry fixture.
    """
    _ = patch_entity_registry
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    # attach config_entry property directly on handler type
    monkeypatch.setattr(
        type(handler), "config_entry", property(lambda self: config_entry), raising=False
    )
    bad_user_input = {
        "devicetracker_id": "device.test",
        CONF_DISPLAY_OPTIONS: "zone,[place,(zone]",
    }
    result = await handler.async_step_init(bad_user_input)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_syntax"}
    assert result["step_id"] == "init"


ADDRESS_TEXT = State("input_text.address", "10 Downing Street", {ATTR_FRIENDLY_NAME: "Address"})
ADDRESS_SENSOR = State("sensor.address", "10 Downing Street", {ATTR_FRIENDLY_NAME: "Addr"})
GPS_SENSOR = State(
    "sensor.gps",
    "ok",
    {ATTR_FRIENDLY_NAME: "GPS", CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0},
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tracker", "mode", "expected_error"),
    [
        pytest.param(ADDRESS_TEXT, GEOCODING_MODE_FORWARD, None, id="forward_text_entity"),
        pytest.param(ADDRESS_SENSOR, GEOCODING_MODE_FORWARD, None, id="forward_sensor_no_coords"),
        pytest.param(GPS_SENSOR, None, None, id="default_reverse_sensor_with_coords"),
        pytest.param(
            ADDRESS_TEXT, None, "tracker_needs_coordinates", id="default_reverse_text_entity"
        ),
        pytest.param(
            ADDRESS_SENSOR,
            GEOCODING_MODE_REVERSE,
            "tracker_needs_coordinates",
            id="reverse_sensor_no_coords",
        ),
    ],
)
async def test_config_flow_user_step_validates_tracker_for_geocoding_mode(
    mock_hass: MagicMock,
    patch_entity_registry: object,
    tracker: State,
    mode: str | None,
    expected_error: str | None,
) -> None:
    """Coordinates are only required from the tracked entity in reverse mode.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        patch_entity_registry (object):
            Isolated entity-registry fixture used when the form is re-rendered.
        tracker (State):
            Tracked entity state selected by the user.
        mode (str | None):
            Submitted geocoding mode, or ``None`` to omit it.
        expected_error (str | None):
            Expected ``devicetracker_id`` error, or ``None`` for a created entry.
    """
    _ = patch_entity_registry
    mock_hass.states.get.side_effect = lambda entity_id: (
        tracker if entity_id == tracker.entity_id else None
    )
    mock_hass.states.async_all.return_value = []
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    user_input: ConfigData = {
        "name": "Geocoder",
        CONF_DEVICETRACKER_ID: tracker.entity_id,
        CONF_DISPLAY_OPTIONS: DEFAULT_DISPLAY_OPTIONS,
    }
    if mode is not None:
        user_input[CONF_GEOCODING_MODE] = mode

    result = await flow.async_step_user(user_input)

    if expected_error is None:
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == user_input
    else:
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {CONF_DEVICETRACKER_ID: expected_error}


def test_get_devicetracker_id_entities_offers_forward_geocoding_candidates(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    patch_entity_registry: object,
) -> None:
    """Entities without coordinates and text entities are selectable for forward mode.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        patch_entity_registry (object):
            Isolated entity-registry fixture.
    """
    _ = patch_entity_registry
    by_domain = {"sensor": [ADDRESS_SENSOR, GPS_SENSOR], "input_text": [ADDRESS_TEXT]}
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", ["sensor"])
    monkeypatch.setattr(
        "custom_components.places.config_flow.TRACKING_DOMAINS_FORWARD_ONLY", ["input_text"]
    )
    mock_hass.states.async_all.side_effect = lambda domain: by_domain.get(domain, [])

    entities = get_devicetracker_id_entities(mock_hass)

    assert {entity["value"] for entity in entities} == {
        "input_text.address",
        "sensor.address",
        "sensor.gps",
    }
