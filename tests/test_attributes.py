"""Tests for Places attribute storage helpers on the coordinator."""

from __future__ import annotations

from collections.abc import MutableMapping
from unittest.mock import MagicMock

from homeassistant.const import CONF_NAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.attributes import PlacesAttributes
from custom_components.places.const import (
    ATTR_INITIAL_UPDATE,
    ATTR_NATIVE_VALUE,
    ATTR_PLACE_NAME,
    CONF_DEVICETRACKER_ID,
)
from custom_components.places.coordinator import PlacesUpdateCoordinator


def _coordinator(mock_hass: MagicMock) -> PlacesUpdateCoordinator:
    """Return a coordinator with empty Home Assistant state lookups."""
    mock_hass.states.get.return_value = None
    entry = MockConfigEntry(
        domain="places",
        data={CONF_NAME: "TestSensor", CONF_DEVICETRACKER_ID: "device_tracker.test"},
    )
    return PlacesUpdateCoordinator(mock_hass, entry, {}, MagicMock())


def test_places_attribute_blank_semantics(mock_hass: MagicMock) -> None:
    """Blank checks preserve the current falsey-value behavior."""
    coordinator = _coordinator(mock_hass)
    coordinator.clear_attr("missing")
    coordinator.set_attr("empty_string", "")
    coordinator.set_attr("none_value", None)
    coordinator.set_attr("zero_value", 0)
    coordinator.set_attr("false_value", False)
    coordinator.set_attr("text_value", "home")

    assert coordinator.is_attr_blank("missing") is True
    assert coordinator.is_attr_blank("empty_string") is True
    assert coordinator.is_attr_blank("none_value") is True
    assert coordinator.is_attr_blank("zero_value") is False
    assert coordinator.is_attr_blank("false_value") is False
    assert coordinator.is_attr_blank("text_value") is False


def test_places_attributes_preserves_empty_initial_mapping() -> None:
    """An explicit empty initial mapping remains the backing storage object."""
    initial: MutableMapping[str, object] = {}

    attributes = PlacesAttributes(initial)

    assert attributes.data is initial


def test_places_attribute_safe_conversions(mock_hass: MagicMock) -> None:
    """Safe conversion helpers keep current fallback behavior."""
    coordinator = _coordinator(mock_hass)
    coordinator.set_attr("int_text", "12")
    coordinator.set_attr("bad_float", object())
    coordinator.set_attr("items", ["a", "b"])
    coordinator.set_attr("not_items", "a,b")
    coordinator.set_attr("mapping", {"a": 1})
    coordinator.set_attr("not_mapping", ["a"])

    assert coordinator.get_attr_safe_str("int_text") == "12"
    assert coordinator.get_attr_safe_float("int_text") == 12.0
    assert coordinator.get_attr_safe_float("bad_float") == 0.0
    assert coordinator.get_attr_safe_list("items") == ["a", "b"]
    assert coordinator.get_attr_safe_list("not_items") == []
    assert coordinator.get_attr_safe_dict("mapping") == {"a": 1}
    assert coordinator.get_attr_safe_dict("not_mapping") == {}


async def test_places_attribute_cleanup_and_restore(mock_hass: MagicMock) -> None:
    """Cleanup removes blank values while leaving configured state intact."""
    coordinator = _coordinator(mock_hass)
    coordinator.set_attr("keep_zero", 0)
    coordinator.set_attr("remove_empty", "")
    coordinator.set_attr("remove_none", None)
    coordinator.set_attr(ATTR_PLACE_NAME, "Library")

    await coordinator.async_cleanup_attributes()

    attrs = coordinator.get_internal_attr()
    assert attrs[CONF_NAME] == "TestSensor"
    assert attrs["keep_zero"] == 0
    assert attrs[ATTR_INITIAL_UPDATE] is True
    assert attrs[ATTR_PLACE_NAME] == "Library"
    assert "remove_empty" not in attrs
    assert "remove_none" not in attrs


async def test_places_attribute_restore_previous_attr(mock_hass: MagicMock) -> None:
    """Rollback restores the exact previous mapping object and content."""
    coordinator = _coordinator(mock_hass)
    previous: MutableMapping[str, object] = {
        CONF_NAME: "Restored",
        ATTR_NATIVE_VALUE: "Old State",
    }

    await coordinator.restore_previous_attr(previous)

    assert coordinator.get_internal_attr() is previous
    assert coordinator.get_internal_attr() == previous


@pytest.mark.parametrize(
    ("persisted_attr", "expected_initial_update"),
    [
        ({}, True),
        ({ATTR_NATIVE_VALUE: "Restored"}, False),
    ],
)
def test_coordinator_import_persisted_attrs_updates_initial_update(
    mock_hass: MagicMock,
    persisted_attr: MutableMapping[str, object],
    expected_initial_update: bool,
) -> None:
    """Persisted attrs only clear the initial-update guard when data is imported."""
    coordinator = _coordinator(mock_hass)

    coordinator.import_persisted_attributes(persisted_attr)

    assert coordinator.get_attr(ATTR_INITIAL_UPDATE) is expected_initial_update
