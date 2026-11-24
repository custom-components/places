"""Render Advanced display options from the current Place data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_NAME

from .const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
    ATTR_ROUTE_NUMBER,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    DISPLAY_OPTIONS_MAP,
)
from .display_options import DisplayOptions, parse_display_options

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class AdvancedOptionsParser:
    """Render bracketed and filtered Display options into a main sensor state."""

    def __init__(
        self, coordinator: PlacesUpdateCoordinator, curr_options: str | DisplayOptions
    ) -> None:
        """Initialize the renderer for a single Display options expression.

        Args:
            coordinator (PlacesUpdateCoordinator):
                Places coordinator that provides attribute access helpers.
            curr_options (str | DisplayOptions):
                Display options expression or its parsed representation.
        """
        self.coordinator = coordinator
        self.options = (
            parse_display_options(curr_options) if isinstance(curr_options, str) else curr_options
        )
        self.state_list: list[str] = []

    async def build_from_advanced_options(self) -> None:
        """Append available values in display order and join adjacent address pairs."""
        if self.options.bracket_mismatch:
            _LOGGER.error("Mismatched delimiters in Display options: %s", self.options.source)
            return

        pending = list(reversed(self.options.items))
        previous_field: str | None = None
        while pending:
            item = pending.pop()
            if not item.token:
                continue
            filters = item.filters(self.options.source)
            state = await self.get_option_state(
                item.token,
                filters.include,
                filters.exclude,
                filters.include_attributes,
                filters.exclude_attributes,
            )
            if not state:
                pending.extend(reversed(item.fallback))
                continue
            mapped_field = DISPLAY_OPTIONS_MAP.get(item.token.lower())
            if previous_field == ATTR_STREET_NUMBER and mapped_field in {
                ATTR_STREET,
                ATTR_ROUTE_NUMBER,
            }:
                self.state_list[-1] += f" {state}"
            else:
                self.state_list.append(state)
            previous_field = mapped_field

    async def get_option_state(
        self,
        opt: str,
        incl: Sequence[str] | None = None,
        excl: Sequence[str] | None = None,
        incl_attr: Mapping[str, Sequence[str]] | None = None,
        excl_attr: Mapping[str, Sequence[str]] | None = None,
    ) -> str | None:
        """Return an option value after applying zone and filter constraints.

        Args:
            opt (str):
                Display option name to resolve through ``DISPLAY_OPTIONS_MAP``.
            incl (Sequence[str] | None):
                Lowercase option values that are allowed.
            excl (Sequence[str] | None):
                Lowercase option values that are suppressed.
            incl_attr (Mapping[str, Sequence[str]] | None):
                Attribute filters that must match before ``opt`` is used.
            excl_attr (Mapping[str, Sequence[str]] | None):
                Attribute filters that suppress ``opt`` when matched.

        Returns:
            str | None:
                Resolved display string, or ``None`` when the option is blank,
                outside its zone context, or filtered out.
        """
        incl = [] if incl is None else incl
        excl = [] if excl is None else excl
        incl_attr = {} if incl_attr is None else incl_attr
        excl_attr = {} if excl_attr is None else excl_attr
        if opt:
            opt = str(opt).lower().strip()
        _LOGGER.debug(
            "(%s) [get_option_state] Option: %s", self.coordinator.get_attr(CONF_NAME), opt
        )
        mapped_opt: str | None = DISPLAY_OPTIONS_MAP.get(opt)
        out: str | None = self.coordinator.get_attr(mapped_opt)
        if (
            mapped_opt in {ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME}
            and not await self.coordinator.in_zone()
        ):
            out = None
        _LOGGER.debug(
            "(%s) [get_option_state] State: %s", self.coordinator.get_attr(CONF_NAME), out
        )
        _LOGGER.debug(
            "(%s) [get_option_state] incl list: %s", self.coordinator.get_attr(CONF_NAME), incl
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl list: %s", self.coordinator.get_attr(CONF_NAME), excl
        )
        _LOGGER.debug(
            "(%s) [get_option_state] incl_attr dict: %s",
            self.coordinator.get_attr(CONF_NAME),
            incl_attr,
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl_attr dict: %s",
            self.coordinator.get_attr(CONF_NAME),
            excl_attr,
        )
        if out:
            if (incl and str(out).strip().lower() not in incl) or (
                excl and str(out).strip().lower() in excl
            ):
                out = None
            if incl_attr:
                for attr, states in incl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_attr: %s / State: %s",
                        self.coordinator.get_attr(CONF_NAME),
                        attr,
                        self.coordinator.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_states: %s",
                        self.coordinator.get_attr(CONF_NAME),
                        states,
                    )
                    map_attr: str | None = DISPLAY_OPTIONS_MAP.get(attr)
                    if (
                        not map_attr
                        or self.coordinator.is_attr_blank(map_attr)
                        or self.coordinator.get_attr(map_attr) not in states
                    ):
                        out = None
            if excl_attr:
                for attr, states in excl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_attr: %s / State: %s",
                        self.coordinator.get_attr(CONF_NAME),
                        attr,
                        self.coordinator.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_states: %s",
                        self.coordinator.get_attr(CONF_NAME),
                        states,
                    )
                    if self.coordinator.get_attr(DISPLAY_OPTIONS_MAP.get(attr)) in states:
                        out = None
            _LOGGER.debug(
                "(%s) [get_option_state] State after incl/excl: %s",
                self.coordinator.get_attr(CONF_NAME),
                out,
            )
        if out:
            out = str(out)
            if out == out.lower() and mapped_opt in {
                ATTR_DEVICETRACKER_ZONE_NAME,
                ATTR_PLACE_TYPE,
                ATTR_PLACE_CATEGORY,
            }:
                out = out.title()
            return out.strip()
        return None

    async def compile_state(self) -> str:
        """Join resolved option values into the final coordinator state.

        Returns:
            str:
                Comma-separated state string, with street number and street joined
                by a space when they are adjacent.
        """
        return ", ".join(self.state_list)
