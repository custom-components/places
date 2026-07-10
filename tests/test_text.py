"""Tests for Places text entities."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers.entity import EntityCategory

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
