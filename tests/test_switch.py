"""Tests for Places switch entities."""

from unittest.mock import AsyncMock, MagicMock, call

from homeassistant.helpers.entity import EntityCategory

from custom_components.places.switch import PlacesShowLastUpdatedSwitch, async_setup_entry


async def test_show_last_updated_switch_setup_and_update() -> None:
    """The disabled config switch exposes and updates suffix visibility."""
    coordinator = MagicMock()
    coordinator.get_attr.return_value = False
    coordinator.async_update_setting = AsyncMock()
    entry = MagicMock(runtime_data=coordinator)
    async_add_entities = MagicMock()

    await async_setup_entry(MagicMock(), entry, async_add_entities)

    entity = async_add_entities.call_args.args[0][0]
    assert isinstance(entity, PlacesShowLastUpdatedSwitch)
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.entity_registry_enabled_default is False
    assert entity.is_on is False

    await entity.async_turn_on()
    await entity.async_turn_off()

    assert coordinator.async_update_setting.await_args_list == [
        call("show_time", True),
        call("show_time", False),
    ]
