"""Integration tests for display options rendering in the Places sensor."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.places.config_flow import PlacesConfigFlow
from custom_components.places.const import (
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_HOME_ZONE,
    CONF_NAME,
    CONF_SHOW_TIME,
    DOMAIN,
    EVENT_TYPE,
)
from custom_components.places.coordinator import PlacesUpdateCoordinator
from custom_components.places.persistence import PlacesStorage
from custom_components.places.update_sensor import PlacesUpdater

# Semantic location attributes used by the display-option cases below.
BASE_INTERNAL_ATTR = {
    "zone_name": "not_home",
    "zone": "not_home",
    "place_name": "Roy Spiegel MSW",
    "place_name_no_dupe": "Roy Spiegel MSW",
    "place_type": "house",
    "neighborhood": "Koreatown",
    "street_number": "1",
    "street": "Bridge Plaza North",
    "city_clean": "Fort Lee",
    "state_abbr": "NJ",
    "formatted_address": "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, New Jersey, 07024, United States",
}

README_PLACE_ADVANCED = (
    "name_no_dupe, category(-, place), type(-, yes), neighborhood, house_number, street"
)

README_FORMATTED_PLACE_ADVANCED = (
    "zone_name[driving, name_no_dupe[type(-, unclassified, category(-, highway))"
    "[category(-, highway)], house_number, route_number(type(+, motorway, trunk))"
    "[street[route_number]], neighborhood(type(house))], city_clean[county], state_abbr]"
)


async def render_display_option(
    mock_hass: MagicMock, monkeypatch: pytest.MonkeyPatch, display_option: str
) -> str | None:
    """Render one display option using the coordinator attribute snapshot.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        display_option (str):
            Display option rendered by the parametrized case.

    Returns:
        str | None:
            Rendered state produced for the selected display option.
    """
    mock_hass.states.get.return_value = None
    config_entry = MockConfigEntry(
        domain="places",
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test_iphone",
        },
    )
    persistence = MagicMock()
    persistence.async_save = AsyncMock()
    persistence.async_remove = AsyncMock()
    coordinator = PlacesUpdateCoordinator(
        mock_hass,
        config_entry,
        copy.deepcopy(BASE_INTERNAL_ATTR),
        persistence,
    )
    coordinator.clear_attr(ATTR_NATIVE_VALUE)
    coordinator.set_attr(CONF_DISPLAY_OPTIONS, display_option)
    coordinator.set_attr(ATTR_DISPLAY_OPTIONS, display_option)
    coordinator.set_attr(ATTR_DISPLAY_OPTIONS_LIST, [])
    monkeypatch.setattr(coordinator, "in_zone", AsyncMock(return_value=False), raising=False)
    monkeypatch.setattr(
        coordinator,
        "get_driving_status",
        AsyncMock(return_value=None),
        raising=False,
    )

    await coordinator.process_display_options()

    return coordinator.get_attr(ATTR_NATIVE_VALUE)


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_entity_registry")
@pytest.mark.parametrize(
    ("display_option", "expected_state"),
    [
        ("zone_name", "not_home"),
        (
            "zone, place",
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        (
            "zone_name, place",
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        ("formatted_place", "Roy Spiegel MSW, Fort Lee, NJ"),
        (
            "osm_formatted_address",
            (
                "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, "
                "New Jersey, 07024, United States"
            ),
        ),
        (
            README_PLACE_ADVANCED,
            "Roy Spiegel MSW, House, Koreatown, 1 Bridge Plaza North",
        ),
        (
            README_FORMATTED_PLACE_ADVANCED,
            "Roy Spiegel MSW, Fort Lee, NJ",
        ),
    ],
)
async def test_display_options_state_render(
    display_option: str,
    expected_state: str,
    mock_hass: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert that a CONF_DISPLAY_OPTIONS value renders the expected state.

    Args:
        display_option (str):
            Display option rendered by the parametrized case.
        expected_state (str):
            Entity state expected for this parametrized case.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
    state = await render_display_option(mock_hass, monkeypatch, display_option)

    assert state == expected_state


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_entity_registry")
async def test_basic_place_option_includes_neighborhood(
    mock_hass: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Basic place options should retain neighborhood context.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
    """
    basic_state = await render_display_option(mock_hass, monkeypatch, "place")

    assert basic_state
    assert "Koreatown" in basic_state


REPEATED_FALLBACK = (
    "name[city[county],country_code], type[city[county],country_code], "
    "house_number, street, state_abbr"
)
LONG_RULE = f"{REPEATED_FALLBACK}, name(-, {'x' * MAX_LENGTH_STATE_STATE})"
REPEATED_STATE = "Bergen County, US, Bergen County, US, 1 Bridge Plaza North, NJ"
FALLBACK_PLACE = {
    "county": "Bergen County",
    "country_code": "US",
    "street_number": "1",
    "street": "Bridge Plaza North",
    "state_abbr": "NJ",
}
FILTERED_FALLBACK = (
    "place_type[city_clean[county], house_number, street](+, city, category(building)), "
    "neighborhood(-, city)[postal_town[]], state_abbr"
)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("rule", "place", "expected"),
    [
        (REPEATED_FALLBACK, FALLBACK_PLACE, REPEATED_STATE),
        (LONG_RULE, FALLBACK_PLACE, REPEATED_STATE),
        (
            "name[house_number, neighborhood, street], type[house_number, neighborhood, street]",
            FALLBACK_PLACE,
            "1 Bridge Plaza North, 1 Bridge Plaza North",
        ),
        (
            "name(+, city[county])[street]",
            FALLBACK_PLACE | {"place_name": "Corner Cafe"},
            "Bridge Plaza North",
        ),
        (
            "name(-, city[county])[street]",
            FALLBACK_PLACE | {"place_name": "City[County]"},
            "Bridge Plaza North",
        ),
        (
            "name(category(city[county]))[street]",
            FALLBACK_PLACE | {"place_name": "Corner Cafe", "place_category": "city[county]"},
            "Corner Cafe",
        ),
        (
            "name[street]city(house), state_abbr",
            FALLBACK_PLACE | {"place_name": "Corner Cafe"},
            "Corner Cafe",
        ),
        (
            "name[city[street]city(house), county], state_abbr",
            FALLBACK_PLACE | {"city": "Fort Lee"},
            "Fort Lee, NJ",
        ),
        (
            FILTERED_FALLBACK,
            FALLBACK_PLACE | {"place_type": "city", "place_category": "building"},
            "City, NJ",
        ),
        (
            FILTERED_FALLBACK,
            FALLBACK_PLACE
            | {
                "place_type": "house",
                "place_category": "building",
                "city_clean": "Fort Lee",
                "neighborhood": "city",
                "postal_town": "Edgewater",
            },
            "Fort Lee, 1 Bridge Plaza North, Edgewater, NJ",
        ),
        (
            FILTERED_FALLBACK,
            FALLBACK_PLACE
            | {"place_type": "city", "place_category": "highway", "neighborhood": "Koreatown"},
            "Bergen County, 1 Bridge Plaza North, Koreatown, NJ",
        ),
        (
            README_FORMATTED_PLACE_ADVANCED,
            BASE_INTERNAL_ATTR
            | {
                "place_name_no_dupe": None,
                "place_type": "unclassified",
                "place_category": "building",
            },
            "Building, 1 Bridge Plaza North, Fort Lee, NJ",
        ),
        (
            "formatted_place, driving",
            BASE_INTERNAL_ATTR | {"place_type": "motorway", "place_category": "highway"},
            "Driving, Roy Spiegel MSW, Fort Lee, NJ",
        ),
        (
            "formatted_place, driving",
            BASE_INTERNAL_ATTR | {"zone": "work", "zone_name": "Work"},
            "Work",
        ),
    ],
    ids=(
        "repeated-fallback",
        "long-rule",
        "repeated-address-with-omitted-field",
        "bracketed-include-miss",
        "bracketed-exclude-match",
        "bracketed-attribute-match",
        "post-fallback-token",
        "nested-post-fallback-token",
        "matching-primary",
        "literal-mismatch",
        "attribute-mismatch",
        "documented-rule",
        "formatted-place-driving",
        "formatted-place-in-zone",
    ),
)
async def test_config_flow_renders_restored_place(
    hass: HomeAssistant, rule: str, place: dict[str, str | None], expected: str
) -> None:
    """Render the accepted config flow rule against restored Place data.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the Places entry.
        rule (str): Display options submitted to the config flow.
        place (dict[str, str | None]): Place data restored from Store.
        expected (str): Main sensor state produced from the accepted rule.
    """
    flow = PlacesConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user(
        {
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_DISPLAY_OPTIONS: rule,
            CONF_SHOW_TIME: False,
        }
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=result["data"])
    entry.add_to_hass(hass)
    await PlacesStorage(hass, entry.entry_id, "Test Place").async_save(
        place | {ATTR_NATIVE_VALUE: "Earlier display text"}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_place")
    assert state is not None
    assert state.state == expected


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("rule", "expected_formatted"),
    [
        ("zone_name[city, driving, county]", "Driving, Bergen County"),
        ("zone_name[driving, county]", "Bergen County"),
    ],
)
async def test_display_options_event_driving(
    hass: HomeAssistant, rule: str, expected_formatted: str
) -> None:
    """Publish the main sensor state and the established Formatted place event value.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the Places entry.
        rule (str): Advanced display options for a Place outside a zone.
        expected_formatted (str): Formatted place value in the state-update event.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_DISPLAY_OPTIONS: rule,
            CONF_SHOW_TIME: False,
        },
    )
    entry.add_to_hass(hass)
    await PlacesStorage(hass, entry.entry_id, "Test Place").async_save(
        {
            "zone": "not_home",
            "place_category": "highway",
            "place_type": "motorway",
            "county": "Bergen County",
            ATTR_NATIVE_VALUE: "Earlier display text",
        }
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state("sensor.test_place", "Driving, Bergen County")

    events: list[Event] = []
    hass.bus.async_listen_once(EVENT_TYPE, events.append)
    await PlacesUpdater(hass, entry, entry.runtime_data).fire_event_data("")
    await hass.async_block_till_done()

    assert events[0].data["to_state"] == "Driving, Bergen County"
    assert events[0].data["formatted_place"] == expected_formatted


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_display_options_entity_edits_and_reload(hass: HomeAssistant) -> None:
    """Re-render a valid runtime edit immediately and retain it after rejection and reload.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the Places entry.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_DISPLAY_OPTIONS: "county",
            CONF_SHOW_TIME: False,
        },
    )
    entry.add_to_hass(hass)
    text_id = (
        er.async_get(hass)
        .async_get_or_create(
            "text",
            DOMAIN,
            f"{entry.entry_id}_{CONF_DISPLAY_OPTIONS}",
            suggested_object_id="test_place_display_options",
            config_entry=entry,
            disabled_by=None,
        )
        .entity_id
    )
    storage = PlacesStorage(hass, entry.entry_id, "Test Place")
    earlier_snapshot = FALLBACK_PLACE | {ATTR_NATIVE_VALUE: "Bergen County"}
    await storage.async_save(earlier_snapshot)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state("sensor.test_place", "Bergen County")

    await hass.services.async_call(
        "text", "set_value", {"entity_id": text_id, "value": REPEATED_FALLBACK}, blocking=True
    )
    assert entry.data[CONF_DISPLAY_OPTIONS] == REPEATED_FALLBACK
    assert hass.states.is_state("sensor.test_place", REPEATED_STATE)

    with pytest.raises(HomeAssistantError, match="Invalid display options"):
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": text_id, "value": "name(category_missing(building))[city[county]]"},
            blocking=True,
        )
    assert entry.data[CONF_DISPLAY_OPTIONS] == REPEATED_FALLBACK
    assert hass.states.is_state("sensor.test_place", REPEATED_STATE)

    await storage.async_save(earlier_snapshot)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state("sensor.test_place", REPEATED_STATE)

    # The options flow accepts the same nested rule with a literal that exceeds
    # the configuration text entity's maximum state length.
    hass.states.async_set("device_tracker.test", "not_home")
    hass.states.async_set("zone.home", "0")
    options_form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        options_form["flow_id"],
        {
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_HOME_ZONE: "zone.home",
            CONF_DISPLAY_OPTIONS: LONG_RULE,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data[CONF_DISPLAY_OPTIONS] == LONG_RULE
    assert hass.states.is_state("sensor.test_place", REPEATED_STATE)
