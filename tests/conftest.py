"""Pytest fixtures and mock classes for testing Home Assistant integrations."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, Mock

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import homeassistant.helpers.entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import CONF_DEVICETRACKER_ID, CONF_NAME
from custom_components.places.coordinator import PlacesUpdateCoordinator
from custom_components.places.sensor import Places
from custom_components.places.update_sensor import PlacesUpdater

# Sentinel value that callers may use to indicate a previous attribute should be removed
RESTORE_PREVIOUS_ATTR_REMOVE = object()

type Attrs = dict[str, object]
type StubMock = AsyncMock | MagicMock
type MethodSpec = tuple[str, dict[str, object]]
type StubMapping = dict[str, StubMock]


def mock_method(default_func: Callable[..., object]) -> Mock:
    """Return a Mock that calls default_func when not overridden by side_effect/return_value.

    This preserves previous tests' ability to set `.side_effect` or `.return_value` while
    defaulting to calling `default_func` when neither is provided.
    """
    m = Mock()
    # Use a unique sentinel so tests can explicitly set `m.return_value = None`
    # while leaving the sentinel meaning "no explicit return set". Mock() by
    # default provides a Mock as return_value, so initialize to the sentinel to
    # allow our side_effect to call `default_func` unless a test provided an
    # explicit return value (including `None`).
    no_return = object()
    m.return_value = no_return

    # Use a side_effect that prefers a user-set non-None return_value, but
    # otherwise falls back to calling the provided default function. If a test
    # sets .side_effect on the mock after creation, that will override this.
    def _side_effect(*args: object, **kwargs: object) -> object:
        """Dispatch to an explicit mock return value or the default implementation.

        Args:
            *args: Positional arguments passed to the mock.
            **kwargs: Keyword arguments passed to the mock.

        Returns:
            The mock's configured return value, or ``default_func`` evaluated
            with the same arguments.
        """
        # If the test explicitly set a return_value (including None), return it.
        # If return_value is still the sentinel, call the provided default func.
        ret = getattr(m, "return_value", no_return)
        if ret is not no_return:
            return ret
        return default_func(*args, **kwargs)

    m.side_effect = _side_effect
    return m


class MockSensor:
    """Lightweight mock sensor entity with attribute helpers used by tests."""

    def __init__(
        self,
        attrs: Attrs | None = None,
        display_options_list: Sequence[str] | None = None,
        blank_attrs: set[str] | None = None,
        in_zone: bool = False,
    ) -> None:
        """Create a MockSensor with optional attrs, display options, blank attrs, and zone flag."""
        self.attrs = attrs or {}
        self.display_options_list = display_options_list or []
        self.blank_attrs = blank_attrs or set()
        self._in_zone = in_zone
        self.native_value = None
        self.entity_id = "sensor.test"
        self.warn_if_device_tracker_prob = False

        # get_attr: MagicMock with fallback to real attribute lookup
        def _get_attr_fallback(key: str) -> object:
            """Return the stored test attribute for a key.

            Args:
                key: Attribute name requested by production code.

            Returns:
                Stored attribute value, or ``None`` when it has not been set.
            """
            return self.attrs.get(key)

        self.get_attr = MagicMock(side_effect=_get_attr_fallback)

        # Custom is_attr_blank: MagicMock with default side_effect
        def _is_attr_blank_default(attr: str) -> bool:
            """Apply the mock sensor's blank-value rules for an attribute.

            Args:
                attr: Attribute name to inspect.

            Returns:
                ``True`` when the attribute is explicitly blanked, missing,
                ``None``, or an empty string.
            """
            if hasattr(self, "blank_attrs") and attr in self.blank_attrs:
                return True
            val = self.attrs.get(attr)
            if isinstance(val, MagicMock):
                return False
            return val is None or val == ""

        self.is_attr_blank = MagicMock(side_effect=_is_attr_blank_default)

        # Custom get_attr_safe_str: mock_method
        def _get_attr_safe_str_default(attr: str, default: object = None) -> str:
            """Coerce a stored mock attribute to the string form used by the sensor.

            Args:
                attr: Attribute name to read.
                default: Value to use when the attribute is missing or ``None``.

            Returns:
                String representation of the stored value or default, with
                MagicMock placeholders treated as blank values.
            """
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

        self.get_attr_safe_str = mock_method(_get_attr_safe_str_default)

        # Custom get_attr_safe_float: mock_method
        def _get_attr_safe_float_default(attr: str, default: object = None) -> float:
            """Coerce a stored mock attribute to a float like the real helper.

            Args:
                attr: Attribute name to read.
                default: Fallback value when conversion cannot use the stored
                    value.

            Returns:
                Converted float value, or ``0.0`` when neither the stored value
                nor the fallback can be converted.
            """
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if isinstance(default, int | float | str) else 0.0
            try:
                return float(val)
            except TypeError, ValueError:
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if isinstance(default, int | float | str) else 0.0

        self.get_attr_safe_float = mock_method(_get_attr_safe_float_default)

        # Custom get_attr_safe_dict: mock_method
        def _get_attr_safe_dict_default(
            attr: str, default: Mapping[str, object] | None = None
        ) -> Mapping[str, object]:
            """Return a stored mapping attribute with production-like fallback behavior.

            Args:
                attr: Attribute name to read.
                default: Fallback mapping when the stored value is not a dict.

            Returns:
                Stored mapping value, a dict fallback, or an empty dict.
            """
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return {} if not isinstance(default, dict) else default
            return val if isinstance(val, dict) else (default if isinstance(default, dict) else {})

        self.get_attr_safe_dict = mock_method(_get_attr_safe_dict_default)

        # Custom get_attr_safe_list: mock_method
        def _get_attr_safe_list_default(
            attr: str, default: Sequence[object] | None = None
        ) -> Sequence[object]:
            """Return a stored sequence attribute with display-options handling.

            Args:
                attr: Attribute name to read.
                default: Fallback sequence when the stored value is not a list.

            Returns:
                The configured display options, a stored list, a list fallback,
                or an empty list.
            """
            if attr == "display_options_list":
                return self.display_options_list
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return [] if not isinstance(default, list) else default
            return val if isinstance(val, list) else (default if isinstance(default, list) else [])

        self.get_attr_safe_list = mock_method(_get_attr_safe_list_default)
        # Custom set_attr: updates attrs and records calls
        self._set_attr_mock = MagicMock()

        def set_attr(key: str, value: object) -> None:
            """Store an attribute value and record the call for assertions.

            Args:
                key: Attribute name to set.
                value: Value to store on the mock sensor.
            """
            self.attrs[key] = value
            self._set_attr_mock(key, value)

        self.set_attr = MagicMock(side_effect=set_attr)
        self.set_attr.call_args_list = self._set_attr_mock.call_args_list
        self.set_attr.assert_any_call = self._set_attr_mock.assert_any_call
        self.set_attr.assert_not_called = self._set_attr_mock.assert_not_called
        # Custom clear_attr: removes key from attrs and records calls
        self._clear_attr_mock = MagicMock()

        def clear_attr(key: str) -> None:
            """Remove an attribute value and record the call for assertions.

            Args:
                key: Attribute name to remove from the mock sensor.
            """
            self.attrs.pop(key, None)
            self._clear_attr_mock(key)

        self.clear_attr = MagicMock(side_effect=clear_attr)
        self.clear_attr.call_args_list = self._clear_attr_mock.call_args_list
        self.clear_attr.assert_called_once_with = self._clear_attr_mock.assert_called_once_with
        self.clear_attr.assert_called = self._clear_attr_mock.assert_called
        # Custom set_native_value: sets native_value and records calls
        self._set_native_value_mock = MagicMock()

        def set_native_value(value: object) -> None:
            """Store the mock sensor's native value and record the call.

            Args:
                value: Native value to expose from the mock sensor.
            """
            self.native_value = value
            self._set_native_value_mock(value)

        self.set_native_value = MagicMock(side_effect=set_native_value)
        self.set_native_value.call_args_list = self._set_native_value_mock.call_args_list
        self.set_native_value.assert_any_call = self._set_native_value_mock.assert_any_call
        self.async_cleanup_attributes = AsyncMock()
        self.restore_previous_attr = AsyncMock(side_effect=self._restore_previous_attr)
        self.async_persist_attributes = AsyncMock()
        self.publish_update = MagicMock()
        self.get_internal_attr = lambda: self.attrs

    def _set_attr(self, key: str, value: object) -> None:
        """Set an attribute directly without recording a MagicMock call.

        Args:
            key: Attribute name to set.
            value: Value to store on the mock sensor.
        """
        self.attrs[key] = value

    def _set_native_value(self, value: object) -> None:
        """Set the native value directly without recording a MagicMock call.

        Args:
            value: Native value to store on the mock sensor.
        """
        self.native_value = value

    def _clear_attr(self, key: str | None = None) -> None:
        """Remove the specified key from attrs if present."""
        if key is not None and key in self.attrs:
            self.attrs.pop(key)

    async def _restore_previous_attr(self, *args: object, **kwargs: object) -> None:
        """Restore previous attribute values on this mock sensor.

        This helper is used by tests to simulate restoring attribute state after an
        update/rollback. It accepts either:

        - A single mapping (e.g., a dict) as the first positional argument, and/or
          keyword arguments: all key/value pairs from the mapping and kwargs will
          be applied to ``self.attrs`` via ``update()``.

        - A (key, previous_value) pair as two positional arguments: the sensor's
          ``self.attrs[key]`` will be set to ``previous_value``. If
          ``previous_value`` is the module-level sentinel
          ``RESTORE_PREVIOUS_ATTR_REMOVE``, the key will instead be removed from
          ``self.attrs``.

        The method is async to match callers that ``await`` the mocked
        ``restore_previous_attr`` (the public attribute is an ``AsyncMock`` whose
        side_effect points here).
        """
        # If a mapping-like first arg is provided, merge it into attrs.
        if args:
            first = args[0]
            # Mapping case: update attrs with provided mapping
            if isinstance(first, Mapping):
                # Best-effort: try to convert and update; ignore expected bad mapping data.
                with suppress(TypeError, ValueError, AttributeError):
                    self.attrs.update(first)
                # Also apply any kwargs
                if kwargs:
                    self.attrs.update(kwargs)
                return

            # Pair case: (key, previous_value)
            if len(args) >= 2:
                key, previous_value = args[0], args[1]
                if not isinstance(key, str):
                    return
                if previous_value is RESTORE_PREVIOUS_ATTR_REMOVE:
                    self.attrs.pop(key, None)
                else:
                    self.attrs[key] = previous_value
                return

        # If no positional args but kwargs provided, update attrs with kwargs
        if kwargs:
            self.attrs.update(kwargs)
            return

        # Nothing to do for other call shapes; keep as no-op.
        return

    async def in_zone(self) -> bool:
        """Return True if the sensor is in the configured zone, else False."""
        return self._in_zone


@pytest.fixture(name="mock_hass")
def mock_hass() -> MagicMock:
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
        return_value={
            "type": FlowResultType.FORM,
            "flow_id": "abc",
            "data_schema": MagicMock(),
        }
    )
    hass_instance.config_entries.options.async_configure = AsyncMock(
        return_value={"type": FlowResultType.CREATE_ENTRY}
    )
    # Services
    hass_instance.services = MagicMock()
    # Other commonly used attributes
    hass_instance.config = MagicMock()
    hass_instance.bus = MagicMock()
    hass_instance.states = MagicMock()
    hass_instance.data = {}
    hass_instance.async_add_executor_job = AsyncMock()
    # Prevent entity registry lookups from expecting a full HA runtime in unit tests.
    # Tests should use the `patch_entity_registry` fixture or monkeypatch to scope
    # any replacement methods to individual tests; do not assign it here
    # to avoid leaking state across tests.
    return hass_instance


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Provide a default Places config entry for unit tests."""
    return MockConfigEntry(
        domain="places",
        data={CONF_NAME: "Test Place", CONF_DEVICETRACKER_ID: "person.test"},
    )


@pytest.fixture
def places_instance(
    mock_hass: MagicMock,
    patch_entity_registry: object,
    mock_config_entry: MockConfigEntry,
) -> Places:
    """Provide a real Places sensor instance with minimal configuration."""
    _ = patch_entity_registry
    persistence = MagicMock()
    persistence.async_save = AsyncMock()
    persistence.async_remove = AsyncMock()
    coordinator = PlacesUpdateCoordinator(
        mock_hass,
        mock_config_entry,
        {},
        persistence,
    )
    mock_config_entry.runtime_data = coordinator
    return Places(coordinator)


class _DummyRegistry(er.EntityRegistry):
    """Minimal entity registry test double."""

    def __init__(self) -> None:
        """Avoid requiring a full Home Assistant instance for registry tests."""

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str) -> None:
        """Return no entity ID for tests that only need registry lookup isolation."""
        return


def _async_get_entity_registry(hass: HomeAssistant) -> er.EntityRegistry:
    """Return a minimal, typed dummy EntityRegistry for tests."""
    return _DummyRegistry()


def mock_sensor(
    attrs: Attrs | None = None,
    display_options_list: Sequence[str] | None = None,
    blank_attrs: set[str] | None = None,
    in_zone: bool = False,
) -> MockSensor:
    """Factory function that returns a configured MockSensor.

    Usage in tests:
        sensor = mock_sensor()
        sensor = mock_sensor(attrs={...}, in_zone=True)
    """
    return MockSensor(
        attrs=attrs,
        display_options_list=display_options_list,
        blank_attrs=blank_attrs,
        in_zone=in_zone,
    )


def assert_awaited_count(mock_obj: AsyncMock, expected: int) -> None:
    """Assert that an AsyncMock was awaited the expected number of times.

    This helper centralizes a readable assertion for await counts and produces a
    clearer failure message than direct integer comparisons in tests.
    """
    actual = getattr(mock_obj, "await_count", None)
    assert actual == expected, f"Expected await_count == {expected}, got {actual} for {mock_obj}"


@pytest.fixture
def sensor() -> MockSensor:
    """Provide a fresh MockSensor instance for tests via fixture."""
    return mock_sensor()


@pytest.fixture
def updater_instance(mock_hass: MagicMock) -> PlacesUpdater:
    """Provide a PlacesUpdater instance wired to the shared `mock_hass` and a fresh sensor."""
    sensor_obj = mock_sensor()
    return PlacesUpdater(mock_hass, MockConfigEntry(domain="places", data={}), sensor_obj)


@pytest.fixture
def updater(mock_hass: MagicMock) -> PlacesUpdater:
    """Provide a PlacesUpdater instance using the shared `mock_hass` and a fresh mock_sensor.

    Returns a PlacesUpdater constructed with a fresh mock_sensor.
    """
    sensor = mock_sensor()
    return PlacesUpdater(mock_hass, MockConfigEntry(domain="places", data={}), sensor)


@pytest.fixture
def prepared_updater(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Provide a MagicMock updater and patch PlacesUpdater to return it while recording init calls.

    The fixture returns the MagicMock instance. The fixture attaches an `_init_calls` list
    to the mock where each instantiation call's (args, kwargs) is appended. Tests can
    assert on `_init_calls` to verify instantiation parameters.
    """
    mock_updater = MagicMock()
    init_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _creator(*args: object, **kwargs: object) -> MagicMock:
        """Record constructor arguments and return the prepared updater mock.

        Args:
            *args: Positional constructor arguments passed by production code.
            **kwargs: Keyword constructor arguments passed by production code.

        Returns:
            The shared updater mock used by the test.
        """
        init_calls.append((args, kwargs))
        return mock_updater

    # Patch the PlacesUpdater constructor used in tests
    monkeypatch.setattr("custom_components.places.sensor.PlacesUpdater", _creator)
    # Attach the calls list for test assertions
    mock_updater._init_calls = init_calls
    return mock_updater


@pytest.fixture
def patch_entity_registry() -> Iterator[Callable[[HomeAssistant], er.EntityRegistry]]:
    """Patch er.async_get to return a minimal dummy EntityRegistry for the duration of a test.

    This fixture temporarily replaces the entity registry getter so tests that rely on a
    patched registry can run without requiring a full Home Assistant runtime.
    """
    original = er.async_get
    er.async_get = _async_get_entity_registry
    try:
        yield _async_get_entity_registry
    finally:
        er.async_get = original


def stub_in_zone(obj: object, return_value: bool) -> AbstractContextManager[StubMock]:
    """Return a context manager that temporarily stubs an object's async `in_zone` method.

    Usage:
        with stub_in_zone(sensor, False):
            await sensor.process_display_options()
    """
    # Use the generic stub_method helper to provide a context manager that
    # temporarily replaces `in_zone` with an AsyncMock and restores the
    # original attribute on exit.
    return stub_method(obj, "in_zone", return_value=return_value)


def stub_method(
    obj: object,
    method_name: str,
    *,
    return_value: object = None,
    side_effect: object = None,
    async_method: bool = True,
    restore_original: bool = True,
) -> AbstractContextManager[StubMock]:
    """Return a context manager that temporarily stubs an object's method.

    Parameters:
        obj: target object
        method_name: attribute name to patch
        return_value: value to return from the stub
        side_effect: callable to use as side_effect
        async_method: whether to patch with AsyncMock (True) or MagicMock (False)

    Usage:
        with stub_method(parser, "parse_type", return_value=None):
            await parser.parse_osm_dict()

    """
    # Create the appropriate mock object and assign it to the target attribute.
    if async_method:
        mocker = AsyncMock(return_value=return_value)
        if side_effect is not None:
            mocker.side_effect = side_effect
    else:
        mocker = MagicMock(return_value=return_value)
        if side_effect is not None:
            mocker.side_effect = side_effect

    # Use a simple context manager that attaches the mock to the object. By
    # default it preserves previous behavior and leaves the mock assigned so
    # tests may assert against the attribute after the with-block. If
    # `restore_original=True` is passed, the original attribute (if any) is
    # restored when the context exits to avoid leaking state across tests.
    @contextmanager
    def _cm() -> Iterator[StubMock]:
        """Temporarily replace a method on an object with a mock.

        Yields:
            The mock assigned to the target object.
        """
        # Save original state
        sentinel = object()
        original = getattr(obj, method_name, sentinel)
        setattr(obj, method_name, mocker)
        try:
            yield mocker
        finally:
            if restore_original:
                # Restore original attribute or remove if it didn't exist
                if original is sentinel:
                    # Best-effort deletion; ignore if something else changed it
                    with suppress(Exception):
                        delattr(obj, method_name)
                else:
                    # Best-effort restore; ignore failures to avoid masking test errors
                    with suppress(Exception):
                        setattr(obj, method_name, original)

    return _cm()


@pytest.fixture
def stubbed_updater() -> Callable[
    [object, Sequence[MethodSpec]], AbstractContextManager[StubMapping]
]:
    """Provide a helper that returns a context manager for stubbing multiple updater methods.

    Usage:
        with stubbed_updater(updater, [
            ("get_current_time", {"return_value": dt}),
            ("update_previous_state", {}),
        ]):
            await updater.do_update(...)

    Each tuple is (method_name, kwargs) where kwargs match stub_method's signature.
    """

    def _create(
        updater: object, methods: Sequence[MethodSpec]
    ) -> AbstractContextManager[StubMapping]:
        """Build a context manager that stubs several updater methods.

        Args:
            updater: Object whose methods should be patched.
            methods: Method names and stub configuration passed to
                ``stub_method``.

        Returns:
            Context manager yielding method names mapped to their mocks.
        """
        # Create context managers for each requested stub. Helpers now default to
        # restoring originals, so do not opt-out here; tests should capture the
        # returned mocks from the context.
        cms = [stub_method(updater, method_name, **kwargs) for method_name, kwargs in methods]

        @contextmanager
        def _cm() -> Iterator[StubMapping]:
            """Enter all updater method stubs and restore them on exit.

            Yields:
                Mapping from updater method name to its mock.
            """
            # Enter all context managers and yield a mapping of method_name->mock
            entered = [cm.__enter__() for cm in cms]
            mapping = {method_name: entered[i] for i, (method_name, _) in enumerate(methods)}
            try:
                yield mapping
            finally:
                # Ensure each context manager is exited to restore originals
                for cm in cms:
                    with suppress(Exception):
                        cm.__exit__(None, None, None)

        return _cm()

    return _create


def stubbed_parser(
    parser: object, methods: Sequence[MethodSpec]
) -> AbstractContextManager[StubMapping]:
    """Return a context manager for stubbing multiple parser methods.

    Usage:
        with stubbed_parser(parser, [("parse_type", {}), ("set_attribution", {})]):
            await parser.parse_osm_dict()
    """
    cms = [stub_method(parser, method_name, **kwargs) for method_name, kwargs in methods]

    @contextmanager
    def _cm() -> Iterator[StubMapping]:
        """Enter all parser method stubs and restore them on exit.

        Yields:
            Mapping from parser method name to its mock.
        """
        entered = [cm.__enter__() for cm in cms]
        mapping = {method_name: entered[i] for i, (method_name, _) in enumerate(methods)}
        try:
            yield mapping
        finally:
            for cm in cms:
                with suppress(Exception):
                    cm.__exit__(None, None, None)

    return _cm()


def stubbed_sensor(
    sensor_obj: object, methods: Sequence[MethodSpec]
) -> AbstractContextManager[StubMapping]:
    """Return a context manager for stubbing multiple sensor methods.

    Usage:
        with stubbed_sensor(sensor, [("process_display_options", {})]):
            await Places.process_display_options(sensor)
    """
    cms = [stub_method(sensor_obj, method_name, **kwargs) for method_name, kwargs in methods]

    @contextmanager
    def _cm() -> Iterator[StubMapping]:
        """Enter all sensor method stubs and restore them on exit.

        Yields:
            Mapping from sensor method name to its mock.
        """
        entered = [cm.__enter__() for cm in cms]
        mapping = {method_name: entered[i] for i, (method_name, _) in enumerate(methods)}
        try:
            yield mapping
        finally:
            for cm in cms:
                with suppress(Exception):
                    cm.__exit__(None, None, None)

    return _cm()
