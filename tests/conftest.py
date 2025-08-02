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


class MockSensor:
    def __init__(self, attrs=None, display_options_list=None, blank_attrs=None, in_zone=False):
        self.attrs = attrs or {}
        self.display_options_list = display_options_list or []
        self.blank_attrs = blank_attrs or set()
        self._in_zone = in_zone

    def is_attr_blank(self, attr):
        # Handles both blank_attrs and attrs for compatibility
        if hasattr(self, "blank_attrs") and attr in self.blank_attrs:
            return True
        val = self.attrs.get(attr)
        return val is None or val == ""

    def get_attr_safe_str(self, attr, default=None):
        val = self.attrs.get(attr, default)
        return str(val) if val is not None else ""

    def get_attr_safe_list(self, attr, default=None):
        if attr == "display_options_list":
            return self.display_options_list
        return (
            self.attrs.get(attr, default) if isinstance(self.attrs.get(attr, default), list) else []
        )

    def get_attr(self, key):
        return self.attrs.get(key)

    async def in_zone(self):
        return self._in_zone
