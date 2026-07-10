"""Tests for Places button entities."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.places.button import PlacesForceUpdateButton, async_setup_entry


async def test_force_update_button_setup_and_press(mock_hass: HomeAssistant) -> None:
    """The entry exposes one button that delegates to its coordinator."""
    coordinator = MagicMock()
    coordinator.async_force_update = AsyncMock()
    entry = MagicMock()
    entry.runtime_data = coordinator
    async_add_entities = MagicMock()

    await async_setup_entry(mock_hass, entry, async_add_entities)

    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 1
    button = entities[0]
    assert isinstance(button, PlacesForceUpdateButton)
    assert button.entity_registry_enabled_default is False
    await button.async_press()
    coordinator.async_force_update.assert_awaited_once_with()
