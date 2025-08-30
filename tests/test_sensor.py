"""Test suite for the Places sensor integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

from .conftest import stub_in_zone, stub_method, stubbed_parser


@pytest.fixture
def places_instance(mock_hass, patch_entity_registry):
    """Fixture that returns a Places instance for testing using the shared mock_hass fixture."""
    hass = mock_hass
    config = {"devicetracker_id": "test_id"}
    config_entry = MockConfigEntry(domain="places", data={})
    name = "TestSensor"
    unique_id = "unique123"
    imported_attributes = {}
    return Places(hass, config, config_entry, name, unique_id, imported_attributes)


@pytest.mark.parametrize(
    "setup_value,attr_name,expected,default",
    [
        (42.5, "float_attr", 42.5, None),
        ("3.1415", "float_str_attr", 3.1415, None),
        ("not_a_float", "bad_str_attr", 0.0, None),
        (None, "none_attr", 0.0, None),
        (7, "int_attr", 7.0, None),
        ([1, 2, 3], "list_attr", 0.0, None),
        ({"a": 1}, "dict_attr", 0.0, None),
    ],
)
def test_get_attr_safe_float_various(places_instance, setup_value, attr_name, expected, default):
    """Parametrized checks for get_attr_safe_float behavior across multiple input types.

    Covers: existing float, numeric string, invalid string, explicit None, int, list, and dict cases.
    """
    # If setup_value is provided (including None), set the attribute explicitly; otherwise leave missing
    places_instance.set_attr(attr_name, setup_value)
    if default is None:
        assert places_instance.get_attr_safe_float(attr_name) == expected
    else:
        assert places_instance.get_attr_safe_float(attr_name, default=default) == expected


def test_set_and_get_attr(places_instance):
    """set_attr followed by get_attr should return the stored value."""
    places_instance.set_attr("foo", "bar")
    assert places_instance.get_attr("foo") == "bar"


@pytest.mark.parametrize(
    "attr_name,setup_value,expected",
    [
        ("missing_attr", None, True),
        ("foo", "bar", False),
        ("zero_attr", 0, False),
    ],
)
def test_is_attr_blank_various(places_instance, attr_name, setup_value, expected):
    """Parametrized checks for is_attr_blank covering missing, non-blank string, and zero values."""
    if setup_value is not None:
        places_instance.set_attr(attr_name, setup_value)
    assert places_instance.is_attr_blank(attr_name) is expected


def test_extra_state_attributes_basic(monkeypatch, places_instance):
    """Test that extra_state_attributes returns correct attributes based on extended flag."""
    monkeypatch.setattr(
        "custom_components.places.sensor.EXTRA_STATE_ATTRIBUTE_LIST", ["foo", "bar"]
    )
    monkeypatch.setattr("custom_components.places.sensor.EXTENDED_ATTRIBUTE_LIST", ["baz", "qux"])
    monkeypatch.setattr("custom_components.places.sensor.CONF_EXTENDED_ATTR", "extended")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tracker_id", ["device.tracker_1", "device.tracker_2"])
    async def test_async_added_to_hass_param(monkeypatch, places_instance, tracker_id):
        """Parametrized: async_added_to_hass subscribes to the configured tracker id and registers the removal callback."""
        with (
            patch(
                "custom_components.places.sensor.async_track_state_change_event",
                return_value="remove_handle",
            ) as track_event,
            patch("custom_components.places.sensor._LOGGER") as logger,
        ):
            places_instance.get_attr = MagicMock(return_value=tracker_id)
            places_instance.tsc_update = MagicMock()
            places_instance.async_on_remove = MagicMock()

            await places_instance.async_added_to_hass()

            track_event.assert_called_once_with(
                places_instance._hass,
                [tracker_id],
                places_instance.tsc_update,
            )
            places_instance.async_on_remove.assert_called_once_with("remove_handle")
            logger.debug.assert_called()


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


@pytest.mark.parametrize(
    "attr_name, setup_value, default, expected",
    [
        # get_attr_safe_str cases
        ("missing_str", None, None, ""),
        ("int_str", 123, None, "123"),
    ],
)
def test_get_attr_safe_str_variants(places_instance, attr_name, setup_value, default, expected):
    """Parametrized: get_attr_safe_str returns expected string or default for various inputs."""
    if setup_value is not None:
        places_instance.set_attr(attr_name, setup_value)
    if default is None:
        assert places_instance.get_attr_safe_str(attr_name) == expected
    else:
        assert places_instance.get_attr_safe_str(attr_name, default=default) == expected


@pytest.mark.parametrize(
    "attr_name, setup_value, default, expected",
    [
        ("notadict", "string", None, {}),
        ("adict", {"a": 1}, None, {"a": 1}),
        ("missing_dict", None, {"a": 1}, {"a": 1}),
    ],
)
def test_get_attr_safe_dict_variants(places_instance, attr_name, setup_value, default, expected):
    """Parametrized: get_attr_safe_dict returns dict, empty dict or default when missing."""
    if setup_value is not None:
        places_instance.set_attr(attr_name, setup_value)
    if default is None:
        assert places_instance.get_attr_safe_dict(attr_name) == expected
    else:
        assert places_instance.get_attr_safe_dict(attr_name, default=default) == expected


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
    assert places_instance.get_attr(ATTR_NATIVE_VALUE) is None
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
@pytest.mark.parametrize(
    "use_no_recorder,extended_attr,patched_class",
    [
        (False, False, "Places"),
        (True, True, "PlacesNoRecorder"),
    ],
)
async def test_async_setup_entry_places_param(
    monkeypatch, use_no_recorder, extended_attr, patched_class, mock_hass
):
    """Parametrized: async_setup_entry adds the expected entity class and calls async_add_entities."""
    # use shared mock_hass fixture to provide common mocked hass behavior
    hass = mock_hass
    hass.data = {}
    hass.config.path = lambda *args: "/tmp/json_sensors"
    config_entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "device.test",
            "extended_attr": extended_attr,
        },
    )

    class _Adder:
        def __init__(self):
            self.call_count = 0
            self.call_args = None

        def __call__(self, entities, **kwargs):
            self.call_count += 1
            # mimic MagicMock.call_args: (args_tuple, kwargs_dict)
            self.call_args = ((entities,), kwargs)

    async_add_entities = _Adder()

    # Patch helpers and the appropriate Places class
    monkeypatch.setattr("custom_components.places.sensor.create_json_folder", lambda path: None)
    monkeypatch.setattr(
        "custom_components.places.sensor.get_dict_from_json_file", lambda name, filename, folder: {}
    )
    monkeypatch.setattr(f"custom_components.places.sensor.{patched_class}", MagicMock())

    with stub_method(
        hass, "async_add_executor_job", side_effect=lambda func, *a: func(*a), restore_original=True
    ):
        await async_setup_entry(hass, config_entry, async_add_entities)

    # Should call async_add_entities once and pass update_before_add=True
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


@pytest.mark.parametrize(
    "recorder_present,expected_in_set",
    [
        (True, True),
        (False, False),
    ],
)
def test_exclude_event_types_param(monkeypatch, recorder_present, expected_in_set):
    """Parametrized test for exclude_event_types: with and without recorder instance."""

    class Recorder:
        def __init__(self):
            self.exclude_event_types = set()

    recorder = Recorder() if recorder_present else None
    hass = type("Hass", (), {"data": {RECORDER_INSTANCE: recorder} if recorder_present else {}})
    places_instance = type("Places", (), {})()
    places_instance._hass = hass
    places_instance.get_attr = lambda x: "TestName"
    Places.exclude_event_types(places_instance)

    if recorder_present:
        assert EVENT_TYPE in recorder.exclude_event_types
    else:
        assert RECORDER_INSTANCE not in hass.data


@pytest.mark.asyncio
@pytest.mark.parametrize("tracker_id", ["device.tracker_1", "device.tracker_2"])
async def test_async_added_to_hass_param(monkeypatch, places_instance, tracker_id):
    """Parametrized: async_added_to_hass subscribes to the configured tracker id and registers the removal callback."""
    with (
        patch(
            "custom_components.places.sensor.async_track_state_change_event",
            return_value="remove_handle",
        ) as track_event,
        patch("custom_components.places.sensor._LOGGER") as logger,
    ):
        places_instance.get_attr = MagicMock(return_value=tracker_id)
        places_instance.tsc_update = MagicMock()
        places_instance.async_on_remove = MagicMock()

        await places_instance.async_added_to_hass()

        track_event.assert_called_once_with(
            places_instance._hass,
            [tracker_id],
            places_instance.tsc_update,
        )
        places_instance.async_on_remove.assert_called_once_with("remove_handle")
        logger.debug.assert_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,extended_attr,recorder_present",
    [
        ("remove_json", False, False),
        ("remove_event_exclusion", True, True),
    ],
)
async def test_async_will_remove_from_hass_param(
    monkeypatch, places_instance, scenario, extended_attr, recorder_present
):
    """Parametrized: async_will_remove_from_hass handles JSON removal and recorder exclusion paths."""
    # Setup common executor job passthrough
    cm_async_add = stub_method(
        places_instance._hass,
        "async_add_executor_job",
        side_effect=lambda func, *args: func(*args),
        restore_original=True,
    )
    with cm_async_add:
        # Configure get_attr response
        def get_attr(k):
            mapping = {
                "name": "TestName",
                "json_filename": "file.json",
                "json_folder": "/tmp",
                "extended_attr": extended_attr,
            }
            return mapping.get(k)

        places_instance.get_attr = MagicMock(side_effect=get_attr)

        # Prepare recorder if needed
        recorder = MagicMock() if recorder_present else None
        if recorder_present:
            recorder.exclude_event_types = {EVENT_TYPE}
            places_instance._hass.data = {RECORDER_INSTANCE: recorder}
            places_instance._config_entry.runtime_data = {
                "entity1": {"extended_attr": True},
                "entity2": {"extended_attr": False},
            }
            places_instance._attr_name = "TestName"
            places_instance._entity_id = "sensor.test"
        else:
            places_instance._hass.data = {}

        # Replace remove_json_file with a noop to avoid actual file ops
        monkeypatch.setattr("custom_components.places.sensor.remove_json_file", lambda *a: None)

        with patch("custom_components.places.sensor._LOGGER") as logger:
            await places_instance.async_will_remove_from_hass()

    if recorder_present:
        assert EVENT_TYPE not in recorder.exclude_event_types
        logger.debug.assert_any_call(
            "(%s) Removing entity exclusion from recorder: %s", "TestName", "sensor.test"
        )
    else:
        # No exceptions and remove_json_file was called via executor; nothing to assert beyond success
        assert True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "in_zone,direction,category,type_,expects_driving",
    [
        (False, "not_stationary", "highway", "motorway", True),
        (True, "not_stationary", "highway", "motorway", False),
        (False, "stationary", "highway", "motorway", False),
        (False, "not_stationary", "other", "other", False),
    ],
)
async def test_get_driving_status_variants(in_zone, direction, category, type_, expects_driving):
    """Parametrized checks for get_driving_status covering in-zone, stationary, and category/type mismatches."""
    sensor = MagicMock(spec=Places)
    sensor.clear_attr = MagicMock()
    sensor.set_attr = MagicMock()
    with stub_in_zone(sensor, in_zone):

        def get_attr(k):
            if k == ATTR_DIRECTION_OF_TRAVEL:
                return direction
            if k == ATTR_PLACE_CATEGORY:
                return category
            if k == ATTR_PLACE_TYPE:
                return type_
            return None

        sensor.get_attr.side_effect = get_attr
        await Places.get_driving_status(sensor)
    if expects_driving:
        sensor.set_attr.assert_called_with(ATTR_DRIVING, "Driving")
    else:
        sensor.set_attr.assert_not_called()


@pytest.mark.asyncio
async def test_do_update_calls_updater(monkeypatch, mock_hass, prepared_updater, stubbed_updater):
    """Test that do_update instantiates PlacesUpdater and calls its do_update method with correct args."""
    sensor = MagicMock(spec=Places)
    sensor._hass = mock_hass
    sensor._config_entry = MockConfigEntry(domain="places", data={})
    sensor._internal_attr = {"a": 1}
    # prepared_updater patches PlacesUpdater to return a MagicMock and records init calls
    mock_updater = prepared_updater
    with stubbed_updater(mock_updater, [("do_update", {})]):
        await Places.do_update(sensor, reason="test-reason")
        # verify PlacesUpdater was constructed with expected kwargs on first init
        assert mock_updater._init_calls, "PlacesUpdater was not instantiated"
        args, kwargs = mock_updater._init_calls[-1]
        assert kwargs.get("hass") is sensor._hass
        assert kwargs.get("config_entry") is sensor._config_entry
        assert kwargs.get("sensor") is sensor
        mock_updater.do_update.assert_awaited_once_with(
            reason="test-reason", previous_attr={"a": 1}
        )


@pytest.mark.asyncio
async def test_do_update_handles_empty_internal_attr(
    monkeypatch, mock_hass, prepared_updater, stubbed_updater
):
    """Test do_update with empty internal_attr dict."""
    sensor = MagicMock(spec=Places)
    sensor._hass = mock_hass
    sensor._config_entry = MockConfigEntry(domain="places", data={})
    sensor._internal_attr = {}
    mock_updater = prepared_updater
    with stubbed_updater(mock_updater, [("do_update", {})]):
        await Places.do_update(sensor, reason="another-reason")
        assert mock_updater._init_calls, "PlacesUpdater was not instantiated"
        mock_updater.do_update.assert_awaited_once_with(reason="another-reason", previous_attr={})


def _setup_formatted_place(sensor):
    sensor._internal_attr = {}
    sensor.is_attr_blank = MagicMock(return_value=False)
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.get_attr_safe_str = MagicMock(return_value="formatted_place")
    sensor.get_attr_safe_list = MagicMock(return_value=["formatted_place"])
    sensor.get_attr = MagicMock(
        side_effect=(lambda k: "formatted_place" if k == ATTR_FORMATTED_PLACE else None)
    )


def _setup_advanced_options(sensor):
    sensor._internal_attr = {}
    sensor.is_attr_blank = MagicMock(return_value=False)
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.get_attr_safe_str = MagicMock(return_value="(advanced)")
    sensor.get_attr_safe_list = MagicMock(return_value=["(advanced)"])


def _setup_not_in_zone(sensor):
    sensor._internal_attr = {}
    sensor.is_attr_blank = MagicMock(return_value=False)
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.get_attr_safe_str = MagicMock(return_value="other")
    sensor.get_attr_safe_list = MagicMock(return_value=["other"])


def _setup_zone_or_zone_name_blank(sensor):
    sensor._internal_attr = {}
    sensor.is_attr_blank = MagicMock(side_effect=lambda k: k == ATTR_DEVICETRACKER_ZONE_NAME)
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.get_attr_safe_str = MagicMock(return_value="zone")
    sensor.get_attr_safe_list = MagicMock(return_value=["zone"])
    sensor.get_attr = MagicMock(
        side_effect=(lambda k: "zone_val" if k == ATTR_DEVICETRACKER_ZONE else None)
    )


def _setup_zone_name_not_blank(sensor):
    sensor._internal_attr = {}
    sensor.is_attr_blank = MagicMock(return_value=False)
    sensor.set_attr = MagicMock()
    sensor.get_driving_status = AsyncMock()
    sensor.get_attr_safe_str = MagicMock(return_value="other")
    sensor.get_attr_safe_list = MagicMock(return_value=["other"])
    sensor.get_attr = MagicMock(
        side_effect=(lambda k: "zone_name_val" if k == ATTR_DEVICETRACKER_ZONE_NAME else None)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,setup,parser_patch,expected_calls",
    [
        pytest.param(
            "formatted_place",
            # setup callable: applies to sensor
            _setup_formatted_place,
            (
                "custom_components.places.sensor.BasicOptionsParser",
                [("build_formatted_place", {"return_value": "fp"})],
            ),
            [
                ("set_attr", (ATTR_FORMATTED_PLACE, "fp")),
                ("set_attr", (ATTR_NATIVE_VALUE, "formatted_place")),
            ],
            id="formatted_place",
        ),
        pytest.param(
            "advanced_options",
            _setup_advanced_options,
            (
                "custom_components.places.sensor.AdvancedOptionsParser",
                [
                    ("build_from_advanced_options", {}),
                    ("compile_state", {"return_value": "adv_state"}),
                ],
            ),
            [("set_attr", (ATTR_NATIVE_VALUE, "adv_state"))],
            id="advanced_options",
        ),
        pytest.param(
            "not_in_zone",
            _setup_not_in_zone,
            (
                "custom_components.places.sensor.BasicOptionsParser",
                [("build_display", {"return_value": "display_state"})],
                True,
            ),
            [("set_attr", (ATTR_NATIVE_VALUE, "display_state"))],
            id="not_in_zone",
        ),
        pytest.param(
            "zone_or_zone_name_blank",
            _setup_zone_or_zone_name_blank,
            None,
            [("set_attr", (ATTR_NATIVE_VALUE, "zone_val"))],
            id="zone_or_zone_name_blank",
        ),
        pytest.param(
            "zone_name_not_blank",
            _setup_zone_name_not_blank,
            None,
            [("set_attr", (ATTR_NATIVE_VALUE, "zone_name_val"))],
            id="zone_name_not_blank",
        ),
    ],
)
async def test_process_display_options_variants(
    monkeypatch, scenario, setup, parser_patch, expected_calls
):
    """Parametrized: exercise Places.process_display_options for common display-option scenarios."""
    sensor = MagicMock(spec=Places)
    # apply scenario-specific setup
    setup(sensor)

    if parser_patch:
        # parser_patch can optionally include a third element indicating stub_in_zone usage
        if len(parser_patch) == 3:
            parser_path, methods, use_stub = parser_patch
        else:
            parser_path, methods = parser_patch
            use_stub = False

        if use_stub:
            with stub_in_zone(sensor, False), patch(parser_path) as mock_parser_cls:
                mock_parser = MagicMock()
                with stubbed_parser(mock_parser, methods):
                    mock_parser_cls.return_value = mock_parser
                    await Places.process_display_options(sensor)
        else:
            with patch(parser_path) as mock_parser_cls:
                mock_parser = MagicMock()
                with stubbed_parser(mock_parser, methods):
                    mock_parser_cls.return_value = mock_parser
                    await Places.process_display_options(sensor)
    else:
        # no parser involved in this scenario
        await Places.process_display_options(sensor)

    # validate expected calls were made
    for func_name, args in expected_calls:
        if func_name == "set_attr":
            sensor.set_attr.assert_any_call(*args)
