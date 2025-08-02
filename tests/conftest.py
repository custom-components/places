from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def hass():
    """Canonical Home Assistant mock fixture with common attributes."""
    hass_instance = MagicMock()
    hass_instance.config_entries = MagicMock()
    hass_instance.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass_instance.config_entries.async_update_entry = AsyncMock()
    hass_instance.config_entries.async_reload = AsyncMock()
    # Add options mocks
    hass_instance.config_entries.options = MagicMock()
    hass_instance.config_entries.options.async_init = AsyncMock(
        return_value={"type": "form", "flow_id": "abc", "data_schema": MagicMock()}
    )
    hass_instance.config_entries.options.async_configure = AsyncMock(
        return_value={"type": "create_entry"}
    )
    hass_instance.services = MagicMock()
    return hass_instance
