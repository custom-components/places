from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def hass():
    """Pytest fixture that provides a mock Home Assistant instance with commonly used attributes and asynchronous methods for testing integrations."""
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
        """Initialize a MockSensor instance with customizable attributes and zone status.

        Parameters:
            attrs (dict, optional): Dictionary of sensor attributes.
            display_options_list (list, optional): List of display options for the sensor.
            blank_attrs (set, optional): Set of attribute names considered blank.
            in_zone (bool, optional): Indicates if the sensor is in a zone. Defaults to False.

        """
        self.attrs = attrs or {}
        self.display_options_list = display_options_list or []
        self.blank_attrs = blank_attrs or set()
        self._in_zone = in_zone

    def is_attr_blank(self, attr):
        # Handles both blank_attrs and attrs for compatibility
        """Determine if a given attribute is considered blank.

        An attribute is considered blank if it is listed in `blank_attrs`, or if its value in `attrs` is `None` or an empty string.

        Parameters:
            attr (str): The name of the attribute to check.

        Returns:
            bool: True if the attribute is blank, False otherwise.

        """
        if hasattr(self, "blank_attrs") and attr in self.blank_attrs:
            return True
        val = self.attrs.get(attr)
        return val is None or val == ""

    def get_attr_safe_str(self, attr, default=None):
        """Safely retrieves the string value of a specified attribute.

        Returns the string representation of the attribute value if it exists and is not None; otherwise, returns an empty string.
        """
        val = self.attrs.get(attr, default)
        return str(val) if val is not None else ""

    def get_attr_safe_list(self, attr, default=None):
        """Safely retrieve a list attribute by name, returning an empty list if the value is not a list.

        If the attribute name is "display_options_list", returns the instance's `display_options_list` attribute. For other attribute names, returns the value from `attrs` if it is a list; otherwise, returns an empty list.
        """
        if attr == "display_options_list":
            return self.display_options_list
        return (
            self.attrs.get(attr, default) if isinstance(self.attrs.get(attr, default), list) else []
        )

    def get_attr(self, key):
        """Retrieve the value of the specified attribute key from the sensor's attributes.

        Parameters:
            key: The attribute name to retrieve.

        Returns:
            The value associated with the given key, or None if the key is not present.

        """
        return self.attrs.get(key)

    async def in_zone(self):
        """Asynchronously determine whether the sensor is currently in the designated zone.

        Returns:
            bool: True if the sensor is in the zone, False otherwise.

        """
        return self._in_zone
