"""Tests for Places text entities."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import DOMAIN
from custom_components.places.coordinator import PlacesUpdateCoordinator
from custom_components.places.text import PlacesDisplayOptionsText, async_setup_entry


async def test_display_options_text_setup_and_update() -> None:
    """The disabled config text exposes and updates display options."""
    coordinator = MagicMock()
    coordinator.get_attr_safe_str.return_value = "zone_name, place"
    coordinator.async_update_setting = AsyncMock()
    entry = MagicMock(runtime_data=coordinator)
    async_add_entities = MagicMock()

    await async_setup_entry(MagicMock(), entry, async_add_entities)

    entity = async_add_entities.call_args.args[0][0]
    assert isinstance(entity, PlacesDisplayOptionsText)
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.entity_registry_enabled_default is False
    assert entity.native_value == "zone_name, place"

    await entity.async_set_value("formatted_place")

    coordinator.async_update_setting.assert_awaited_once_with("options", "formatted_place")


async def test_display_options_text_entity_enforces_max_length(mock_hass: MagicMock) -> None:
    """Display-options text entity should use shared validation for 255-char limits."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry123",
        data={"name": "TestSensor", "devicetracker_id": "person.test"},
    )
    coordinator = PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())
    coordinator.process_display_options = AsyncMock()
    coordinator.publish_update = MagicMock()
    coordinator.async_persist_attributes = AsyncMock()

    entity = PlacesDisplayOptionsText(coordinator)
    await entity.async_set_value("x" * MAX_LENGTH_STATE_STATE)

    with pytest.raises(HomeAssistantError, match="Invalid display options"):
        await entity.async_set_value("x" * (MAX_LENGTH_STATE_STATE + 1))

    assert coordinator.process_display_options.await_count == 1


def test_display_options_text_hides_legacy_overlong_state() -> None:
    """Legacy rules longer than HA's text-state limit remain stored but unexposed."""
    coordinator = MagicMock()
    coordinator.get_attr_safe_str.return_value = "x" * (MAX_LENGTH_STATE_STATE + 1)
    entity = PlacesDisplayOptionsText(coordinator)

    assert entity.native_value is None
