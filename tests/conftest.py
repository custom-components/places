"""Pytest fixtures and mock classes for testing Home Assistant integrations."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class MockMethod:
    """Callable mock supporting a default function, return_value, and side_effect."""

    def __init__(self, default_func):
        """Initialize with a default callable used when no return_value/side_effect set."""
        self._default_func = default_func
        self.return_value = None
        self.side_effect = None

    def __call__(self, *args, **kwargs):
        """Invoke side_effect, return_value, or the default function with provided args."""
        if self.side_effect is not None:
            return self.side_effect(*args, **kwargs)
        if self.return_value is not None:
            return self.return_value
        return self._default_func(*args, **kwargs)


class MockSensor:
    """Lightweight mock sensor entity with attribute helpers used by tests."""

    def __init__(self, attrs=None, display_options_list=None, blank_attrs=None, in_zone=False):
        """Create a MockSensor with optional attrs, display options, blank attrs, and zone flag."""
        self.attrs = attrs or {}
        self.display_options_list = display_options_list or []
        self.blank_attrs = blank_attrs or set()
        self._in_zone = in_zone
        self.native_value = None
        self.entity_id = "sensor.test"
        self.warn_if_device_tracker_prob = False

        # get_attr: MagicMock with fallback to real attribute lookup
        def _get_attr_fallback(key):
            return self.attrs.get(key)

        self.get_attr = MagicMock(side_effect=_get_attr_fallback)

        # Custom is_attr_blank: MagicMock with default side_effect
        def _is_attr_blank_default(attr):
            if hasattr(self, "blank_attrs") and attr in self.blank_attrs:
                return True
            val = self.attrs.get(attr)
            if isinstance(val, MagicMock):
                return False
            return val is None or val == ""

        self.is_attr_blank = MagicMock(side_effect=_is_attr_blank_default)

        # Custom get_attr_safe_str: MockMethod
        def _get_attr_safe_str_default(attr, default=None):
            val = self.attrs.get(attr, default)
            # If val is a MagicMock, return default or empty string
            if isinstance(val, MagicMock):
                # If default is a MagicMock, return empty string
                if isinstance(default, MagicMock):
                    return ""
                return str(default) if default is not None else ""
            # If val is None, return default or empty string
            if val is None:
                if isinstance(default, MagicMock):
                    return ""
                return str(default) if default is not None else ""
            return str(val)

        self.get_attr_safe_str = MockMethod(_get_attr_safe_str_default)

        # Custom get_attr_safe_float: MockMethod
        def _get_attr_safe_float_default(attr, default=None):
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if default is not None else 0.0
            try:
                return float(val)
            except (TypeError, ValueError):
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if default is not None else 0.0

        self.get_attr_safe_float = MockMethod(_get_attr_safe_float_default)

        # Custom get_attr_safe_dict: MockMethod
        def _get_attr_safe_dict_default(attr, default=None):
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return {} if not isinstance(default, dict) else default
            return val if isinstance(val, dict) else (default if isinstance(default, dict) else {})

        self.get_attr_safe_dict = MockMethod(_get_attr_safe_dict_default)

        # Custom get_attr_safe_list: MockMethod
        def _get_attr_safe_list_default(attr, default=None):
            if attr == "display_options_list":
                return self.display_options_list
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return [] if not isinstance(default, list) else default
            return val if isinstance(val, list) else (default if isinstance(default, list) else [])

        self.get_attr_safe_list = MockMethod(_get_attr_safe_list_default)
        # Custom set_attr: updates attrs and records calls
        self._set_attr_mock = MagicMock()

        def set_attr(key, value):
            self.attrs[key] = value
            self._set_attr_mock(key, value)

        self.set_attr = set_attr
        self.set_attr.call_args_list = self._set_attr_mock.call_args_list
        self.set_attr.assert_any_call = self._set_attr_mock.assert_any_call
        self.set_attr.assert_not_called = self._set_attr_mock.assert_not_called
        # Custom clear_attr: removes key from attrs and records calls
        self._clear_attr_mock = MagicMock()

        def clear_attr(key):
            self.attrs.pop(key, None)
            self._clear_attr_mock(key)

        self.clear_attr = clear_attr
        self.clear_attr.call_args_list = self._clear_attr_mock.call_args_list
        self.clear_attr.assert_called_once_with = self._clear_attr_mock.assert_called_once_with
        self.clear_attr.assert_called = self._clear_attr_mock.assert_called
        # Custom set_native_value: sets native_value and records calls
        self._set_native_value_mock = MagicMock()

        def set_native_value(value):
            self.native_value = value
            self._set_native_value_mock(value)

        self.set_native_value = set_native_value
        self.set_native_value.call_args_list = self._set_native_value_mock.call_args_list
        self.set_native_value.assert_any_call = self._set_native_value_mock.assert_any_call
        self.async_cleanup_attributes = AsyncMock()
        self.restore_previous_attr = AsyncMock(side_effect=self._restore_previous_attr)
        self.get_internal_attr = lambda: self.attrs

    def _set_attr(self, key, value):
        self.attrs[key] = value

    def _set_native_value(self, value):
        self.native_value = value

    def _clear_attr(self, key=None):
        """Remove the specified key from attrs if present."""
        if key is not None and key in self.attrs:
            self.attrs.pop(key)

    def _restore_previous_attr(self, *args, **kwargs):
        """No-op placeholder for restoring previous attributes in tests."""

    def get_attr(self, key):
        """Return the attribute value for key or None."""
        return self.attrs.get(key)

    async def in_zone(self):
        """Return True if the sensor is in the configured zone, else False."""
        return self._in_zone


class MockState:
    """Simple mock of a Home Assistant state with entity_id and attributes."""

    def __init__(self, entity_id, attributes):
        """Store entity_id and attributes on the mock state."""
        self.entity_id = entity_id
        self.attributes = attributes


@pytest.fixture(name="mock_hass")
def mock_hass():
    """Provide a mock Home Assistant instance configured with common attributes."""
    hass_instance = MagicMock()
    # Config entries
    hass_instance.config_entries = MagicMock()
    hass_instance.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    # In Home Assistant this method is synchronous, so use MagicMock (AsyncMock caused un-awaited coroutine warnings in tests)
    hass_instance.config_entries.async_update_entry = MagicMock()
    hass_instance.config_entries.async_reload = AsyncMock()
    hass_instance.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    # Options mocks
    hass_instance.config_entries.options = MagicMock()
    hass_instance.config_entries.options.async_init = AsyncMock(
        return_value={"type": "form", "flow_id": "abc", "data_schema": MagicMock()}
    )
    hass_instance.config_entries.options.async_configure = AsyncMock(
        return_value={"type": "create_entry"}
    )
    # Services
    hass_instance.services = MagicMock()
    # Other commonly used attributes
    hass_instance.config = MagicMock()
    hass_instance.bus = MagicMock()
    hass_instance.states = MagicMock()
    hass_instance.data = {}
    hass_instance.async_add_executor_job = AsyncMock()
    return hass_instance


class FakeResp:
    """Fake aiohttp response exposing an async .text() method."""

    def __init__(self, text):
        """Store the response payload text."""
        self._text = text

    async def text(self):
        """Return the stored payload text."""
        return self._text


class FakeCM:
    """Async context manager that yields a FakeResp for use with "async with"."""

    def __init__(self, resp: FakeResp):
        """Create the context manager that will yield the provided FakeResp."""
        self._resp = resp

    async def __aenter__(self):
        """Return the underlying FakeResp when entering the async context."""
        return self._resp

    async def __aexit__(self, exc_type, exc, tb):
        """Exit the async context; do not suppress exceptions."""
        return False


class FakeSession:
    """Fake aiohttp ClientSession-like object for tests with async context support."""

    def __init__(self, resp: FakeResp, *a, **kw):
        """Store the FakeResp to be returned by get()."""
        self._resp = resp

    async def __aenter__(self):
        """Return the fake session when entering the async context."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit the async context; no cleanup performed."""
        return False

    def get(self, *a, **kw):
        """Return a FakeCM that yields the stored FakeResp when entered."""
        return FakeCM(self._resp)
