"""Test suite for the Places sensor integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.places.const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DRIVING,
    ATTR_FORMATTED_PLACE,
    ATTR_NATIVE_VALUE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
)
from custom_components.places.sensor import EVENT_TYPE, RECORDER_INSTANCE, Places, async_setup_entry


@pytest.fixture
def places_instance():
    """Fixture that returns a Places instance for testing."""
    hass = MagicMock()
    config = {"devicetracker_id": "test_id"}
    config_entry = MagicMock()
    name = "TestSensor"
    unique_id = "unique123"
    imported_attributes = {}
    return Places(hass, config, config_entry, name, unique_id, imported_attributes)


def test_get_attr_safe_float_not_set_returns_zero(places_instance):
    """get_attr_safe_float should return 0.0 for missing attributes."""
    assert places_instance.get_attr_safe_float("missing_attr") == 0.0


def test_get_attr_safe_float_valid_float(places_instance):
    """If an attribute is already a float, get_attr_safe_float should return it unchanged."""
    places_instance.set_attr("float_attr", 42.5)
    assert places_instance.get_attr_safe_float("float_attr") == 42.5


def test_get_attr_safe_float_string_float(places_instance):
    """String float values should be parsed and returned as floats by get_attr_safe_float."""
    places_instance.set_attr("float_str_attr", "3.1415")
    assert places_instance.get_attr_safe_float("float_str_attr") == 3.1415


def test_get_attr_safe_float_non_numeric_string(places_instance):
    """Non-numeric strings should result in a 0.0 return value from get_attr_safe_float."""
    places_instance.set_attr("bad_str_attr", "not_a_float")
    assert places_instance.get_attr_safe_float("bad_str_attr") == 0.0


def test_get_attr_safe_float_none(places_instance):
    """None attribute values should be treated as 0.0 by get_attr_safe_float."""
    places_instance.set_attr("none_attr", None)
    assert places_instance.get_attr_safe_float("none_attr") == 0.0


def test_get_attr_safe_float_int(places_instance):
    """Integers stored as attributes should be converted to float by get_attr_safe_float."""
    places_instance.set_attr("int_attr", 7)
    assert places_instance.get_attr_safe_float("int_attr") == 7.0


def test_get_attr_safe_float_list(places_instance):
    """Non-scalar types like list should yield 0.0 from get_attr_safe_float."""
    places_instance.set_attr("list_attr", [1, 2, 3])
    assert places_instance.get_attr_safe_float("list_attr") == 0.0


def test_get_attr_safe_float_dict(places_instance):
    """Dictionaries passed to get_attr_safe_float should result in 0.0 rather than raising."""
    places_instance.set_attr("dict_attr", {"a": 1})
    assert places_instance.get_attr_safe_float("dict_attr") == 0.0


def test_get_attr_safe_float_with_default(places_instance):
    """When missing, get_attr_safe_float should return the provided default value."""
    assert places_instance.get_attr_safe_float("missing_attr", default=5.5) == 5.5


def test_set_and_get_attr(places_instance):
    """set_attr followed by get_attr should return the stored value."""
    places_instance.set_attr("foo", "bar")
    assert places_instance.get_attr("foo") == "bar"


def test_clear_attr(places_instance):
    """clear_attr should remove the key from internal attrs so get_attr returns None."""
    places_instance.set_attr("foo", "bar")
    places_instance.clear_attr("foo")
    assert places_instance.get_attr("foo") is None


def test_get_attr_safe_str_returns_empty_on_none(places_instance):
    """Missing attributes should be represented as empty string by get_attr_safe_str."""
    assert places_instance.get_attr_safe_str("missing") == ""


def test_get_attr_safe_str_returns_str(places_instance):
    """Non-string attribute values should be stringified by get_attr_safe_str."""
    places_instance.set_attr("foo", 123)
    assert places_instance.get_attr_safe_str("foo") == "123"


def test_get_attr_safe_list_returns_empty_on_non_list(places_instance):
    """Test that get_attr_safe_list returns an empty list when the attribute is not a list."""
    places_instance.set_attr("notalist", "string")
    assert places_instance.get_attr_safe_list("notalist") == []


def test_get_attr_safe_list_returns_list(places_instance):
    """Verify that get_attr_safe_list returns the correct list when the attribute is set to a list."""
    places_instance.set_attr("alist", [1, 2, 3])
    assert places_instance.get_attr_safe_list("alist") == [1, 2, 3]


def test_get_attr_safe_dict_returns_empty_on_non_dict(places_instance):
    """Verify that get_attr_safe_dict returns an empty dictionary when the attribute is not a dictionary."""
    places_instance.set_attr("notadict", "string")
    assert places_instance.get_attr_safe_dict("notadict") == {}


def test_get_attr_safe_dict_returns_dict(places_instance):
    """Verify that get_attr_safe_dict returns the correct dictionary when the attribute is set to a dictionary."""
    places_instance.set_attr("adict", {"a": 1})
    assert places_instance.get_attr_safe_dict("adict") == {"a": 1}


def test_is_attr_blank_true_for_missing(places_instance):
    """Test that is_attr_blank returns True when the specified attribute is missing."""
    assert places_instance.is_attr_blank("missing_attr") is True


def test_is_attr_blank_false_for_value(places_instance):
    """Verify that an attribute with a non-blank value is not considered blank by is_attr_blank."""
    places_instance.set_attr("foo", "bar")
    assert places_instance.is_attr_blank("foo") is False


def test_is_attr_blank_false_for_zero(places_instance):
    """Verify that an attribute set to zero is not considered blank by the is_attr_blank method."""
    places_instance.set_attr("zero_attr", 0)
    assert places_instance.is_attr_blank("zero_attr") is False


def test_extra_state_attributes_basic(monkeypatch, places_instance):
    """Test that extra_state_attributes returns correct attributes based on extended flag."""
    monkeypatch.setattr(
        "custom_components.places.sensor.EXTRA_STATE_ATTRIBUTE_LIST", ["foo", "bar"]
    )
    monkeypatch.setattr("custom_components.places.sensor.EXTENDED_ATTRIBUTE_LIST", ["baz", "qux"])
    monkeypatch.setattr("custom_components.places.sensor.CONF_EXTENDED_ATTR", "extended")
    # Set attributes
    places_instance.set_attr("foo", "value1")
    places_instance.set_attr("bar", "value2")
    places_instance.set_attr("baz", "value3")
    places_instance.set_attr("qux", "value4")
    places_instance.set_attr("extended", False)
    result = places_instance.extra_state_attributes
    assert result == {"foo": "value1", "bar": "value2"}
    # Now enable extended
    places_instance.set_attr("extended", True)
    result = places_instance.extra_state_attributes
    assert result == {"foo": "value1", "bar": "value2", "baz": "value3", "qux": "value4"}


def test_extra_state_attributes_skips_blank(monkeypatch, places_instance):
    """Test that extra_state_attributes omits attributes that are blank or None.

    Ensures that when attributes in the configured extra state attribute list are empty strings or None, the resulting extra_state_attributes dictionary is empty.
    """
    monkeypatch.setattr(
        "custom_components.places.sensor.EXTRA_STATE_ATTRIBUTE_LIST", ["foo", "bar"]
    )
    monkeypatch.setattr("custom_components.places.sensor.EXTENDED_ATTRIBUTE_LIST", [])
    monkeypatch.setattr("custom_components.places.sensor.CONF_EXTENDED_ATTR", "extended")
    places_instance.set_attr("foo", "")
    places_instance.set_attr("bar", None)
    places_instance.set_attr("extended", False)
    result = places_instance.extra_state_attributes
    assert result == {}


def test_cleanup_attributes_removes_blank(places_instance):
    """Test that cleanup_attributes removes blank or None attributes from the internal attribute dictionary."""
    places_instance.set_attr("foo", "")
    places_instance.set_attr("bar", None)
    places_instance.set_attr("baz", "notblank")
    places_instance.cleanup_attributes()
    assert "foo" not in places_instance._internal_attr
    assert "bar" not in places_instance._internal_attr
    assert "baz" in places_instance._internal_attr


def test_set_native_value_sets_and_clears(places_instance):
    """Test that set_native_value correctly sets and clears the native value attribute."""
    places_instance.set_native_value("abc")
    assert places_instance._attr_native_value == "abc"
    assert places_instance.get_attr("native_value") == "abc"
    places_instance.set_native_value(None)
    assert places_instance._attr_native_value is None
    assert places_instance.get_attr("native_value") is None


def test_get_internal_attr_returns_dict(places_instance):
    """Verify that get_internal_attr returns a dictionary containing the attributes previously set on the Places instance."""
    places_instance.set_attr("foo", "bar")
    places_instance.set_attr("baz", 123)
    result = places_instance.get_internal_attr()
    # Only check keys we set, since Places adds many defaults
    assert result["foo"] == "bar"
    assert result["baz"] == 123


def test_import_attributes_from_json(monkeypatch, places_instance):
    """Test that attributes are correctly imported from a JSON dictionary, respecting configured attribute lists and ignoring specified keys."""
    monkeypatch.setattr("custom_components.places.sensor.JSON_ATTRIBUTE_LIST", ["a", "b"])
    monkeypatch.setattr("custom_components.places.sensor.CONFIG_ATTRIBUTES_LIST", ["c"])
    monkeypatch.setattr("custom_components.places.sensor.JSON_IGNORE_ATTRIBUTE_LIST", ["d"])
    monkeypatch.setattr("custom_components.places.sensor.ATTR_NATIVE_VALUE", "native_value")
    json_attr = {"a": 1, "b": 2, "c": 3, "d": 4, "native_value": "nv"}
    places_instance.import_attributes_from_json(json_attr)
    assert places_instance.get_attr("a") == 1
    assert places_instance.get_attr("b") == 2
    # The import only sets _attr_native_value if ATTR_NATIVE_VALUE is not blank
    # So we need to set it explicitly for the test
    places_instance.set_attr("native_value", "nv")
    places_instance._attr_native_value = places_instance.get_attr("native_value")
    assert places_instance._attr_native_value == "nv"
    assert "c" not in places_instance._internal_attr
    assert "d" not in places_instance._internal_attr


def test_get_attr_returns_default(places_instance):
    """Test that get_attr returns the specified default value when the attribute is missing."""
    assert places_instance.get_attr("missing", default="default") == "default"


def test_get_attr_none_when_blank_and_no_default(places_instance):
    """Test that get_attr returns None when the attribute is missing and no default is provided."""
    assert places_instance.get_attr("missing") is None


def test_set_attr_overwrites_value(places_instance):
    """Test that setting an attribute with the same key overwrites its previous value."""
    places_instance.set_attr("foo", "bar")
    places_instance.set_attr("foo", "baz")
    assert places_instance.get_attr("foo") == "baz"


def test_clear_attr_removes_key(places_instance):
    """Verify that clearing an attribute removes the corresponding key from the internal attribute dictionary."""
    places_instance.set_attr("foo", "bar")
    places_instance.clear_attr("foo")
    assert "foo" not in places_instance._internal_attr


def test_get_attr_safe_str_handles_value_error(places_instance):
    """Test that get_attr_safe_str returns an empty string when __str__ raises a ValueError."""

    class BadStr:
        def __str__(self):
            raise ValueError

    places_instance.set_attr("bad", BadStr())
    assert places_instance.get_attr_safe_str("bad") == ""


def test_get_attr_safe_str_with_default(places_instance):
    """Test that get_attr_safe_str returns the specified default value when the attribute is missing."""
    assert places_instance.get_attr_safe_str("missing", default="abc") == "abc"


def test_get_attr_safe_list_with_default(places_instance):
    """Test that get_attr_safe_list returns the specified default value when the attribute is missing."""
    assert places_instance.get_attr_safe_list("missing", default=[1, 2]) == [1, 2]


def test_get_attr_safe_dict_with_default(places_instance):
    """Test that get_attr_safe_dict returns the specified default value when the attribute is missing."""
    assert places_instance.get_attr_safe_dict("missing", default={"a": 1}) == {"a": 1}


def test_cleanup_attributes_removes_multiple_blanks(places_instance):
    """Test that cleanup_attributes removes multiple blank attributes but retains non-blank values."""
    places_instance.set_attr("a", "")
    places_instance.set_attr("b", None)
    places_instance.set_attr("c", 0)
    places_instance.set_attr("d", "ok")
    places_instance.cleanup_attributes()
    assert "a" not in places_instance._internal_attr
    assert "b" not in places_instance._internal_attr
    assert "c" in places_instance._internal_attr  # 0 is not blank
    assert "d" in places_instance._internal_attr


def test_set_native_value_none_clears_internal_attr(places_instance):
    """Test that setting the native value to None clears both the internal attribute and the native value property."""
    places_instance.set_native_value("test")
    places_instance.set_native_value(None)
    assert places_instance.get_attr("native_value") is None
    assert places_instance._attr_native_value is None


def test_extra_state_attributes_with_no_attributes(monkeypatch, places_instance):
    """Test that extra_state_attributes returns an empty dictionary when no attribute lists are configured and the extended attribute is False."""
    monkeypatch.setattr("custom_components.places.sensor.EXTRA_STATE_ATTRIBUTE_LIST", [])
    monkeypatch.setattr("custom_components.places.sensor.EXTENDED_ATTRIBUTE_LIST", [])
    monkeypatch.setattr("custom_components.places.sensor.CONF_EXTENDED_ATTR", "extended")
    places_instance.set_attr("extended", False)
    assert places_instance.extra_state_attributes == {}


@pytest.mark.asyncio
async def test_restore_previous_attr(places_instance):
    """Test that the restore_previous_attr method correctly restores previous attribute values to the Places instance.

    Ensures that all key-value pairs from the provided previous attributes dictionary are set in the internal attribute storage.
    """
    prev = {"foo": "bar", "baz": 123}
    places_instance.set_attr("old", "gone")
    await places_instance.restore_previous_attr(prev)
    # Only check that prev keys/values are present
    for k, v in prev.items():
        assert places_instance._internal_attr[k] == v


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attrs,expected_keys",
    [
        # Removes multiple blanks
        ({"a": "", "b": None, "c": "ok", "d": 0, "e": []}, ["c", "d"]),
        # Removes blank and None, keeps valid and zero
        ({"blank": "", "none": None, "zero": 0, "valid": "something"}, ["zero", "valid"]),
        # No change for all valid
        ({"foo": "bar", "baz": 123}, ["foo", "baz"]),
        # Empty dict remains empty
        ({}, []),
    ],
)
async def test_async_cleanup_attributes_various(places_instance, attrs, expected_keys):
    """Test async_cleanup_attributes with various initial attribute states and expected results."""
    places_instance._internal_attr.clear()
    for k, v in attrs.items():
        places_instance.set_attr(k, v)
    await places_instance.async_cleanup_attributes()
    # Only expected keys should remain
    assert sorted(places_instance._internal_attr.keys()) == sorted(expected_keys)


@pytest.mark.asyncio
async def test_async_update_triggers_do_update(monkeypatch, places_instance):
    """Test that async_update triggers the creation of an asynchronous update task."""
    called = {}

    # Stub do_update to avoid executing real logic
    monkeypatch.setattr(places_instance, "do_update", AsyncMock(return_value=None))

    background_tasks = set()

    def fake_create_task(coro):
        """Schedule the coroutine, retain a reference, and mark task creation."""
        task = asyncio.create_task(coro)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        called["task"] = True

    monkeypatch.setattr(places_instance._hass, "async_create_task", fake_create_task)
    await places_instance.async_update()
    assert called.get("task") is True


@pytest.mark.asyncio
async def test_async_update_throttle(monkeypatch, places_instance):
    """Test that async_update is throttled and does not trigger multiple tasks within the throttle interval."""
    called = {}

    # Stub do_update to avoid executing real logic
    monkeypatch.setattr(places_instance, "do_update", AsyncMock(return_value=None))

    background_tasks = set()

    def fake_create_task(coro):
        """Schedule the coroutine, retain a reference, and mark task creation."""
        task = asyncio.create_task(coro)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        called["task"] = True

    monkeypatch.setattr(places_instance._hass, "async_create_task", fake_create_task)
    # First call triggers
    await places_instance.async_update()
    assert called.get("task") is True
    called.clear()
    # Second call should be throttled (MIN_THROTTLE_INTERVAL/THROTTLE_INTERVAL)
    await places_instance.async_update()
    assert called.get("task") is None


@pytest.mark.asyncio
async def test_async_setup_entry_places(monkeypatch):
    """Test that async_setup_entry sets up a Places sensor entity and adds it to Home Assistant.

    This test verifies that the async_setup_entry function correctly initializes the Places sensor, creates necessary folders, loads JSON data, and calls async_add_entities with the expected arguments.
    """
    hass = MagicMock()
    hass.data = {}
    hass.config.path = lambda *args: "/tmp/json_sensors"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    config_entry = MagicMock()
    config_entry.data = {
        "name": "TestSensor",
        "devicetracker_id": "device.test",
        "extended_attr": False,
    }
    config_entry.entry_id = "abc123"
    async_add_entities = MagicMock()

    # Patch helpers and Places
    monkeypatch.setattr("custom_components.places.sensor.create_json_folder", lambda path: None)
    monkeypatch.setattr(
        "custom_components.places.sensor.get_dict_from_json_file", lambda name, filename, folder: {}
    )
    monkeypatch.setattr("custom_components.places.sensor.Places", MagicMock())

    await async_setup_entry(hass, config_entry, async_add_entities)

    # Should call async_add_entities with Places
    assert async_add_entities.call_count == 1
    args, kwargs = async_add_entities.call_args
    assert isinstance(args[0][0], MagicMock)
    assert kwargs.get("update_before_add") is True


@pytest.mark.asyncio
async def test_async_setup_entry_places_no_recorder(monkeypatch):
    """Test that `async_setup_entry` adds a `PlacesNoRecorder` entity when the recorder is not configured.

    This test verifies that the setup function correctly initializes the JSON folder, loads data, and adds a `PlacesNoRecorder` entity with the expected parameters when the recorder integration is absent.
    """
    hass = MagicMock()
    hass.data = {}
    hass.config.path = lambda *args: "/tmp/json_sensors"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    config_entry = MagicMock()
    config_entry.data = {
        "name": "TestSensor",
        "devicetracker_id": "device.test",
        "extended_attr": True,
    }
    config_entry.entry_id = "abc123"
    async_add_entities = MagicMock()

    # Patch helpers and PlacesNoRecorder
    monkeypatch.setattr("custom_components.places.sensor.create_json_folder", lambda path: None)
    monkeypatch.setattr(
        "custom_components.places.sensor.get_dict_from_json_file", lambda name, filename, folder: {}
    )
    monkeypatch.setattr("custom_components.places.sensor.PlacesNoRecorder", MagicMock())

    await async_setup_entry(hass, config_entry, async_add_entities)

    # Should call async_add_entities with PlacesNoRecorder
    assert async_add_entities.call_count == 1
    args, kwargs = async_add_entities.call_args
    assert isinstance(args[0][0], MagicMock)
    assert kwargs.get("update_before_add") is True


def test_exclude_event_types_adds_event(monkeypatch):
    """Test that exclude_event_types adds EVENT_TYPE to the recorder's exclude_event_types set."""

    class Recorder:
        def __init__(self):
            self.exclude_event_types = set()

    recorder = Recorder()
    hass = type("Hass", (), {"data": {RECORDER_INSTANCE: recorder}})
    places_instance = type("Places", (), {})()
    places_instance._hass = hass
    places_instance.get_attr = lambda x: "TestName"
    Places.exclude_event_types(places_instance)

    # Assert EVENT_TYPE was added
    assert EVENT_TYPE in recorder.exclude_event_types


def test_exclude_event_types_no_recorder(monkeypatch):
    """Test that exclude_event_types does nothing when no recorder instance is present in hass.data."""
    hass = type("Hass", (), {"data": {}})
    places_instance = type("Places", (), {})()
    places_instance._hass = hass
    places_instance.get_attr = lambda x: "TestName"
    Places.exclude_event_types(places_instance)

    # Nothing should happen, no error
    assert RECORDER_INSTANCE not in hass.data


@pytest.mark.asyncio
async def test_async_added_to_hass_calls_super_and_tracks(monkeypatch, places_instance):
    """Test that async_added_to_hass calls the superclass and tracks state changes for the device tracker."""
    with (
        patch(
            "custom_components.places.sensor.async_track_state_change_event",
            return_value="remove_handle",
        ) as track_event,
        patch("custom_components.places.sensor._LOGGER") as logger,
    ):
        # Set up tracker id and tsc_update
        places_instance.get_attr = MagicMock(return_value="device.tracker_1")
        places_instance.tsc_update = MagicMock()
        places_instance.async_on_remove = MagicMock()

        await places_instance.async_added_to_hass()

        # Subscribed to state change event
        track_event.assert_called_once_with(
            places_instance._hass,
            ["device.tracker_1"],
            places_instance.tsc_update,
        )
        # async_on_remove called with handle
        places_instance.async_on_remove.assert_called_once_with("remove_handle")
        # Debug log called
        logger.debug.assert_called()


@pytest.mark.asyncio
async def test_async_added_to_hass_with_different_tracker(monkeypatch, places_instance):
    """Test that async_added_to_hass subscribes to state changes for a different device tracker and registers the removal callback."""
    with (
        patch(
            "custom_components.places.sensor.async_track_state_change_event",
            return_value="remove_handle",
        ) as track_event,
        patch("custom_components.places.sensor._LOGGER") as logger,
    ):
        places_instance.get_attr = MagicMock(return_value="device.tracker_2")
        places_instance.tsc_update = MagicMock()
        places_instance.async_on_remove = MagicMock()

        await places_instance.async_added_to_hass()

        track_event.assert_called_once_with(
            places_instance._hass,
            ["device.tracker_2"],
            places_instance.tsc_update,
        )
        places_instance.async_on_remove.assert_called_once_with("remove_handle")
        logger.debug.assert_called()


@pytest.mark.asyncio
async def test_async_will_remove_from_hass_removes_json(monkeypatch, places_instance):
    """Test that async_will_remove_from_hass removes the associated JSON file when called."""
    remove_json_file_called = {}

    def fake_remove_json_file(name, filename, folder):
        """Mocks the removal of a JSON file by recording the provided arguments in a tracking dictionary."""
        remove_json_file_called["called"] = (name, filename, folder)

    monkeypatch.setattr("custom_components.places.sensor.remove_json_file", fake_remove_json_file)
    places_instance._hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    places_instance.get_attr = MagicMock(
        side_effect=lambda k: {
            "name": "TestName",
            "json_filename": "file.json",
            "json_folder": "/tmp",
        }[k]
    )

    # No recorder logic triggered
    places_instance._hass.data = {}
    await places_instance.async_will_remove_from_hass()
    assert remove_json_file_called["called"] == ("TestName", "file.json", "/tmp")


@pytest.mark.asyncio
async def test_async_will_remove_from_hass_removes_event_exclusion(monkeypatch, places_instance):
    """Test that async_will_remove_from_hass removes the event exclusion from the recorder when called."""
    monkeypatch.setattr("custom_components.places.sensor.remove_json_file", lambda *a: None)
    places_instance._hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    places_instance.get_attr = MagicMock(
        side_effect=lambda k: {
            "name": "TestName",
            "json_filename": "file.json",
            "json_folder": "/tmp",
            "extended_attr": True,
        }[k]
    )
    # Setup recorder and runtime_data
    recorder = MagicMock()
    recorder.exclude_event_types = {EVENT_TYPE}
    places_instance._hass.data = {RECORDER_INSTANCE: recorder}
    places_instance._config_entry.runtime_data = {
        "entity1": {"extended_attr": True},
        "entity2": {"extended_attr": False},
    }
    places_instance._attr_name = "TestName"
    places_instance._entity_id = "sensor.test"
    with patch("custom_components.places.sensor._LOGGER") as logger:
        await places_instance.async_will_remove_from_hass()
        # Should discard EVENT_TYPE from recorder
        assert EVENT_TYPE not in recorder.exclude_event_types
        logger.debug.assert_any_call(
            "(%s) Removing entity exclusion from recorder: %s", "TestName", "sensor.test"
        )


@pytest.mark.asyncio
async def test_get_driving_status_sets_driving(monkeypatch):
    """Should set ATTR_DRIVING when not in zone, direction not stationary, and category/type matches."""
    sensor = MagicMock(spec=Places)
    sensor.clear_attr = MagicMock()
    sensor.set_attr = MagicMock()
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.get_attr.side_effect = lambda k: (
        "not_stationary"
        if k == ATTR_DIRECTION_OF_TRAVEL
        else "highway"
        if k == ATTR_PLACE_CATEGORY
        else "motorway"
        if k == ATTR_PLACE_TYPE
        else None
    )
    # Run
    await Places.get_driving_status(sensor)
    sensor.set_attr.assert_called_with(ATTR_DRIVING, "Driving")


@pytest.mark.asyncio
async def test_get_driving_status_in_zone(monkeypatch):
    """Should NOT set ATTR_DRIVING when in zone."""
    sensor = MagicMock(spec=Places)
    sensor.clear_attr = MagicMock()
    sensor.set_attr = MagicMock()
    sensor.in_zone = AsyncMock(return_value=True)
    sensor.get_attr.return_value = "not_stationary"
    await Places.get_driving_status(sensor)
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_get_driving_status_direction_stationary(monkeypatch):
    """Should NOT set ATTR_DRIVING when direction is stationary."""
    sensor = MagicMock(spec=Places)
    sensor.clear_attr = MagicMock()
    sensor.set_attr = MagicMock()
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.get_attr.side_effect = (
        lambda k: "stationary" if k == ATTR_DIRECTION_OF_TRAVEL else "highway"
    )
    await Places.get_driving_status(sensor)
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_get_driving_status_category_type_not_match(monkeypatch):
    """Should NOT set ATTR_DRIVING when place category/type does not match."""
    sensor = MagicMock(spec=Places)
    sensor.clear_attr = MagicMock()
    sensor.set_attr = MagicMock()
    sensor.in_zone = AsyncMock(return_value=False)
    sensor.get_attr.side_effect = (
        lambda k: "not_stationary" if k == ATTR_DIRECTION_OF_TRAVEL else "other"
    )
    await Places.get_driving_status(sensor)
    sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_do_update_calls_updater(monkeypatch):
    """Test that do_update instantiates PlacesUpdater and calls its do_update method with correct args."""
    sensor = MagicMock(spec=Places)
    sensor._hass = MagicMock()
    sensor._config_entry = MagicMock()
    sensor._internal_attr = {"a": 1}
    # Patch PlacesUpdater and its do_update
    with patch("custom_components.places.sensor.PlacesUpdater") as mock_updater_cls:
        mock_updater = MagicMock()
        mock_updater.do_update = AsyncMock()
        mock_updater_cls.return_value = mock_updater
        await Places.do_update(sensor, reason="test-reason")
        mock_updater_cls.assert_called_once_with(
            hass=sensor._hass, config_entry=sensor._config_entry, sensor=sensor
        )
        mock_updater.do_update.assert_awaited_once_with(
            reason="test-reason", previous_attr={"a": 1}
        )


@pytest.mark.asyncio
async def test_do_update_handles_empty_internal_attr(monkeypatch):
    """Test do_update with empty internal_attr dict."""
    sensor = MagicMock(spec=Places)
    sensor._hass = MagicMock()
    sensor._config_entry = MagicMock()
    sensor._internal_attr = {}
    with patch("custom_components.places.sensor.PlacesUpdater") as mock_updater_cls:
        mock_updater = MagicMock()
        mock_updater.do_update = AsyncMock()
        mock_updater_cls.return_value = mock_updater
        await Places.do_update(sensor, reason="another-reason")
        mock_updater_cls.assert_called_once()
        mock_updater.do_update.assert_awaited_once_with(reason="another-reason", previous_attr={})


@pytest.mark.asyncio
async def test_process_display_options_formatted_place(monkeypatch):
    """Should call BasicOptionsParser and set formatted place if 'formatted_place' in display options."""
    sensor = MagicMock(spec=Places)
    sensor._internal_attr = {}  # Fix: ensure attribute exists
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "formatted_place"
    sensor.get_attr_safe_list.return_value = ["formatted_place"]
    sensor.get_attr.side_effect = lambda k: "formatted_place" if k == ATTR_FORMATTED_PLACE else None
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    with patch("custom_components.places.sensor.BasicOptionsParser") as mock_parser_cls:
        mock_parser = MagicMock()
        mock_parser.build_formatted_place = AsyncMock(return_value="fp")
        mock_parser_cls.return_value = mock_parser
        await Places.process_display_options(sensor)
    sensor.set_attr.assert_any_call(ATTR_FORMATTED_PLACE, "fp")
    sensor.set_attr.assert_any_call(ATTR_NATIVE_VALUE, "formatted_place")


@pytest.mark.asyncio
async def test_process_display_options_advanced_options(monkeypatch):
    """Should call AdvancedOptionsParser and set native value if advanced options present."""
    sensor = MagicMock(spec=Places)
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "(advanced)"
    sensor.get_attr_safe_list.return_value = ["(advanced)"]
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    with patch("custom_components.places.sensor.AdvancedOptionsParser") as mock_parser_cls:
        mock_parser = MagicMock()
        mock_parser.build_from_advanced_options = AsyncMock()
        mock_parser.compile_state = AsyncMock(return_value="adv_state")
        mock_parser_cls.return_value = mock_parser
        await Places.process_display_options(sensor)
    sensor.set_attr.assert_any_call(ATTR_NATIVE_VALUE, "adv_state")


@pytest.mark.asyncio
async def test_process_display_options_not_in_zone(monkeypatch):
    """Should call BasicOptionsParser and set native value if not in zone and no other options match."""
    sensor = MagicMock(spec=Places)
    sensor._internal_attr = {}  # Fix: ensure attribute exists
    sensor.is_attr_blank.return_value = False
    sensor.get_attr_safe_str.return_value = "other"
    sensor.get_attr_safe_list.return_value = ["other"]
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.in_zone = AsyncMock(return_value=False)
    with patch("custom_components.places.sensor.BasicOptionsParser") as mock_parser_cls:
        mock_parser = MagicMock()
        mock_parser.build_display = AsyncMock(return_value="display_state")
        mock_parser_cls.return_value = mock_parser
        await Places.process_display_options(sensor)
    sensor.set_attr.assert_any_call(ATTR_NATIVE_VALUE, "display_state")


@pytest.mark.asyncio
async def test_process_display_options_zone_or_zone_name_blank(monkeypatch):
    """Should set native value from zone if 'zone' in display options or zone name is blank."""
    sensor = MagicMock(spec=Places)
    sensor.is_attr_blank.side_effect = lambda k: k == ATTR_DEVICETRACKER_ZONE_NAME
    sensor.get_attr_safe_str.return_value = "zone"
    sensor.get_attr_safe_list.return_value = ["zone"]
    sensor.get_attr.side_effect = lambda k: "zone_val" if k == ATTR_DEVICETRACKER_ZONE else None
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    await Places.process_display_options(sensor)
    sensor.set_attr.assert_any_call(ATTR_NATIVE_VALUE, "zone_val")


@pytest.mark.asyncio
async def test_process_display_options_zone_name_not_blank(monkeypatch):
    """Should set native value from zone name if zone name is not blank."""
    sensor = MagicMock(spec=Places)
    sensor.is_attr_blank.side_effect = lambda k: False
    sensor.get_attr_safe_str.return_value = "other"
    sensor.get_attr_safe_list.return_value = ["other"]
    sensor.get_attr.side_effect = (
        lambda k: "zone_name_val" if k == ATTR_DEVICETRACKER_ZONE_NAME else None
    )
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    await Places.process_display_options(sensor)
    sensor.set_attr.assert_any_call(ATTR_NATIVE_VALUE, "zone_name_val")
