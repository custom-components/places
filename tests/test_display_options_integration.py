"""Integration tests for display options rendering in the Places sensor."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_NATIVE_VALUE,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_NAME,
)
from custom_components.places.coordinator import PlacesUpdateCoordinator

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
