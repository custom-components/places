"""Mutable Place state shared by the coordinator and an isolated Update attempt."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, TypeVar

from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.const import CONF_ZONE
from homeassistant.core import HomeAssistant

from .advanced_options import AdvancedOptionsParser
from .attributes import PlacesAttributes
from .basic_options import BasicOptionsParser
from .const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_DRIVING,
    ATTR_FORMATTED_PLACE,
    ATTR_NATIVE_VALUE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
    CONF_DEVICETRACKER_ID,
)

_AttrT = TypeVar("_AttrT", default=Any)


class PlacesState:
    """Hold Place attributes and render the main sensor's native value."""

    def __init__(
        self, hass: HomeAssistant, attributes: MutableMapping[str, Any] | None = None
    ) -> None:
        """Initialize Place state from an optional attribute mapping.

        Args:
            hass (HomeAssistant): Runtime used to resolve Home Assistant zones.
            attributes (MutableMapping[str, Any] | None): Mapping owned by this state.
        """
        self.hass = hass
        self._attributes = PlacesAttributes(attributes)
        self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None

    def replace_attributes(self, attributes: MutableMapping[str, Any]) -> None:
        """Replace the Place and its mirrored native value together.

        Args:
            attributes (MutableMapping[str, Any]): Complete replacement Place attributes.
        """
        self._attributes.data = attributes
        native_value = self.get_attr(ATTR_NATIVE_VALUE)
        self._native_value = str(native_value) if native_value is not None else None

    def get_internal_attr(self) -> MutableMapping[str, Any]:
        """Return the mutable runtime attribute mapping.

        Returns:
            MutableMapping[str, Any]:
                Live mutable mapping that stores all runtime attributes.
        """
        return self._attributes.data

    def is_attr_blank(self, attr: str) -> bool:
        """Return whether a stored attribute is blank.

        Args:
            attr (str):
                Attribute name to inspect.

        Returns:
            bool:
                ``True`` when the attribute is missing or contains a blank value.
        """
        return self._attributes.is_blank(attr)

    def get_attr(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Read a stored runtime attribute.

        Args:
            attr (str | None):
                Attribute name to read.
            default (_AttrT | None):
                Value returned when the attribute is unset.

        Returns:
            _AttrT | None:
                Stored attribute value, or ``default`` when unset.
        """
        return self._attributes.get(attr, default)

    def get_attr_safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Read a stored runtime attribute as a safe string.

        Args:
            attr (str | None):
                Attribute name to read.
            default (object | None):
                Value converted when the attribute is unset.

        Returns:
            str:
                String value, or an empty string when no value is available.
        """
        return self._attributes.safe_str(attr, default)

    def get_attr_safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Read a stored runtime attribute as a safe float.

        Args:
            attr (str | None):
                Attribute name to read.
            default (object | None):
                Value converted when the attribute is unset.

        Returns:
            float:
                Float value, or ``0.0`` when conversion is not possible.
        """
        return self._attributes.safe_float(attr, default)

    def get_attr_safe_list(self, attr: str | None, default: object | None = None) -> list[Any]:
        """Read a stored runtime attribute as a safe list.

        Args:
            attr (str | None):
                Attribute name to read.
            default (object | None):
                Value used when the attribute is unset.

        Returns:
            list[Any]:
                Stored list, or an empty list when no list is available.
        """
        return self._attributes.safe_list(attr, default)

    def get_attr_safe_dict(
        self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
    ) -> MutableMapping[str, _AttrT]:
        """Read a stored runtime attribute as a safe mapping.

        Args:
            attr (str | None):
                Attribute name to read.
            default (MutableMapping[str, _AttrT] | None):
                Mapping used when the attribute is unset.

        Returns:
            MutableMapping[str, _AttrT]:
                Stored mapping, or an empty mapping when no mapping is available.
        """
        return self._attributes.safe_dict(attr, default)

    def set_attr(self, attr: str, value: object | None = None) -> None:
        """Store a runtime attribute.

        Args:
            attr (str):
                Attribute name to update.
            value (object | None):
                Value to store.
        """
        self._attributes.set(attr, value)

    def clear_attr(self, attr: str) -> None:
        """Remove a runtime attribute.

        Args:
            attr (str):
                Attribute name to remove.
        """
        self._attributes.clear(attr)
        if attr == ATTR_NATIVE_VALUE:
            self._native_value = None

    def set_native_value(self, value: object) -> None:
        """Update the display state and mirror it into runtime attributes.

        Args:
            value (object):
                New state value for the main Places sensor.
        """
        if value is None:
            self.clear_attr(ATTR_NATIVE_VALUE)
            return
        self._native_value = str(value)
        self.set_attr(ATTR_NATIVE_VALUE, self._native_value)

    async def async_cleanup_attributes(self) -> None:
        """Remove blank runtime attributes."""
        self._attributes.cleanup()

    async def in_zone(self) -> bool:
        """Return whether the tracked entity is in a real non-passive zone.

        Returns:
            bool:
                ``True`` when the tracker is currently in an active HA zone.
        """
        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone = self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE).lower()
            zone_state = self.hass.states.get(f"{CONF_ZONE}.{zone}")
            if (
                self.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] == CONF_ZONE
                or (
                    "stationary" in zone
                    or zone.startswith(("statzon", "ic3_statzone_"))
                    or zone in {"away", "not_home", "notset", "not_set"}
                )
                or (
                    zone_state is not None
                    and zone_state.attributes.get(ATTR_PASSIVE, False) is True
                )
            ):
                return False
            return True
        return False

    async def get_driving_status(self) -> None:
        """Set the driving marker when movement implies road travel."""
        self.clear_attr(ATTR_DRIVING)
        if (
            not await self.in_zone()
            and self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and (
                self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                or self.get_attr(ATTR_PLACE_TYPE) == "motorway"
            )
        ):
            self.set_attr(ATTR_DRIVING, "Driving")

    async def process_display_options(self) -> None:
        """Render configured display options into the native value."""
        self.clear_attr(ATTR_NATIVE_VALUE)
        display_options: list[str] = []
        if not self.is_attr_blank(ATTR_DISPLAY_OPTIONS):
            display_options.extend(
                option.strip() for option in self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS).split(",")
            )
        self.set_attr(ATTR_DISPLAY_OPTIONS_LIST, display_options)

        await self.get_driving_status()

        if "formatted_place" in display_options:
            basic_parser = BasicOptionsParser(
                coordinator=self,
                internal_attr=self.get_internal_attr(),
                display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            )
            formatted_place = await basic_parser.build_formatted_place()
            self.set_attr(ATTR_FORMATTED_PLACE, formatted_place)
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_FORMATTED_PLACE))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if any(ext in self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS) for ext in ["(", ")", "[", "]"]):
            advanced_parser = AdvancedOptionsParser(
                coordinator=self,
                curr_options=self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS),
            )
            await advanced_parser.build_from_advanced_options()
            self.set_attr(ATTR_NATIVE_VALUE, await advanced_parser.compile_state())
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if not await self.in_zone():
            basic_parser = BasicOptionsParser(
                coordinator=self,
                internal_attr=self.get_internal_attr(),
                display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            )
            state = await basic_parser.build_display()
            if state:
                self.set_attr(ATTR_NATIVE_VALUE, state)
                self._native_value = state
            return

        if (
            "zone" in display_options and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
        ) or self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
