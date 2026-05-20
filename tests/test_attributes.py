"""Tests for Places attribute storage compatibility."""

from collections.abc import MutableMapping

from homeassistant.const import CONF_NAME

from custom_components.places.attributes import PlacesAttributes
from custom_components.places.const import ATTR_INITIAL_UPDATE, ATTR_NATIVE_VALUE, ATTR_PLACE_NAME
from custom_components.places.sensor import Places


def test_places_attribute_blank_semantics(places_instance: Places) -> None:
    """Blank checks preserve the current falsey-value behavior."""
    places_instance.clear_attr("missing")
    places_instance.set_attr("empty_string", "")
    places_instance.set_attr("none_value", None)
    places_instance.set_attr("zero_value", 0)
    places_instance.set_attr("false_value", False)
    places_instance.set_attr("text_value", "home")

    assert places_instance.is_attr_blank("missing") is True
    assert places_instance.is_attr_blank("empty_string") is True
    assert places_instance.is_attr_blank("none_value") is True
    assert places_instance.is_attr_blank("zero_value") is False
    assert places_instance.is_attr_blank("false_value") is False
    assert places_instance.is_attr_blank("text_value") is False


def test_places_attributes_preserves_empty_initial_mapping() -> None:
    """An explicit empty initial mapping remains the backing storage object."""
    initial: MutableMapping[str, object] = {}

    attributes = PlacesAttributes(initial)

    assert attributes.data is initial


def test_places_attribute_safe_conversions(places_instance: Places) -> None:
    """Safe conversion helpers keep current fallback behavior."""
    places_instance.set_attr("int_text", "12")
    places_instance.set_attr("bad_float", object())
    places_instance.set_attr("items", ["a", "b"])
    places_instance.set_attr("not_items", "a,b")
    places_instance.set_attr("mapping", {"a": 1})
    places_instance.set_attr("not_mapping", ["a"])

    assert places_instance.get_attr_safe_str("int_text") == "12"
    assert places_instance.get_attr_safe_float("int_text") == 12.0
    assert places_instance.get_attr_safe_float("bad_float") == 0.0
    assert places_instance.get_attr_safe_list("items") == ["a", "b"]
    assert places_instance.get_attr_safe_list("not_items") == []
    assert places_instance.get_attr_safe_dict("mapping") == {"a": 1}
    assert places_instance.get_attr_safe_dict("not_mapping") == {}


def test_places_attribute_cleanup_and_restore(places_instance: Places) -> None:
    """Cleanup removes blank values and restore replaces the whole mapping."""
    places_instance.set_attr("keep_zero", 0)
    places_instance.set_attr("remove_empty", "")
    places_instance.set_attr("remove_none", None)
    places_instance.set_attr(ATTR_PLACE_NAME, "Library")

    places_instance.cleanup_attributes()

    attrs = places_instance.get_internal_attr()
    assert attrs[CONF_NAME] == "TestSensor"
    assert attrs["keep_zero"] == 0
    assert attrs[ATTR_INITIAL_UPDATE] is False
    assert attrs[ATTR_PLACE_NAME] == "Library"
    assert "remove_empty" not in attrs
    assert "remove_none" not in attrs


async def test_places_attribute_restore_previous_attr(
    places_instance: Places,
) -> None:
    """Rollback restores the exact previous mapping object and content."""
    previous: MutableMapping[str, object] = {
        CONF_NAME: "Restored",
        ATTR_NATIVE_VALUE: "Old State",
    }

    await places_instance.restore_previous_attr(previous)

    assert places_instance.get_internal_attr() is previous
    assert places_instance.get_internal_attr() == previous
