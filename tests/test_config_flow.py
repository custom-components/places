"""Tests for the Places integration config and options flows."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.config_flow import (
    HOME_LOCATION_DOMAINS,
    PlacesConfigFlow,
    PlacesOptionsFlowHandler,
    _validate_brackets,
    _validate_comma_syntax,
    _validate_known_options,
    _validate_option_names,
    get_devicetracker_id_entities,
    get_home_zone_entities,
    validate_display_options,
)
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def config_entry():
    """Create a mock configuration entry for the 'places' integration with predefined test data.

    Returns:
        MockConfigEntry: A mock config entry populated with typical 'places' integration fields for testing.

    """
    return MockConfigEntry(
        domain="places",
        data={
            "name": "Test Place",
            "devicetracker_id": "device.test",
            "display_options": "zone, place",
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
async def test_config_flow_user_step(mock_hass):
    """Verify the config flow user step creates an entry when given valid input."""
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    user_input = {
        "name": "Test Place",
        "devicetracker_id": "device.test",
        "display_options": "zone, place",
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


@pytest.mark.asyncio
async def test_options_flow_init(mock_hass, config_entry):
    """Ensure the options flow init returns a form schema for editing options."""
    config_entry.add_to_hass(mock_hass)
    result = await mock_hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,user_input",
    [
        (
            "updates_and_reload",
            {
                "devicetracker_id": "device.test",
                "name": "Test Place",
                "display_options": "zone, place",
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
                "display_options": "zone, place",
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
            {"devicetracker_id": "device.test", "display_options": "zone, place"},
        ),
    ],
)
async def test_options_flow_handler_variants(mock_hass, config_entry, case, user_input):
    """Parametrized: ensure options flow handler behaves correctly for different input variants."""
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
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
    "async_all_states,states_get_state,expected_label_check,expected_count",
    [
        # current not present, has friendly name -> label contains friendly name, appears once
        (
            [],
            State("device_tracker.extra", "", {ATTR_FRIENDLY_NAME: "Extra"}),
            lambda e: "Extra" in e["label"],
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
    monkeypatch, mock_hass, async_all_states, states_get_state, expected_label_check, expected_count
):
    """Parametrized tests for current_entity handling in get_devicetracker_id_entities.

    Covers: friendly name present, no friendly name, and already-present cases.
    """
    # Limit TRACKING_DOMAINS to a single domain for deterministic results
    domain = "device_tracker"
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", [domain])

    mock_hass.states.async_all = MagicMock(return_value=async_all_states)
    mock_hass.states.get = MagicMock(return_value=states_get_state)

    entities = get_devicetracker_id_entities(mock_hass, current_entity="device_tracker.extra")
    matches = [e for e in entities if e["value"] == "device_tracker.extra"]
    assert len(matches) == expected_count
    if expected_count:
        assert any(expected_label_check(e) for e in matches)


def test_get_home_zone_entities_builds_zone_list(monkeypatch, mock_hass):
    """get_home_zone_entities should return zone entities labeled by their friendly names and sorted by label."""

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


def test_async_get_options_flow_returns_handler():
    """Ensure PlacesConfigFlow.async_get_options_flow returns a handler instance for a config entry."""
    config_entry = MockConfigEntry(domain="places", data={})
    handler = PlacesConfigFlow.async_get_options_flow(config_entry)
    assert isinstance(handler, PlacesOptionsFlowHandler)


@pytest.mark.asyncio
async def test_options_flow_handler_shows_form_when_no_user_input(mock_hass, config_entry):
    """Test that the options flow handler displays a form with the correct schema and description placeholders when no user input is provided (None)."""
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    with (
        patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)),
        patch(
            "custom_components.places.config_flow.get_devicetracker_id_entities",
            return_value=[{"value": "device.test", "label": "Device Test"}],
        ),
        patch(
            "custom_components.places.config_flow.get_home_zone_entities",
            return_value=[{"value": "zone.home", "label": "Home Zone"}],
        ),
    ):
        result = await handler.async_step_init(None)
        assert result["type"] == "form"
        assert "data_schema" in result
        assert result["step_id"] == "init"
        assert "description_placeholders" in result
        assert result["description_placeholders"]["sensor_name"] == config_entry.data["name"]
        assert result["description_placeholders"]["component_config_url"]


@pytest.mark.asyncio
async def test_options_flow_handler_merges_config_entry_data(mock_hass, config_entry):
    """Test that the options flow handler merges user input with existing config entry data and updates the entry.

    Asserts that the updated config entry data contains both the original and new values, and that the flow returns a create entry result.
    """
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
        user_input = {
            "devicetracker_id": "device.test",
            "display_options": "zone, place",
        }
        expected_data = dict(config_entry.data)
        expected_data.update(user_input)
        mock_hass.config_entries.async_update_entry = MagicMock()
        mock_hass.config_entries.async_reload = AsyncMock()
        result = await handler.async_step_init(user_input)
        updated_data = mock_hass.config_entries.async_update_entry.call_args[1]["data"]
        for k, v in expected_data.items():
            assert updated_data[k] == v
        assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "display_options,expected",
    [
        ("zone,place", True),  # Should be valid
        ("zone,[place]", False),
        ("zone,[place,zone]", False),
        ("zone,[place,(zone)]", False),
        ("zone,[place,(zone]", False),  # Unmatched bracket
        ("zone,place]", False),  # Unmatched closing bracket
        ("zone,[place,]", False),  # Trailing comma
        ("zone,[,place]", False),  # Leading comma
        ("zone,[place](city)", False),  # Still invalid: '[' directly after comma
        ("zone,[place](zone)", False),  # Invalid per validator (item expected before '[')
    ],
)
def test_validate_brackets(display_options, expected):
    """Test the _validate_brackets function to ensure it correctly validates bracket usage in display_options."""
    errors = {}
    result = _validate_brackets(display_options, errors)
    assert result is expected


@pytest.mark.parametrize(
    "display_options,expected",
    [
        ("zone,place", False),  # Should be invalid
        ("zone,unknown", False),  # 'unknown' not in DISPLAY_OPTIONS_MAP
        ("zone,[place,unknown]", False),
        ("zone,[place],unknown", False),  # Invalid last token after bracket group
        ("unknown", False),  # Single invalid token
    ],
)
def test_validate_known_options(display_options, expected):
    """Test the _validate_known_options function to ensure it correctly validates known display options.

    Parameters:
        display_options (str): The display options string to validate.
        expected (bool): The expected result of the validation.

    """
    errors = {}
    result = _validate_known_options(display_options, errors)
    assert result is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "display_options,has_error",
    [
        ("zone,place", False),  # Valid
        ("zone,[place,(zone)]", True),  # Invalid
        ("zone,[place,(zone]", True),  # Invalid
        # ("zone,,place", False),  # Valid (your logic does not catch double comma)
        # ("zone name,place", False),  # Valid (your logic does not catch space in option name)
        # ("zone,unknown", False),  # Valid (your logic does not catch unknown option)
    ],
)
async def test_validate_display_options(display_options, has_error):
    """Test the validate_display_options function to ensure it returns errors for invalid display option syntax.

    Parameters:
        display_options (str): The display options string to validate.
        has_error (bool): Whether an error is expected for the given input.

    """
    errors = {}
    result = await validate_display_options(display_options, errors)
    assert (result != {}) is has_error


@pytest.mark.asyncio
async def test_validate_display_options_brackets_then_paren_invalid():
    """Advanced validation fails for bracket group directly followed by paren group."""
    errors = {}
    result = await validate_display_options("zone,[place](zone)", errors)
    assert result != {}


@pytest.mark.asyncio
async def test_config_flow_user_step_no_input_shows_form(mock_hass):
    """User step with no input returns a form and includes description placeholders."""
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    result = await flow.async_step_user(None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_config_flow_user_step_invalid_display_options(mock_hass):
    """Invalid display options should return form with errors populated."""
    flow = PlacesConfigFlow()
    flow.hass = mock_hass
    bad_input = {
        "name": "Bad Sensor",
        "devicetracker_id": "device.test",
        "options": "zone,[place,(zone]",
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
    assert result["errors"] != {}
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_options_flow_invalid_display_options_shows_form(mock_hass, config_entry):
    """Options flow with invalid display options string returns form (errors path)."""
    config_entry.add_to_hass(mock_hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = mock_hass
    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
        bad_user_input = {
            "devicetracker_id": "device.test",
            "options": "zone,[place,(zone]",  # invalid using correct key
        }
        result = await handler.async_step_init(bad_user_input)
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] != {}
        assert result["step_id"] == "init"


@pytest.mark.parametrize(
    "display_options,expected",
    [
        ("zone,place", True),  # Valid: single comma
        ("zone,,place", False),  # Invalid: double comma
        ("zone,[place,zone]", True),  # Valid: comma inside brackets
        ("zone,[place,]", False),  # Invalid: trailing comma in brackets
        ("zone,[,place]", False),  # Invalid: leading comma in brackets
        ("zone,(place,zone)", True),  # Valid: comma inside parentheses
        ("zone,(place,)", False),  # Invalid: trailing comma in parentheses
        ("zone,(,place)", False),  # Invalid: leading comma in parentheses
        ("zone, place", True),  # Valid: space after comma
        ("zone,[place , zone]", True),  # Valid: spaces around comma inside brackets
    ],
)
def test_validate_comma_syntax(display_options, expected):
    """Test the _validate_comma_syntax function to ensure it correctly validates comma usage in display_options.

    Parameters:
        display_options (str): The display options string to validate.
        expected (bool): The expected result of the validation.

    """
    errors = {}
    result = _validate_comma_syntax(display_options, errors)
    assert result is expected


@pytest.mark.parametrize(
    "display_options,expected",
    [
        ("zone,place", True),  # Valid: no spaces
        ("zone, place", True),  # Valid: space after comma is allowed
        ("zone name,place", False),  # Invalid: space in option name
        ("zone,[place,zone name]", False),  # Invalid: space in option name inside brackets
        ("zone,[place , zone]", True),  # Valid: spaces around comma inside brackets
        ("zone,place-name", True),  # Valid: dash allowed
        ("zone,place+name", True),  # Valid: plus allowed
        ("zone, place + name", False),  # Invalid: space in option name with plus
    ],
)
def test_validate_option_names(display_options, expected):
    """Test the _validate_option_names function to ensure it correctly validates option names in display_options.

    Parameters:
        display_options (str): The display options string to validate.
        expected (bool): The expected result of the validation.

    """
    errors = {}
    result = _validate_option_names(display_options, errors)
    assert result is expected
