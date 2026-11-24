"""Integration tests for display options rendering in the Places sensor."""

from __future__ import annotations

from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_capture_events
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.places.config_flow import PlacesConfigFlow
from custom_components.places.const import (
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_HOME_ZONE,
    CONF_NAME,
    CONF_SHOW_TIME,
    DOMAIN,
    EVENT_TYPE,
)
from custom_components.places.persistence import PlacesStorage

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
NESTED_FILTER_WITH_SIBLINGS = "name(-,city,category(building,type(house)),type(cafe))[city]"
NESTED_FILTER_PLACE = {
    "place_name": "Corner Cafe",
    "place_category": "shop",
    "place_type": "cafe",
    "city": "Fort Lee",
}
REPEATED_FALLBACK_GROUP = "name[street][city], state_abbr"
REPEATED_FILTER_GROUP = "name(type(house))(type(city)), state_abbr"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("rule", "place", "expected"),
    [
        ("zone_name", BASE_INTERNAL_ATTR, "not_home"),
        (
            "zone, place",
            BASE_INTERNAL_ATTR,
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        (
            "zone_name, place",
            BASE_INTERNAL_ATTR,
            "not_home, Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North",
        ),
        ("formatted_place", BASE_INTERNAL_ATTR, "Roy Spiegel MSW, Fort Lee, NJ"),
        (
            "osm_formatted_address",
            BASE_INTERNAL_ATTR,
            (
                "Roy Spiegel MSW, 1, Bridge Plaza North, Koreatown, Fort Lee, Bergen County, "
                "New Jersey, 07024, United States"
            ),
        ),
        (
            README_PLACE_ADVANCED,
            BASE_INTERNAL_ATTR,
            "Roy Spiegel MSW, House, Koreatown, 1 Bridge Plaza North",
        ),
        (
            README_FORMATTED_PLACE_ADVANCED,
            BASE_INTERNAL_ATTR,
            "Roy Spiegel MSW, Fort Lee, NJ",
        ),
        ("place", BASE_INTERNAL_ATTR, "Roy Spiegel MSW, house, Koreatown, 1, Bridge Plaza North"),
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
            "name(category(type(house)))[city]",
            NESTED_FILTER_PLACE,
            "Corner Cafe",
        ),
        pytest.param(
            "name(type(house)(cafe), category(shop))[street]",
            NESTED_FILTER_PLACE,
            "Corner Cafe",
            id="malformed-repeated-attribute-group-skipped",
        ),
        (NESTED_FILTER_WITH_SIBLINGS, NESTED_FILTER_PLACE, "Corner Cafe"),
        (NESTED_FILTER_WITH_SIBLINGS, NESTED_FILTER_PLACE | {"place_name": "City"}, "Fort Lee"),
        (NESTED_FILTER_WITH_SIBLINGS, NESTED_FILTER_PLACE | {"place_type": "house"}, "Fort Lee"),
        (
            "name(-, city[county][state])[street], state_abbr",
            FALLBACK_PLACE | {"place_name": "City[County][State]"},
            "Bridge Plaza North, NJ",
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
        "zone-name",
        "raw-zone-and-place",
        "zone-name-and-place",
        "formatted-place",
        "osm-address",
        "advanced-place",
        "advanced-place-with-primary",
        "basic-place",
        "repeated-fallback",
        "long-rule",
        "repeated-address-with-omitted-field",
        "bracketed-include-miss",
        "bracketed-exclude-match",
        "bracketed-attribute-match",
        "unsupported-nested-filter",
        "malformed-repeated-attribute-group-skipped",
        "unsupported-nested-filter-with-matching-siblings",
        "unsupported-nested-filter-with-literal-exclusion",
        "unsupported-nested-filter-with-attribute-mismatch",
        "literal-repeated-brackets",
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
    "rule",
    [
        REPEATED_FALLBACK_GROUP,
        REPEATED_FILTER_GROUP,
        "name[street](type(house))[city], state_abbr",
        "name[city[street][county]], state_abbr",
    ],
    ids=("fallback", "filter", "mixed-order", "nested-fallback"),
)
async def test_options_flow_rejects_repeated_groups(hass: HomeAssistant, rule: str) -> None:
    """Show a syntax error and retain the saved rule when an edit repeats a group.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the options flow.
        rule (str): Submitted Display options containing a repeated group.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_DISPLAY_OPTIONS: "county",
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("device_tracker.test", "not_home")
    hass.states.async_set("zone.home", "0")

    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_DEVICETRACKER_ID: "device_tracker.test",
            CONF_HOME_ZONE: "zone.home",
            CONF_DISPLAY_OPTIONS: rule,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_syntax"}
    assert entry.data[CONF_DISPLAY_OPTIONS] == "county"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("rule", [REPEATED_FALLBACK_GROUP, REPEATED_FILTER_GROUP])
async def test_saved_repeated_groups_keep_legacy_rendering(hass: HomeAssistant, rule: str) -> None:
    """Render a previously saved rule with repeated groups on entry setup.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the Places entry.
        rule (str): Previously saved Display options containing a repeated group.
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
        FALLBACK_PLACE
        | {"place_name": "Corner Cafe", "place_type": "house", ATTR_NATIVE_VALUE: "Earlier text"}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state("sensor.test_place", "Corner Cafe")


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("rule", "expected_formatted"),
    [
        ("zone_name[city, driving, county]", "Driving, Bergen County"),
        ("zone_name[driving, county]", "Bergen County"),
    ],
)
async def test_display_options_event_driving(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    rule: str,
    expected_formatted: str,
) -> None:
    """Publish the main sensor state and the established Formatted place event value.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the Places entry.
        aioclient_mock (AiohttpClientMocker): Mocked reverse-geocode HTTP response.
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
            "county": "Hudson County",
            "latitude": 51.5,
            "longitude": -0.1,
            ATTR_NATIVE_VALUE: "Earlier display text",
        }
    )
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state("sensor.test_place", "Driving, Hudson County")

    events = async_capture_events(hass, EVENT_TYPE)
    aioclient_mock.get(
        "https://nominatim.openstreetmap.org/reverse",
        json={"category": "highway", "type": "motorway", "address": {"county": "Bergen County"}},
    )
    hass.states.async_set("device_tracker.test", "not_home", {"latitude": 51.7, "longitude": -0.1})
    await hass.async_block_till_done()

    assert hass.states.is_state("sensor.test_place", "Driving, Bergen County")
    (event,) = events
    assert event.data["to_state"] == "Driving, Bergen County"
    assert event.data["formatted_place"] == expected_formatted


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
